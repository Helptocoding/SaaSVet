"""
test_webhook.py — É-F0 PR-4: webhook de WhatsApp.

Cubre el contrato de seguridad (firma HMAC fail-closed, handshake) y el de
transporte (routing número→org R1, dedup R5, acuses de entrega). El payload
de fixture replica la forma real de Meta Cloud API.
"""
import hashlib
import hmac
import json

from django.test import TestCase, override_settings

from apps.agent.models import Conversation
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings

SECRET = "test-app-secret"
VERIFY = "test-verify-token"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _meta_payload(phone_number_id, wamid="wamid.001", wa_id="5215511223344",
                  text="hola", profile_name="Ana"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{
                        "wa_id": wa_id,
                        "profile": {"name": profile_name},
                    }],
                    "messages": [{
                        "id": wamid,
                        "from": wa_id,
                        "timestamp": "1752600000",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY)
class WebhookHandshakeTests(TestCase):
    def test_valid_handshake_echoes_challenge(self):
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY,
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"12345")

    def test_wrong_verify_token_rejected(self):
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": "nope",
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 403)

    @override_settings(WHATSAPP_VERIFY_TOKEN="")
    def test_unconfigured_verify_token_rejects(self):
        """Fail-closed: sin token configurado no hay handshake válido."""
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": "",
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 403)


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY)
class WebhookSignatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="WH Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="111222333",
        )

    def _post(self, payload, signature=None):
        body = json.dumps(payload).encode()
        headers = {}
        if signature is not None:
            headers["HTTP_X_HUB_SIGNATURE_256"] = signature
        return self.client.post(
            "/hooks/whatsapp/", body,
            content_type="application/json", **headers,
        )

    def test_missing_signature_rejected_nothing_persisted(self):
        r = self._post(_meta_payload("111222333"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Message.all_objects.count(), 0)

    def test_bad_signature_rejected_nothing_persisted(self):
        r = self._post(_meta_payload("111222333"), signature="sha256=" + "0" * 64)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Message.all_objects.count(), 0)

    @override_settings(WHATSAPP_APP_SECRET="")
    def test_unconfigured_secret_fails_closed(self):
        payload = _meta_payload("111222333")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 403)

    def test_valid_signature_ingests_message(self):
        payload = _meta_payload("111222333", wamid="wamid.SIG1")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)

        message = Message.objects.get(external_message_id="wamid.SIG1")
        self.assertEqual(message.organization, self.org)
        self.assertEqual(message.body, "hola")
        self.assertEqual(message.status, Message.STATUS_PENDING)
        conv = message.conversation
        self.assertEqual(conv.organization, self.org)
        self.assertEqual(conv.contact.display_name, "Ana")
        self.assertEqual(conv.contact.phone_normalized, "5511223344")

    def test_duplicate_delivery_is_deduped(self):
        payload = _meta_payload("111222333", wamid="wamid.DUP")
        body = json.dumps(payload).encode()
        for _ in range(3):
            r = self.client.post(
                "/hooks/whatsapp/", body, content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=_sign(body),
            )
            self.assertEqual(r.status_code, 200)
        self.assertEqual(
            Message.objects.filter(external_message_id="wamid.DUP").count(), 1
        )
        self.assertEqual(Conversation.objects.count(), 1)

    def test_unknown_phone_number_id_acks_without_persisting(self):
        """200 (cortar reintentos de Meta) pero cero escrituras."""
        payload = _meta_payload("999888777")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Message.all_objects.count(), 0)

    def test_routing_by_receiving_number_is_org_exact(self):
        """R1: el mensaje aterriza en la org del NÚMERO receptor, jamás en
        otra — aunque el remitente sea cliente de ambas clínicas."""
        org_b = Organization.objects.create(name="WH Org B", timezone="UTC")
        ChannelAccount.objects.create(
            organization=org_b, external_account_id="444555666",
        )
        payload = _meta_payload("444555666", wamid="wamid.R1")
        body = json.dumps(payload).encode()
        self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        message = Message.objects.get(external_message_id="wamid.R1")
        self.assertEqual(message.organization, org_b)
        self.assertEqual(
            Message.objects.filter(organization=self.org).count(), 0
        )

    def test_status_update_marks_outbound_delivered(self):
        outbound = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta", status=Message.STATUS_SENT,
            external_message_id="wamid.OUT1",
        )
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "111222333"},
                "statuses": [{"id": "wamid.OUT1", "status": "delivered"}],
            }}]}],
        }
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)
        outbound.refresh_from_db()
        self.assertEqual(outbound.status, Message.STATUS_DELIVERED)

    def test_late_sent_ack_does_not_degrade_read(self):
        outbound = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta", status=Message.STATUS_READ,
            external_message_id="wamid.OUT2",
        )
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "111222333"},
                "statuses": [{"id": "wamid.OUT2", "status": "sent"}],
            }}]}],
        }
        body = json.dumps(payload).encode()
        self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        outbound.refresh_from_db()
        self.assertEqual(outbound.status, Message.STATUS_READ)  # forward-only


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY)
class B1ChannelEventTests(TestCase):
    """CHANNEL-01: persisted channel evidence, no binary interpretation."""

    def setUp(self):
        self.org = Organization.objects.create(name='B1 Channel', timezone='UTC')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='b1-channel')

    def _event(self, kind, content=None, *, context_id=None, wamid='b1-event'):
        from apps.channels.events import event_from_message
        payload = _meta_payload(self.channel.external_account_id, wamid=wamid)
        msg = payload['entry'][0]['changes'][0]['value']['messages'][0]
        msg.pop('text')
        msg['type'] = kind
        if content is not None:
            msg[kind] = content
        if context_id is not None:
            msg['context'] = {'id': context_id, 'from': '5215511223344'}
        body = json.dumps(payload).encode()
        response = self.client.post('/hooks/whatsapp/', body, content_type='application/json',
                                    HTTP_X_HUB_SIGNATURE_256=_sign(body))
        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(external_message_id=wamid)
        return message, event_from_message(message)

    def test_original_text_and_context_id_survive_persistence(self):
        from apps.channels.events import EVENT_METADATA_KEY
        message, event = self._event('text', {'body': '  Hola, clínica 👋  '},
                                     context_id='wamid.reference')
        self.assertEqual(message.body, '  Hola, clínica 👋  ')
        self.assertEqual(event.original_text, message.body)
        self.assertIsNone(event.normalized_text)
        self.assertIsNone(event.caption)
        self.assertEqual(event.event_type, 'text')
        self.assertEqual(event.reply_to_id, 'wamid.reference')
        self.assertEqual(event.message_id, message.pk)
        # MED-02 preserves raw transport in DB; B1 projection still has no
        # duplicated body and does not imply binary understanding.
        self.assertEqual(message.raw_metadata['text']['body'], message.body)
        self.assertNotIn(message.body, json.dumps(message.raw_metadata[EVENT_METADATA_KEY], ensure_ascii=False))

    def test_image_and_document_captions_are_body_once_and_media_stays_limited(self):
        from apps.channels.events import EVENT_METADATA_KEY
        from apps.agent.turn_context import build_turn_context
        from apps.agent import prompts
        for kind in ('image', 'document'):
            with self.subTest(kind=kind):
                message, event = self._event(kind, {
                    'caption': 'Texto que acompaña al archivo', 'id': 'media-ref',
                    'mime_type': 'image/jpeg' if kind == 'image' else 'application/pdf',
                }, wamid=f'b1-{kind}')
                self.assertEqual(message.body, 'Texto que acompaña al archivo')
                self.assertEqual(event.caption, message.body)
                self.assertEqual(event.media_reference_id, 'media-ref')
                self.assertEqual(event.event_type, kind)
                self.assertTrue(event.limited_content)
                self.assertFalse(event.binary_understood)
                self.assertFalse(event.uninterpretable)
                self.assertEqual(message.raw_metadata[kind]['caption'], message.body)
                self.assertNotIn(message.body, json.dumps(message.raw_metadata[EVENT_METADATA_KEY], ensure_ascii=False))
                turn = build_turn_context(message.conversation, [message])
                rendered = prompts.assemble_messages(message.conversation, turn_context=turn)
                self.assertEqual(rendered[-2], {'role': 'user', 'content': message.body})
                self.assertIn('no has visto', rendered[-1]['content'])

    def test_audio_image_document_without_text_are_explicitly_uninterpretable(self):
        for kind in ('audio', 'image', 'document'):
            with self.subTest(kind=kind):
                message, event = self._event(kind, {'id': 'binary-ref'}, wamid=f'b1-empty-{kind}')
                self.assertEqual(message.body, '')
                self.assertIsNone(event.caption)
                self.assertEqual(event.media_reference_id, 'binary-ref')
                self.assertTrue(event.uninterpretable)
                self.assertFalse(event.binary_understood)

    def test_button_and_list_keep_distinct_ids_kinds_and_visible_titles(self):
        for kind in ('button_reply', 'list_reply'):
            with self.subTest(kind=kind):
                _, event = self._event('interactive', {
                    'type': kind, kind: {'id': f'action-{kind}', 'title': 'Ver horarios'},
                }, context_id='wamid.menu', wamid=f'b1-{kind}')
                self.assertEqual(event.event_type, 'interactive')
                self.assertEqual(event.interaction_type, kind)
                self.assertEqual(event.action_id, f'action-{kind}')
                self.assertEqual(event.action_title, 'Ver horarios')
                self.assertNotEqual(event.action_id, event.action_title)
                self.assertEqual(event.reply_to_id, 'wamid.menu')

    def test_interactive_without_id_does_not_synthesize_it_from_title(self):
        _, event = self._event('interactive', {'button_reply': {'title': 'confirmar'}})
        self.assertEqual(event.action_title, 'confirmar')
        self.assertIsNone(event.action_id)

    def test_template_button_keeps_payload_separate_from_title(self):
        _, event = self._event('button', {'text': 'Continuar', 'payload': 'action-real'})
        self.assertEqual(event.action_id, 'action-real')
        self.assertEqual(event.action_title, 'Continuar')
        self.assertEqual(event.event_type, 'button')

    def test_legacy_metadata_is_diagnostic_not_runtime_evidence(self):
        from apps.agent.services import ingest_inbound_message
        from apps.channels.events import event_from_message
        message = ingest_inbound_message(
            self.channel, wamid='legacy', wa_id='5215511223344', body='Confirmar',
            payload_type='button_reply', raw={'context': {'id': 'untrusted-raw'},
                                             'interactive': {'button_reply': {'id': 'raw-id'}}})
        event = event_from_message(message)
        self.assertEqual(event.text, 'Confirmar')
        for value in (event.action_id, event.reply_to_id, event.caption,
                      event.action_title, event.event_type, event.media_reference_id):
            self.assertIsNone(value)

    def test_malformed_or_future_projection_is_unknown(self):
        from copy import deepcopy
        from apps.channels.events import EVENT_METADATA_KEY, event_from_message
        message, _ = self._event('interactive', {
            'type': 'button_reply', 'button_reply': {'id': 'real-id', 'title': 'Confirmar'}})
        valid = message.raw_metadata[EVENT_METADATA_KEY]
        invalid = [None, [], {'version': 1}, dict(valid, version=2),
                   dict(valid, version=True), dict(valid, action_id={'id': 'nested'}),
                   dict(valid, event_type='image'), dict(valid, caption='duplicated-body')]
        for projection in invalid:
            with self.subTest(projection=projection):
                message.raw_metadata = {EVENT_METADATA_KEY: deepcopy(projection)}
                event = event_from_message(message)
                self.assertEqual(event.text, 'Confirmar')
                self.assertIsNone(event.action_id)
                self.assertIsNone(event.event_type)

    def test_malformed_provider_objects_do_not_become_text_or_ids(self):
        message, event = self._event('image', {'caption': {'injected': 'text'}, 'id': ['fake']})
        self.assertEqual(message.body, '')
        self.assertIsNone(event.caption)
        self.assertIsNone(event.media_reference_id)
        self.assertTrue(event.uninterpretable)

    def _reference(self, message, *, status=Message.STATUS_SENT, **overrides):
        values = dict(
            organization=self.org, channel_account=self.channel,
            contact=message.conversation.contact, conversation=message.conversation,
            direction=Message.DIRECTION_OUT, author_type=Message.AUTHOR_SYSTEM,
            body='mensaje referenciado', external_message_id='b1-reference', status=status)
        values.update(overrides)
        return Message.objects.create(**values)

    def test_exact_emitted_reference_is_available_without_granting_authority(self):
        from apps.agent import planner
        from apps.agent.models import AgentSettings, TurnOperationAssessment
        from apps.agent.turn_context import build_turn_context
        from apps.channels.selectors import referenced_message
        initial, _ = self._event('text', {'body': 'hola'}, wamid='initial')
        reference = self._reference(initial)
        current, event = self._event('interactive', {
            'type': 'button_reply', 'button_reply': {'id': 'yes', 'title': 'Sí'}},
            context_id=reference.external_message_id)
        turn = build_turn_context(current.conversation, [current])
        self.assertEqual(referenced_message(current.conversation, turn_context=turn, event=event),
                         reference)
        self.assertFalse(current.conversation.flow.get('pending_action'))
        self.assertFalse(current.conversation.goals.exists())
        settings = create_enabled_agent_settings(self.org)
        result = planner.handle_inbound(current.conversation, agent_settings=settings,
                                        turn_context=turn)
        self.assertEqual(result['reason'], 'orphan_affirmative')
        self.assertFalse(TurnOperationAssessment.objects.filter(conversation=current.conversation).exists())
        self.assertFalse(current.conversation.goals.exists())

    def test_referenced_inbound_is_preserved(self):
        from apps.agent.turn_context import build_turn_context
        from apps.channels.selectors import referenced_message
        reference, _ = self._event('text', {'body': 'anterior'}, wamid='prior-inbound')
        current, event = self._event('text', {'body': 'aclaración'}, context_id='prior-inbound')
        turn = build_turn_context(current.conversation, [current])
        self.assertEqual(referenced_message(current.conversation, turn_context=turn, event=event),
                         reference)

    def test_foreign_organization_account_and_contact_cannot_resolve_reference(self):
        from apps.agent.models import ContactIdentity
        from apps.agent.turn_context import build_turn_context
        from apps.channels.selectors import referenced_message
        initial, _ = self._event('text', {'body': 'hola'}, wamid='initial')
        other_org = Organization.objects.create(name='Foreign B1', timezone='UTC')
        other_contact = ContactIdentity.objects.create(organization=self.org, external_id='other-person')
        for label, org, contact in [('organization', other_org, None),
                                    ('account', self.org, initial.conversation.contact),
                                    ('contact', self.org, other_contact)]:
            with self.subTest(label=label):
                channel = ChannelAccount.objects.create(
                    organization=org, external_account_id=f'b1-foreign-{label}')
                if contact is None:
                    contact = ContactIdentity.objects.create(organization=org, external_id='foreign-person')
                if label == 'contact':
                    channel = self.channel
                conv = Conversation.objects.create(organization=org, channel_account=channel, contact=contact)
                self._reference(initial, organization=org, channel_account=channel, contact=contact,
                                conversation=conv, external_message_id=f'ref-{label}')
                current, event = self._event('text', {'body': 'respuesta'}, context_id=f'ref-{label}',
                                             wamid=f'current-{label}')
                turn = build_turn_context(current.conversation, [current])
                self.assertIsNone(referenced_message(current.conversation, turn_context=turn, event=event))

    def test_unemitted_or_later_reference_is_not_resolved(self):
        from apps.agent.turn_context import build_turn_context
        from apps.channels.selectors import referenced_message
        initial, _ = self._event('text', {'body': 'hola'}, wamid='initial')
        reference = self._reference(initial, status=Message.STATUS_PENDING)
        current, event = self._event('text', {'body': 'respuesta'}, context_id='b1-reference')
        turn = build_turn_context(current.conversation, [current])
        self.assertIsNone(referenced_message(current.conversation, turn_context=turn, event=event))
        Message.objects.filter(pk=reference.pk).update(status=Message.STATUS_SENT,
                                                       created_at=current.created_at)
        # Equal timestamp with lower id IS before; a later time is not.
        from datetime import timedelta
        Message.objects.filter(pk=reference.pk).update(created_at=current.created_at + timedelta(seconds=1))
        self.assertIsNone(referenced_message(current.conversation, turn_context=turn, event=event))

    def test_critical_caption_reaches_existing_safety_from_the_same_context(self):
        from unittest.mock import patch
        from apps.agent import planner, safety
        from apps.agent.models import AgentSettings, HumanHandoff
        settings = create_enabled_agent_settings(self.org)
        message, _ = self._event('image', {'id': 'media-only-reference', 'caption': 'mi perro convulsiona'})
        with (patch.object(safety, 'assess_context', wraps=safety.assess_context) as assessment,
              patch.object(planner, '_run_planner') as llm):
            result = planner.handle_inbound(message.conversation, agent_settings=settings,
                                            burst_messages=[message])
        self.assertEqual(result['decision'], 'escalate')
        assessment.assert_called_once()
        assessed_conversation, context = assessment.call_args.args
        self.assertEqual(assessed_conversation.pk, message.conversation_id)
        self.assertEqual(context.inbound_ids, (message.pk,))
        self.assertEqual(context.latest_text, 'mi perro convulsiona')
        llm.assert_not_called()
        self.assertEqual(HumanHandoff.objects.get(conversation=message.conversation).reason_code,
                         HumanHandoff.REASON_EMERGENCY)

    def test_media_without_caption_cannot_use_old_pending_or_llm_to_invent_understanding(self):
        from unittest.mock import patch
        from apps.agent import planner
        from apps.agent.models import AgentSettings
        settings = create_enabled_agent_settings(self.org)
        message, _ = self._event('audio', {'id': 'audio-reference'})
        conversation = message.conversation
        conversation.flow['pending_action'] = {
            'tool': 'create_appointment', 'args': {'pet_id': 'old-pet'},
            'created_at': message.created_at.isoformat(),
        }
        conversation.save(update_fields=['flow'])
        old_flow = dict(conversation.flow)
        with (patch.object(planner, '_run_planner') as llm,
              patch.object(planner, '_commit_pending') as commit):
            result = planner.handle_inbound(conversation, agent_settings=settings,
                                            burst_messages=[message])
        self.assertEqual(result['decision'], 'reply')
        self.assertEqual(result['reason'], 'unreadable_media')
        llm.assert_not_called()
        commit.assert_not_called()
        conversation.refresh_from_db()
        self.assertEqual(conversation.flow, old_flow)
        outbound = Message.objects.get(conversation=message.conversation, direction=Message.DIRECTION_OUT)
        self.assertIn('No puedo interpretar', outbound.body)
        self.assertIn('texto', outbound.body)
        self.assertIn('persona', outbound.body)
