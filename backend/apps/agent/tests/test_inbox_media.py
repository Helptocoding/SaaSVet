"""MED-04/05 proxy/DTO/deltas and RPL-07 native context after B4 admission."""
from datetime import timedelta
import json
from unittest.mock import Mock, patch
from uuid import uuid4

import requests
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.agent import sender
from apps.agent.serializers import MessageSerializer
from apps.agent.tests.test_b4_sender import SenderFixture
from apps.channels.media_storage import InboxMediaStorage
from apps.channels.models import Message, MessageMedia
from apps.channels.providers import MetaWhatsAppProvider
from apps.channels.tests.test_media_pipeline import MediaFixtures
from apps.organizations.models import Organization
from apps.users.models import User


class InboxMediaTests(MediaFixtures, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.actor)

    def get_media(self, row, **kwargs):
        return self.client.get(f'/api/inbox/media/{row.public_id}/', **kwargs)

    def test_authenticated_stream_has_private_headers_and_stored_mime(self):
        row = self.ready(filename='../report\r\n.png')
        response = self.get_media(row, HTTP_CONTENT_TYPE='text/html')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', response['Content-Security-Policy'])
        self.assertIn('Authorization', response['Vary'])
        self.assertIn('inline', response['Content-Disposition'])
        self.assertNotIn('../', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), b'synthetic-private-media')

    def test_document_uses_attachment_and_sanitized_name(self):
        row = self.ready(mime_type='text/plain', filename='C:\\temp\\notes.txt')
        response = self.get_media(row)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('notes.txt', response['Content-Disposition'])
        list(response.streaming_content)  # TestClient closes with its signal guard.

    def test_cross_org_unknown_and_corrupt_scope_return_identical_404_without_io(self):
        row = self.ready()
        foreign = Organization.objects.create(name='Otra clínica sintética')
        outsider = User.objects.create(username='media-outsider', organization=foreign, role='ADMIN')
        self.client.force_authenticate(outsider)
        with patch.object(InboxMediaStorage, 'open') as opened:
            response = self.get_media(row)
            unknown = self.client.get(f'/api/inbox/media/{uuid4()}/')
            self.assertEqual((response.status_code, unknown.status_code), (404, 404))
            self.assertEqual(response.data, unknown.data)
            opened.assert_not_called()
        self.client.force_authenticate(self.actor)
        Message.all_objects.filter(pk=row.message_id).update(organization=foreign)
        with patch.object(InboxMediaStorage, 'open') as opened:
            self.assertEqual(self.get_media(row).status_code, 404)
            opened.assert_not_called()

    def test_permission_is_required_before_storage_access(self):
        row = self.ready()
        self.client.force_authenticate(self.user('media-no-view', ()))
        with patch.object(InboxMediaStorage, 'open') as opened:
            self.assertEqual(self.get_media(row).status_code, 403)
            opened.assert_not_called()
        self.client.force_authenticate(None)
        self.assertIn(self.get_media(row).status_code, (401, 403))

    def test_deadline_is_410_even_before_purge_and_not_a_storage_read(self):
        row = self.ready()
        MessageMedia.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with patch.object(InboxMediaStorage, 'open') as opened:
            response = self.get_media(row)
            self.assertEqual(response.status_code, 410)
            self.assertEqual(response.data['code'], 'media_expired')
            opened.assert_not_called()

    def test_pending_and_failed_are_explicit_without_io(self):
        row = self.media()
        for status in ('pending', 'failed'):
            MessageMedia.objects.filter(pk=row.pk).update(status=status)
            with patch.object(InboxMediaStorage, 'open') as opened:
                self.assertEqual(self.get_media(row).status_code, 409)
                opened.assert_not_called()

    def test_missing_object_logs_error_without_filename_or_provider_id(self):
        row = self.ready(filename='private-name.png')
        row.file.storage.delete(row.file.name)
        with self.assertLogs('agent.events', level='ERROR') as logs:
            response = self.get_media(row)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(row.filename, repr(logs.output))
        self.assertNotIn(row.provider_media_id, repr(logs.output))

    def test_storage_outage_is_generic_503(self):
        row = self.ready()
        with patch.object(InboxMediaStorage, 'open', side_effect=OSError('secret signed URL')):
            response = self.get_media(row)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', json.dumps(response.data))

    def test_dto_is_bounded_and_never_exposes_provider_or_storage_details(self):
        row = self.ready()
        data = MessageSerializer(Message.objects.select_related('media', 'conversation', 'human_author',
            'reply_to__human_author').get(pk=row.message_id)).data['media']
        self.assertEqual(set(data), {'public_id', 'status', 'mime_type', 'file_size', 'filename',
            'error', 'expires_at', 'duration_ms', 'width', 'height'})
        self.assertNotIn(row.provider_media_id, json.dumps(data))
        self.assertNotIn(row.file.name, json.dumps(data))
        self.assertEqual(data['status'], 'ready')

    def test_media_change_updates_delta_without_touching_parent(self):
        row = self.media()
        original = row.message.updated_at
        full = self.read()
        MessageMedia.objects.filter(pk=row.pk).update(status='failed', error='provider_http_404')
        delta = self.read(since=full['sync_cursor'])
        changed = next(item for item in delta['messages'] if item['id'] == row.message_id)
        self.assertEqual(changed['media']['status'], 'failed')
        self.assertEqual(changed['media']['error'], 'media_unavailable')
        row.message.refresh_from_db()
        self.assertEqual(row.message.updated_at, original)
        stable = self.read(since=delta['sync_cursor'])
        self.assertEqual(stable['messages'], [])

    def test_deadline_updates_delta_without_media_or_parent_write(self):
        row = self.ready()
        full = self.read()
        MessageMedia.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        delta = self.read(since=full['sync_cursor'])
        self.assertEqual(next(item for item in delta['messages'] if item['id'] == row.message_id)['media']['status'], 'expired')

    def test_transcript_query_count_is_constant_with_many_files(self):
        self.read()
        with CaptureQueriesContext(connection) as small:
            self.read()
        for _ in range(15):
            self.media()
        with CaptureQueriesContext(connection) as large:
            self.read()
        self.assertEqual(len(small), len(large))

    def test_thread_list_adds_type_and_filename_with_caption_preserved(self):
        self.media(message=self.message(payload_type='document', body=''), filename='study.pdf', mime_type='application/pdf')
        response = self.client.get('/api/inbox/threads/')
        self.assertEqual(response.status_code, 200)
        data = response.data
        rows = data.get('results', data.get('threads', [])) if isinstance(data, dict) else data
        self.assertEqual(rows[0]['last_message_type'], 'document')
        self.assertEqual(rows[0]['last_message_filename'], 'study.pdf')


class NativeReplyTests(SenderFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.target = Message.objects.create(organization=self.org, channel_account=self.channel,
            contact=self.contact, conversation=self.conv, direction='in', author_type='client',
            status='processed', external_message_id='wamid.original', body='Original')
        self.message.reply_to = self.target
        self.message.save(update_fields=['reply_to'])

    def dispatch(self, *, payload=None, status=200, exception=None):
        claim = self.claim()
        response = Mock(status_code=status)
        response.json.return_value = payload if payload is not None else {'messages': [{'id': 'wamid.reply'}]}
        def post(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.message.refresh_from_db()
            self.assertIsNotNone(self.message.send_admitted_at)
            if exception:
                raise exception
            return response
        with patch.object(MetaWhatsAppProvider, '_access_token', return_value='synthetic-token'), \
                patch('apps.channels.providers.requests.post', side_effect=post) as http:
            sender.dispatch_claim(claim)
            self.assertFalse(sender.dispatch_claim(claim))
        self.assertEqual(http.call_count, 1)
        self.message.refresh_from_db()
        return http.call_args.kwargs['json']

    def test_context_native_after_admission_once(self):
        payload = self.dispatch()
        self.assertEqual(payload['context'], {'message_id': 'wamid.original'})
        self.assertEqual(self.message.status, 'sent')

    def test_unquoted_send_keeps_original_provider_contract(self):
        Message.objects.filter(pk=self.message.pk).update(reply_to=None)
        self.assertNotIn('context', self.dispatch())

    def test_absent_or_invalid_external_evidence_preserves_internal_quote(self):
        for identity in (None, '', 'invalid id'):
            Message.objects.filter(pk=self.target.pk).update(external_message_id=identity)
            # The helper must not coerce/guess any ID.
            from apps.channels.replies import outbound_provider_reply_id
            self.assertIsNone(outbound_provider_reply_id(self.message))
        self.assertNotIn('context', self.dispatch())
        self.assertEqual(self.message.reply_to_id, self.target.pk)

    def test_failed_discarded_pending_uncertain_outbound_targets_omit_context(self):
        from apps.channels.replies import outbound_provider_reply_id
        for status in ('failed', 'discarded', 'pending'):
            Message.objects.filter(pk=self.target.pk).update(direction='out', author_type='system', status=status)
            self.assertIsNone(outbound_provider_reply_id(self.message))
        self.assertNotIn('context', self.dispatch())

    def test_cross_contact_reference_corruption_never_reaches_meta(self):
        from apps.agent.models import ContactIdentity
        other = ContactIdentity.objects.create(organization=self.org, external_id='different-contact')
        Message.objects.filter(pk=self.target.pk).update(contact=other)
        from apps.channels.replies import outbound_provider_reply_id
        self.assertIsNone(outbound_provider_reply_id(self.message))
        with patch('apps.channels.providers.requests.post') as post:
            with self.assertRaises(ValidationError):
                self.claim()
            post.assert_not_called()

    def test_http_timeout_stays_uncertain_without_automatic_resend(self):
        self.dispatch(exception=requests.Timeout())
        self.assertEqual(self.message.status, 'uncertain')
        self.assertIsNone(self.message.next_attempt_at)

    def test_explicit_provider_rejection_remains_failed(self):
        payload = self.dispatch(status=400, payload={'error': {'code': 100}})
        self.assertEqual(payload['context']['message_id'], 'wamid.original')
        self.assertEqual(self.message.status, 'failed')

    def test_media_target_with_valid_external_id_keeps_native_context(self):
        Message.objects.filter(pk=self.target.pk).update(payload_type='image', body='')
        self.assertEqual(self.dispatch()['context']['message_id'], 'wamid.original')

    def test_takeover_before_admission_prevents_even_native_http(self):
        claim = self.claim()
        self.takeover()
        with patch('apps.channels.providers.requests.post') as post:
            self.assertFalse(sender.dispatch_claim(claim))
            post.assert_not_called()
