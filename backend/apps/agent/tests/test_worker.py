"""
test_worker.py — É-F0 PR-5: inbox-como-cola y sender del outbox.
"""
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.agent.services import ingest_inbound_message
from apps.agent.tier0 import T0_DISABLED, T0_GREET
from apps.agent.worker import (
    SEND_MAX_ATTEMPTS,
    process_pending_conversations,
    send_pending_outbound,
)
from apps.channels.models import ChannelAccount, Message
from apps.channels.providers import SendResult
from apps.organizations.models import Organization


class FakeProvider:
    """Stub del proveedor: comportamiento configurable por test."""

    def __init__(self, channel_account, error=None, wamid="wamid.FAKE"):
        self.channel_account = channel_account
        self.error = error
        self.wamid = wamid
        self.sent = []

    def send_text(self, to_wa_id, body):
        if self.error is not None:
            return self.error
        self.sent.append((to_wa_id, body))
        return SendResult('accepted', provider_id=self.wamid)


def _factory(error=None, wamid="wamid.FAKE"):
    def factory(channel_account):
        return FakeProvider(channel_account, error=error, wamid=wamid)
    return factory


def _later():
    """`now` ya vencida la ventana silenciosa de los entrantes (W1-4: 8 s)."""
    return timezone.now() + timedelta(seconds=15)


class ProcessPendingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Worker Org", timezone="UTC",
        )
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="700100700",
        )

    def _inbound(self, wamid, body="hola"):
        return ingest_inbound_message(
            self.channel, wamid=wamid, wa_id="5215577778888", body=body,
        )

    def test_first_inbound_gets_greeting_when_enabled(self):
        AgentSettings.objects.create(organization=self.org, enabled=True)
        message = self._inbound("wamid.W1")

        n = process_pending_conversations(now=_later())
        self.assertEqual(n, 1)

        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_PROCESSED)
        outbound = Message.objects.get(
            conversation=message.conversation,
            direction=Message.DIRECTION_OUT,
        )
        # `startswith`: fuera del horario sembrado el saludo lleva además el
        # aviso de fuera de horario (INT-03).
        self.assertTrue(
            outbound.body.startswith(T0_GREET.format(clinic="Worker Org")),
            outbound.body)
        self.assertEqual(outbound.status, Message.STATUS_PENDING)
        self.assertEqual(outbound.author_type, Message.AUTHOR_SYSTEM)

    def test_disabled_or_missing_settings_gets_t0_disabled(self):
        message = self._inbound("wamid.W2")
        process_pending_conversations(now=_later())
        outbound = Message.objects.get(
            conversation=message.conversation,
            direction=Message.DIRECTION_OUT,
        )
        self.assertEqual(outbound.body, T0_DISABLED.format(clinic="Worker Org"))

    def test_second_inbound_does_not_duplicate_greeting(self):
        AgentSettings.objects.create(organization=self.org, enabled=True)
        self._inbound("wamid.W3a")
        process_pending_conversations(now=_later())

        self._inbound("wamid.W3b", body="¿están abiertos?")
        n = process_pending_conversations(now=_later())
        self.assertEqual(n, 1)  # procesó el entrante…
        self.assertEqual(
            Message.objects.filter(direction=Message.DIRECTION_OUT).count(),
            1,  # …pero sin segundo saludo (lo sigue un humano, F0)
        )

    def test_message_within_drain_delay_is_not_picked_yet(self):
        self._inbound("wamid.W4")
        n = process_pending_conversations(now=timezone.now())
        self.assertEqual(n, 0)  # available_at (+3s) aún no vence

    def test_discarded_messages_are_ignored(self):
        ContactIdentity.objects.create(
            organization=self.org, external_id="5215500009999",
            is_blocked=True,
        )
        self._inboundfor_blocked = ingest_inbound_message(
            self.channel, wamid="wamid.W5", wa_id="5215500009999", body="x",
        )
        n = process_pending_conversations(now=_later())
        self.assertEqual(n, 0)
        self.assertEqual(
            Message.objects.filter(direction=Message.DIRECTION_OUT).count(), 0
        )


class SendPendingTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Sender Org", timezone="UTC",
        )
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="700200700",
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215512121212",
        )
        self.conversation = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, last_inbound_at=timezone.now(),
        )

    def _outbound(self, **kwargs):
        defaults = dict(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conversation,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta",
            origin_epoch=self.conversation.ownership_epoch,
        )
        defaults.update(kwargs)
        return Message.objects.create(**defaults)

    def test_successful_send_marks_sent_with_wamid(self):
        message = self._outbound()
        n = send_pending_outbound(provider_factory=_factory(wamid="wamid.OK"))
        self.assertEqual(n, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_SENT)
        self.assertEqual(message.external_message_id, "wamid.OK")
        self.assertEqual(message.attempts, 1)

    def test_retryable_error_schedules_backoff(self):
        message = self._outbound()
        send_pending_outbound(
            provider_factory=_factory(error=SendResult('known_rejected', code='meta_130429', retryable=True)),
        )
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_PENDING)
        self.assertEqual(message.attempts, 1)
        self.assertIsNotNone(message.next_attempt_at)
        self.assertGreater(message.next_attempt_at, timezone.now())

    def test_backoff_message_is_not_retried_early(self):
        message = self._outbound(
            next_attempt_at=timezone.now() + timedelta(minutes=10),
        )
        n = send_pending_outbound(provider_factory=_factory())
        self.assertEqual(n, 0)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_PENDING)

    def test_exhausted_retries_mark_failed(self):
        message = self._outbound(attempts=SEND_MAX_ATTEMPTS - 1)
        send_pending_outbound(
            provider_factory=_factory(error=SendResult('known_rejected', code='meta_130429', retryable=True)),
        )
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_FAILED)

    def test_non_retryable_error_fails_immediately(self):
        message = self._outbound()
        send_pending_outbound(
            provider_factory=_factory(error=SendResult('known_rejected', code='meta_190')),
        )
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_FAILED)
        self.assertEqual(message.attempts, 1)

    def test_closed_session_window_fails_without_sending(self):
        """Spec §2.8: fuera de 24 h del último entrante no va texto libre
        (las plantillas HSM llegan en F3)."""
        self.conversation.last_inbound_at = timezone.now() - timedelta(hours=25)
        self.conversation.save(update_fields=["last_inbound_at"])
        message = self._outbound()
        factory = _factory()
        send_pending_outbound(provider_factory=factory)
        message.refresh_from_db()
        self.assertEqual(message.status, Message.STATUS_FAILED)
        self.assertIn("24h", message.failure_reason)
        self.assertEqual(message.attempts, 0)  # ni siquiera intentó el HTTP


class B1WorkerContextTests(TestCase):
    """CTX-01 runs through the actual worker claim and planner entry point."""

    def setUp(self):
        from apps.users.services import ensure_agent_user
        self.org = Organization.objects.create(name='B1 Worker', timezone='UTC')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='b1-worker')
        agent_user, _ = ensure_agent_user(self.org)
        AgentSettings.objects.create(organization=self.org, enabled=True, agent_user=agent_user)

    def test_claimed_burst_is_shared_and_first_contact_has_no_invented_history(self):
        import json
        from unittest.mock import patch
        from apps.agent import planner, policy, prompts
        from apps.agent.llm import LLMResult, StubLLMClient

        first = ingest_inbound_message(self.channel, wamid='b1-worker-1',
                                       wa_id='5215511110000', body='hola')
        last = ingest_inbound_message(self.channel, wamid='b1-worker-2',
                                      wa_id='5215511110000', body='¿qué horarios tienen?')
        captured = {}
        assemble = prompts.assemble_messages

        def capture(conversation, **kwargs):
            captured['context'] = kwargs['turn_context']
            self.assertEqual(set(Message.objects.filter(
                pk__in=kwargs['turn_context'].inbound_ids).values_list('status', flat=True)),
                {Message.STATUS_PENDING})
            # A real later input arrives during this attempt. It belongs to a
            # subsequent turn even though the prompt has not been assembled yet.
            later = ingest_inbound_message(self.channel, wamid='b1-worker-later',
                                           wa_id='5215511110000', body='mensaje posterior')
            Message.objects.filter(pk=later.pk).update(
                available_at=timezone.now() + timedelta(minutes=1))
            captured['prompt'] = assemble(conversation, **kwargs)
            return captured['prompt']

        stub = StubLLMClient(scripted=[LLMResult(
            kind='text', text='Puedo ayudarte con los horarios de la clínica.')])
        with (patch.object(planner, 'handle_inbound', wraps=planner.handle_inbound) as entry,
              patch.object(planner, 'get_llm_client', return_value=stub),
              patch.object(policy, 'evaluate', wraps=policy.evaluate) as evaluate,
              patch.object(prompts, 'assemble_messages', side_effect=capture),
              patch.object(planner, '_observe_turn_facts', wraps=planner._observe_turn_facts) as observe):
            self.assertEqual(process_pending_conversations(now=_later()), 1)
        entry.assert_called_once()
        turn = entry.call_args.kwargs['turn_context']
        self.assertEqual(turn.inbound_ids, (first.pk, last.pk))
        self.assertIs(evaluate.call_args.kwargs['turn_context'], turn)
        self.assertIs(captured['context'], turn)
        self.assertEqual(observe.call_args.args[0], turn.burst_text)
        data = json.loads(captured['prompt'][0]['content'].split('\n', 1)[1])
        self.assertNotIn('ya_hablamos_antes', data)
        self.assertEqual([m['content'] for m in captured['prompt'] if m['role'] == 'user'],
                         ['hola', '¿qué horarios tienen?'])
        self.assertNotIn('mensaje posterior', str(captured['prompt']))
        self.assertEqual(Message.objects.get(external_message_id='b1-worker-later').status,
                         Message.STATUS_PENDING)
