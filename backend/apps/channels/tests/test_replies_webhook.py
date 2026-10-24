"""WA-RPL-02: signed webhook -> durable citation, isolated scope and dedup."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import threading
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from apps.agent import services
from apps.agent.models import ContactIdentity, Conversation
from apps.channels.events import event_from_message
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization

SECRET = 'synthetic-reply-webhook-secret'
WA_ID = '5215511223344'


class ReplyWebhookFixtures:
    @classmethod
    def build(cls):
        cls.org = Organization.objects.create(name='Webhook replies sintético')
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='reply-webhook-main')
        cls.contact = services.resolve_contact_identity(cls.account, WA_ID)
        cls.convo = services.get_or_create_open_conversation(cls.contact, cls.account)
        cls.target = cls.make_target()

    @classmethod
    def make_target(cls, **overrides):
        fields = dict(organization=cls.org, channel_account=cls.account, contact=cls.contact,
            conversation=cls.convo, direction='out', author_type='system', status='sent',
            body='Contenido privado sintético del destino', external_message_id='reply-reference')
        fields.update(overrides)
        return Message.objects.create(**fields)

    def payload(self, reference='reply-reference', wamid='reply-inbound'):
        message = {'id': wamid, 'from': WA_ID, 'timestamp': '1752600000', 'type': 'text',
            'text': {'body': 'Respuesta sintética privada'}, 'context': {'id': reference}}
        return {'entry': [{'changes': [{'value': {'metadata': {'phone_number_id': self.account.external_account_id},
            'messages': [message]}}]}]}

    def post(self, payload, client=None, signature=True):
        body = json.dumps(payload).encode()
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest() if signature else '0'*64
        response = (client or self.client).post('/hooks/whatsapp/', body, content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256='sha256='+digest)
        self.assertEqual(response.status_code, 200 if signature else 403)
        return response

    @staticmethod
    def unresolved(log):
        return [call for call in log.call_args_list if call.args == ('INBOUND_REPLY_UNRESOLVED',)]

    def inbound(self, wamid='reply-inbound'):
        return Message.objects.for_organization(self.org).get(external_message_id=wamid, direction='in')


@override_settings(WHATSAPP_APP_SECRET=SECRET)
class ReplyWebhookTests(ReplyWebhookFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def test_signed_inbound_persists_outbound_citation_and_original_event_id(self):
        self.post(self.payload())
        message = self.inbound()
        self.assertEqual(message.reply_to_id, self.target.pk)
        self.assertEqual(event_from_message(message).reply_to_id, 'reply-reference')
        self.assertEqual(message.body, 'Respuesta sintética privada')

    def test_reference_to_an_inbound_is_also_valid(self):
        target = self.make_target(direction='in', author_type='client', status='processed', external_message_id='prior-in')
        self.post(self.payload('prior-in'))
        self.assertEqual(self.inbound().reply_to_id, target.pk)

    def test_reference_across_episodes_of_same_thread(self):
        old = Conversation.objects.create(organization=self.org, channel_account=self.account,
            contact=self.contact, state='closed')
        self.target.conversation = old
        self.target.save(update_fields=['conversation'])
        self.post(self.payload())
        self.assertEqual(self.inbound().reply_to_id, self.target.pk)
        self.assertEqual(self.inbound().conversation_id, self.convo.pk)

    def test_discarded_failed_and_unemitted_targets_are_citations(self):
        for status in ('discarded', 'failed', 'pending'):
            with self.subTest(status=status):
                target = self.make_target(status=status, external_message_id=f'target-{status}')
                self.post(self.payload(f'target-{status}', wamid=f'in-{status}'))
                self.assertEqual(self.inbound(f'in-{status}').reply_to_id, target.pk)

    def test_media_reference_needs_no_binary_pipeline(self):
        for kind in ('image', 'audio', 'document'):
            with self.subTest(kind=kind):
                target = self.make_target(payload_type=kind, body='', external_message_id=f'target-{kind}')
                self.post(self.payload(f'target-{kind}', wamid=f'in-{kind}'))
                self.assertEqual(self.inbound(f'in-{kind}').reply_to_id, target.pk)

    def test_hidden_historical_target_can_be_cited(self):
        self.target.is_active = False
        self.target.save(update_fields=['is_active'])
        self.post(self.payload())
        self.assertEqual(self.inbound().reply_to_id, self.target.pk)

    def test_unknown_target_warns_without_pii_and_keeps_inbound(self):
        reference = 'private-reference-that-must-not-be-logged'
        with patch('apps.channels.views.logger.warning') as log:
            self.post(self.payload(reference))
        message = self.inbound()
        self.assertIsNone(message.reply_to_id)
        calls = self.unresolved(log)
        self.assertEqual(len(calls), 1)
        extra = calls[0].kwargs['extra']
        self.assertEqual(set(extra), {'event', 'organization_public_id', 'channel_account_public_id', 'message_id', 'reason'})
        self.assertEqual(extra['message_id'], message.pk)
        self.assertNotIn(message.body, repr(extra))
        self.assertNotIn(self.target.body, repr(extra))
        self.assertNotIn(reference, repr(extra))
        self.assertNotIn(WA_ID, repr(extra))

    def test_other_account_never_resolves_target(self):
        account = ChannelAccount.objects.create(organization=self.org, external_account_id='reply-second')
        target = self.make_target(channel_account=account, conversation=None, external_message_id='other-account')
        self.post(self.payload(target.external_message_id))
        self.assertIsNone(self.inbound().reply_to_id)

    def test_foreign_organization_never_resolves_target(self):
        foreign = Organization.objects.create(name='Foreign reply clinic')
        account = ChannelAccount.objects.create(organization=foreign, external_account_id='reply-foreign')
        contact = ContactIdentity.objects.create(organization=foreign, external_id='foreign-person')
        target = self.make_target(organization=foreign, channel_account=account, contact=contact,
            conversation=None, external_message_id='foreign-reference')
        self.post(self.payload(target.external_message_id))
        self.assertIsNone(self.inbound().reply_to_id)

    def test_other_contact_in_same_account_keeps_inbound_without_citation(self):
        contact = ContactIdentity.objects.create(organization=self.org, external_id='other-reply-person')
        target = self.make_target(contact=contact, conversation=None, external_message_id='other-contact')
        with patch('apps.channels.views.logger.warning') as log:
            self.post(self.payload(target.external_message_id))
        self.assertIsNone(self.inbound().reply_to_id)
        self.assertEqual(self.inbound().body, 'Respuesta sintética privada')
        self.assertEqual(len(self.unresolved(log)), 1)

    def test_duplicate_preserves_first_citation_and_has_no_second_effect(self):
        with patch.object(services.claim_trace, 'persisted', wraps=services.claim_trace.persisted) as persisted:
            self.post(self.payload())
            first = self.inbound()
            original = (first.pk, first.updated_at, first.available_at, first.raw_metadata)
            self.post(self.payload('different-reference'))
            current = self.inbound()
            self.assertEqual((current.pk, current.updated_at, current.available_at, current.raw_metadata), original)
            self.assertEqual(current.reply_to_id, self.target.pk)
            persisted.assert_called_once()

    def test_unknown_target_redelivery_does_not_backfill_or_repeat_warning(self):
        with patch('apps.channels.views.logger.warning') as log:
            self.post(self.payload('arrived-later'))
            self.make_target(external_message_id='arrived-later')
            self.post(self.payload('arrived-later'))
        self.assertIsNone(self.inbound().reply_to_id)
        self.assertEqual(len(self.unresolved(log)), 1)

    def test_ambiguous_provider_id_is_not_guessed(self):
        self.make_target(external_message_id=self.target.external_message_id)
        with patch('apps.channels.views.logger.warning') as log:
            self.post(self.payload())
        self.assertIsNone(self.inbound().reply_to_id)
        self.assertEqual(len(self.unresolved(log)), 1)

    def test_malformed_or_absent_context_is_not_coerced_to_a_reference(self):
        for index, context in enumerate((None, [], {}, {'id': []}, {'id': {}}, {'id': 1}, {'id': ''})):
            with self.subTest(context=context):
                payload = self.payload(wamid=f'malformed-{index}')
                payload['entry'][0]['changes'][0]['value']['messages'][0]['context'] = context
                self.post(payload)
                self.assertIsNone(self.inbound(f'malformed-{index}').reply_to_id)
                self.assertIsNone(event_from_message(self.inbound(f'malformed-{index}')).reply_to_id)

    def test_oversized_reference_does_not_truncate_into_a_valid_target(self):
        self.post(self.payload('reply-reference'+'x'*200))
        self.assertIsNone(self.inbound().reply_to_id)

    def test_service_optional_reply_argument_accepts_same_thread_target(self):
        message = services.ingest_inbound_message(self.account, wamid='direct-reply', wa_id=WA_ID,
            body='Directa sintética', reply_to=self.target)
        self.assertIsNotNone(message)
        self.assertEqual(message.reply_to_id, self.target.pk)

    def test_service_revalidates_current_target_scope(self):
        contact = ContactIdentity.objects.create(organization=self.org, external_id='changed-person')
        Message.all_objects.filter(pk=self.target.pk).update(contact=contact)
        message = services.ingest_inbound_message(self.account, wamid='stale-target', wa_id=WA_ID,
            body='Directa conservada', reply_to=self.target)
        self.assertIsNotNone(message)
        self.assertIsNone(message.reply_to_id)

    def test_target_removed_between_lookup_and_ingest_does_not_drop_inbound(self):
        real_ingest = services.ingest_inbound_message
        def remove_then_ingest(*args, **kwargs):
            Message.objects.get(pk=self.target.pk).delete()
            return real_ingest(*args, **kwargs)
        with patch.object(services, 'ingest_inbound_message', side_effect=remove_then_ingest):
            self.post(self.payload())
        self.assertIsNone(self.inbound().reply_to_id)

    def test_invalid_signature_cannot_even_resolve_citation(self):
        with patch('apps.channels.replies.provider_reply_target') as lookup:
            self.post(self.payload(), signature=False)
        lookup.assert_not_called()
        self.assertFalse(Message.objects.filter(direction='in', external_message_id='reply-inbound').exists())

    def test_second_message_in_batch_can_cite_first_inbound(self):
        payload = self.payload(wamid='batch-source')
        source = payload['entry'][0]['changes'][0]['value']['messages'][0]
        source.pop('context')
        cited = dict(source, id='batch-reply', context={'id': 'batch-source'})
        payload['entry'][0]['changes'][0]['value']['messages'].append(cited)
        self.post(payload)
        self.assertEqual(self.inbound('batch-reply').reply_to_id, self.inbound('batch-source').pk)


@override_settings(WHATSAPP_APP_SECRET=SECRET)
class ReplyWebhookRaceTests(ReplyWebhookFixtures, TransactionTestCase):
    def setUp(self):
        self.build()

    def test_two_concurrent_deliveries_persist_citation_once(self):
        barrier = threading.Barrier(2, timeout=10)
        real_resolve = services.resolve_contact_identity
        def after_precheck(*args, **kwargs):
            result = real_resolve(*args, **kwargs)
            barrier.wait()
            return result
        payload = self.payload()
        def request():
            close_old_connections()
            try:
                return self.post(payload, client=Client()).status_code
            finally:
                connection.close()
        with (patch.object(services, 'resolve_contact_identity', side_effect=after_precheck),
              patch.object(services.claim_trace, 'persisted', wraps=services.claim_trace.persisted) as persisted):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request) for _ in range(2)]
                self.assertEqual([future.result(timeout=20) for future in futures], [200, 200])
            persisted.assert_called_once()
        self.assertEqual(Message.objects.filter(direction='in', external_message_id='reply-inbound').count(), 1)
        self.assertEqual(self.inbound().reply_to_id, self.target.pk)
