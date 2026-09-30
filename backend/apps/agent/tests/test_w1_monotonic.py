"""Product contract: docs/contrato-elegibilidad-preclaim-b3-c4-w1-v1.md."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent import durable, services
from apps.agent.models import Conversation, HumanHandoff, TurnWork
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization


class MonotonicEligibilityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MONO', timezone='UTC')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='mono-channel')
        self.origin = timezone.now()

    def inbound(self, seconds, body='ordinary', key=None):
        instant = self.origin + timedelta(seconds=seconds)
        with patch.object(services, 'db_now', return_value=instant), patch.object(
                durable, 'db_now', return_value=instant), patch(
                'django.utils.timezone.now', return_value=instant):
            message = services.ingest_inbound_message(self.channel,
                wamid=key or f'mono-{seconds}-{Message.objects.count()}',
                wa_id='5215512345678', body=body)
        if message is not None:
            self.conv = message.conversation
        return message

    def claim(self, seconds=9):
        with patch.object(durable, 'db_now', return_value=self.origin + timedelta(seconds=seconds)):
            return durable.claim_turn(self.conv.pk)

    def deadlines(self):
        return list(Message.objects.filter(conversation=self.conv, direction='in')
                    .order_by('created_at', 'id').values_list('available_at', flat=True))

    def assert_context(self, witness, messages):
        context = durable.context_for_work(witness)
        self.assertEqual(context.inbound_ids, tuple(m.pk for m in messages))
        self.assertEqual(context.anchor.message_id, messages[-1].pk)
        self.assertEqual(context.history_before.message_id, messages[0].pk)
        self.assertEqual(tuple(e.text for e in context.events), tuple(m.body for m in messages))
        self.assertEqual(TurnWork.objects.get(pk=witness.turn_work_id).attempts, 1)
        return context

    def test_w1_mono_01_before_8_minus_epsilon_extends(self):
        self.inbound(0)
        self.inbound(7.999999)
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=15.999999)] * 2)
        self.assertIsNone(self.claim(8))
        self.assertFalse(TurnWork.objects.exists())

    def test_w1_mono_02_exactly_8_latches(self):
        a, b = self.inbound(0), self.inbound(8)
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=8)] * 2)
        self.assert_context(self.claim(8), [a, b])

    def test_w1_mono_03_after_8_plus_epsilon_latches(self):
        a, b = self.inbound(0), self.inbound(8.000001)
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=8)] * 2)
        self.assert_context(self.claim(8.000001), [a, b])

    def test_w1_mono_04_ingest_wins_all_members_freeze_in_claim(self):
        a, b, c = self.inbound(0), self.inbound(9), self.inbound(10)
        self.assertFalse(TurnWork.objects.exists())
        self.assert_context(self.claim(10), [a, b, c])

    def test_w1_mono_05_claim_wins_new_input_defers_and_continues(self):
        a = self.inbound(0)
        first = self.claim(8)
        context = self.assert_context(first, [a])
        b = self.inbound(9, 'mejor viernes')
        self.assertTrue(durable.has_new_input(TurnWork.objects.get(pk=first.turn_work_id)))
        self.assertEqual(context, durable.context_for_work(first))
        durable.finalize_turn(first, outputs=[{'body': 'obsolete'}])
        self.assertEqual(TurnWork.objects.get(pk=first.turn_work_id).outcome_code, 'deferred_to_new_input')
        self.assertFalse(Message.objects.filter(direction='out').exists())
        second = self.claim(17)
        self.assertNotEqual(first.turn_work_id, second.turn_work_id)
        self.assert_context(second, [b])

    def test_w1_mono_06_preclaim_date_correction_is_in_original_context(self):
        a = self.inbound(0, 'quiero cita mañana')
        b = self.inbound(9, 'mejor el viernes')
        self.assert_context(self.claim(9), [a, b])

    def test_w1_mono_07_fragments_and_equal_timestamp_order(self):
        msgs = [self.inbound(t, body) for t, body in (
            (0, 'quiero cita'), (1, 'para Firulais'), (2, 'mañana'), (10, 'no, mejor viernes'))]
        # IDs decide ties in the persisted causal order, not body/date semantics.
        Message.objects.filter(pk=msgs[1].pk).update(created_at=msgs[0].created_at)
        self.assert_context(self.claim(10), msgs)

    def test_w1_mono_08_hard_cap_25_survives_rolling(self):
        msgs = [self.inbound(t) for t in (0, 7, 14, 21, 24)]
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=25)] * 5)
        self.assertIsNone(self.claim(24.999999))
        msgs.append(self.inbound(25))
        self.assert_context(self.claim(25), msgs)

    @override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
    def test_w1_mono_09_safety_before_ready_is_immediate(self):
        self.inbound(0)
        signal = self.inbound(1, 'Mi perro está convulsionando ahora')
        self.assertEqual(HumanHandoff.objects.get().source_message_id, signal.pk)
        self.assertTrue(Message.objects.filter(semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE).exists())
        self.assertFalse(TurnWork.objects.filter(status=TurnWork.PROCESSING).exists())

    def test_w1_mono_10_takeover_fences_ready_claim(self):
        from rest_framework.test import APIClient
        from .test_inbox_api import _make_user
        a = self.inbound(0)
        witness = self.claim(8)
        client = APIClient()
        client.force_authenticate(_make_user('mono-human', self.org, 'ADMIN'))
        self.assertEqual(client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/').status_code, 200)
        self.inbound(9)
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(witness, outputs=[{'body': 'obsolete'}])
        self.assertFalse(Message.objects.filter(direction='out', author_type='agent').exists())
        self.assertEqual(Message.objects.get(pk=a.pk).turn_work_id, witness.turn_work_id)

    def test_legacy_null_is_ready_and_new_member_is_also_eligible(self):
        a = self.inbound(0)
        Message.objects.filter(pk=a.pk).update(available_at=None)
        b = self.inbound(1)
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=1)] * 2)
        self.assert_context(self.claim(1), [a, b])

    def test_stale_application_clock_cannot_withdraw_ready(self):
        a = self.inbound(0)
        fresh = self.origin + timedelta(seconds=9)
        with patch.object(services, 'db_now', return_value=fresh), patch(
                'django.utils.timezone.now', return_value=self.origin + timedelta(seconds=7)):
            b = services.ingest_inbound_message(self.channel, wamid='stale-clock',
                wa_id='5215512345678', body='correction')
        self.assertEqual(self.deadlines(), [self.origin + timedelta(seconds=8)] * 2)
        self.assert_context(self.claim(9), [a, b])
