"""MED-01..03: synthetic provider/storage, real PostgreSQL state transitions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import requests
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.agent.tests.test_inbox_replies import ReplyApiFixtures
from apps.channels import media_worker as worker
from apps.channels.media_ingest import persist_inbound_media
from apps.channels.media_policy import MAX_BYTES, extract_media_metadata
from apps.channels.media_storage import B2MediaStorage, InboxMediaStorage, media_upload_path
from apps.channels.media_transfer import MediaDownloadError, downloaded_media, scavenge_media_spools, spool_root
from apps.channels.models import ChannelAccount, MessageMedia
from apps.channels.tests.test_replies_webhook import ReplyWebhookFixtures, SECRET

DATA = b'synthetic-private-media'
SHA = hashlib.sha256(DATA).hexdigest()


class MediaFixtures(ReplyApiFixtures):
    def media(self, **values):
        message = values.pop('message', None) or self.message(payload_type='image', body='Caption preservada')
        fields = dict(organization=self.org, channel_account=self.account, message=message,
            provider_media_id=uuid4().hex, mime_type='image/png', expected_sha256=SHA)
        fields.update(values)
        return MessageMedia.objects.create(**fields)

    def ready(self, **values):
        row = self.media(**values)
        row.file.save('ignored.png', ContentFile(DATA), save=False)
        now = timezone.now()
        row.status, row.file_size, row.sha256 = 'ready', len(DATA), SHA
        row.persisted_at, row.expires_at = now, now + worker.RETENTION
        row.save()
        self.addCleanup(row.file.storage.delete, row.file.name)
        return row


class MediaModelTests(MediaFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def test_provider_id_is_unique_per_account_not_globally(self):
        first = self.media(provider_media_id='shared')
        second = self.media(provider_media_id='different')
        with self.assertRaises(IntegrityError), transaction.atomic():
            MessageMedia.objects.filter(pk=second.pk).update(provider_media_id='shared')
        account = ChannelAccount.objects.create(organization=self.org, external_account_id='media-other')
        message = self.message(channel_account=account, conversation=None)
        other = self.media(channel_account=account, message=message, provider_media_id='shared')
        self.assertNotEqual(first.pk, other.pk)

    def test_model_rejects_outbound_and_cross_clinic(self):
        row = self.media()
        row.message = self.message(direction='out', author_type='system')
        with self.assertRaises(ValidationError):
            row.clean()
        row.message = self.target
        row.organization_id += 1000
        with self.assertRaises(ValidationError):
            row.clean()

    def test_ready_and_downloading_require_durable_evidence(self):
        row = self.media()
        for state in ('ready', 'downloading', 'expired'):
            with self.subTest(state=state), self.assertRaises(IntegrityError), transaction.atomic():
                MessageMedia.objects.filter(pk=row.pk).update(status=state)

    def test_duplicate_reference_reuses_row_without_reparenting(self):
        row = self.media(provider_media_id='same')
        other = self.message(payload_type='image')
        result = persist_inbound_media(other, dict(provider_media_id='same', mime_type='image/png'))
        self.assertEqual(result.pk, row.pk)
        row.refresh_from_db()
        self.assertNotEqual(row.message_id, other.pk)

    def test_bad_dimensions_do_not_poison_message_ingest(self):
        metadata = extract_media_metadata({'type': 'image', 'image': {'id': 'safe', 'width': 2**63,
            'height': True, 'duration_ms': -1, 'filename': '../name\r\n.png'}})
        self.assertIsNone(metadata['width'])
        self.assertIsNone(metadata['height'])
        self.assertEqual(metadata['filename'], 'name.png')
        self.assertIsNotNone(persist_inbound_media(self.message(), metadata))


@override_settings(WHATSAPP_APP_SECRET=SECRET)
class MediaWebhookTests(ReplyWebhookFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def media_payload(self, kind, identity='in-media', malformed=False):
        payload = self.payload(wamid=identity)
        msg = payload['entry'][0]['changes'][0]['value']['messages'][0]
        msg.update(type=kind)
        msg.pop('text')
        msg[kind] = dict(mime_type={'image': 'image/png', 'audio': 'audio/ogg', 'video': 'video/mp4',
            'document': 'application/pdf', 'sticker': 'image/webp'}[kind], filename='../report.pdf',
            sha256=SHA, caption='Caption sintética', width=2**63)
        if not malformed:
            msg[kind]['id'] = 'provider-' + identity
        return payload

    def test_all_five_kinds_capture_metadata_raw_and_caption_without_http(self):
        with patch('requests.get') as get, patch('requests.post') as post:
            for kind in ('image', 'audio', 'video', 'document', 'sticker'):
                with self.subTest(kind=kind):
                    payload = self.media_payload(kind, identity='in-' + kind)
                    self.post(payload)
                    message = self.inbound('in-' + kind)
                    self.assertEqual(message.payload_type, kind)
                    self.assertEqual(message.media.status, 'pending')
                    self.assertEqual(message.media.provider_media_id, 'provider-in-' + kind)
                    self.assertEqual(message.raw_metadata[kind]['sha256'], SHA)
                    if kind in ('image', 'video', 'document'):
                        self.assertEqual(message.body, 'Caption sintética')
            get.assert_not_called()
            post.assert_not_called()

    def test_duplicate_webhook_does_not_create_another_media(self):
        payload = self.media_payload('image')
        self.post(payload)
        first = self.inbound('in-media').media.pk
        self.post(payload)
        self.assertEqual(MessageMedia.objects.count(), 1)
        self.assertEqual(self.inbound('in-media').media.pk, first)

    def test_malformed_reference_preserves_caption_and_message(self):
        self.post(self.media_payload('document', malformed=True))
        message = self.inbound('in-media')
        self.assertEqual((message.payload_type, message.body), ('document', 'Caption sintética'))
        self.assertFalse(MessageMedia.objects.filter(message=message).exists())


class MediaTransferTests(SimpleTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'saaslyvet-inbox-media-spool'
        self.config = override_settings(INBOX_MEDIA_SPOOL_ROOT=str(self.root))
        self.config.enable()
        self.addCleanup(self.config.disable)
        self.media = SimpleNamespace(provider_media_id='12345', mime_type='image/png', expected_sha256=SHA,
            message=SimpleNamespace(payload_type='image'), channel_account=SimpleNamespace(external_account_id='phone'))
        self.token = patch('apps.channels.providers.MetaWhatsAppProvider._access_token', return_value='synthetic-token')
        self.token.start()
        self.addCleanup(self.token.stop)

    def responses(self, metadata=None, data=DATA, binary_status=200):
        info = dict(url='https://lookaside.fbsbx.com/private', mime_type=self.media.mime_type,
            file_size=len(data), sha256=hashlib.sha256(data).hexdigest())
        info.update(metadata or {})
        meta = Mock(status_code=200)
        meta.json.return_value = info
        binary = Mock(status_code=binary_status, headers={'Content-Type': self.media.mime_type})
        binary.iter_content.return_value = iter([data])
        return meta, binary

    def transfer_error(self, expected, **kwargs):
        with patch('apps.channels.media_transfer.requests.get', side_effect=self.responses(**kwargs)):
            with self.assertRaises(MediaDownloadError) as failure, downloaded_media(self.media):
                self.fail('Unsafe download accepted')
        self.assertEqual(failure.exception.code, expected)
        self.assertEqual(list(self.root.glob('*.spool')), [])
        return failure.exception

    def test_image_audio_pdf_success_is_bounded_verified_and_spool_removed(self):
        for kind, mime in [('image', 'image/png'), ('audio', 'audio/ogg'), ('document', 'application/pdf')]:
            with self.subTest(kind=kind):
                self.media.message.payload_type, self.media.mime_type = kind, mime
                responses = self.responses()
                with patch('apps.channels.media_transfer.requests.get', side_effect=responses) as get:
                    with downloaded_media(self.media) as (content, metadata):
                        self.assertEqual(content.read(), DATA)
                        self.assertEqual(metadata['sha256'], SHA)
                        self.assertEqual(len(list(self.root.glob('*.spool'))), 1)
                    self.assertFalse(get.call_args.kwargs['allow_redirects'])
                    self.assertEqual(get.call_count, 2)
                self.assertEqual(list(self.root.glob('*.spool')), [])
                for response in responses:
                    response.close.assert_called_once()

    def test_expired_binary_url_is_retryable(self):
        self.assertTrue(self.transfer_error('provider_url_expired', binary_status=410).retryable)

    def test_metadata_not_found_is_permanent(self):
        response = Mock(status_code=404)
        with patch('apps.channels.media_transfer.requests.get', return_value=response):
            with self.assertRaises(MediaDownloadError) as failure, downloaded_media(self.media):
                pass
        self.assertFalse(failure.exception.retryable)

    def test_network_error_is_retryable_without_leaking_exception(self):
        with patch('apps.channels.media_transfer.requests.get', side_effect=requests.Timeout('secret-url')):
            with self.assertRaises(MediaDownloadError) as failure, downloaded_media(self.media):
                pass
        self.assertEqual(str(failure.exception), 'provider_transport')
        self.assertTrue(failure.exception.retryable)

    def test_untrusted_redirect_and_private_urls_are_rejected_before_binary_get(self):
        for url in ('http://lookaside.fbsbx.com/a', 'https://127.0.0.1/a', 'https://fbcdn.net.evil/a',
                    'https://user:pass@lookaside.fbsbx.com/a', 'https://lookaside.fbsbx.com:8443/a'):
            with self.subTest(url=url):
                self.transfer_error('invalid_download_url', metadata={'url': url})

    def test_mime_hash_advertised_and_actual_limits_are_enforced(self):
        self.transfer_error('mime_mismatch', metadata={'mime_type': 'image/jpeg'})
        self.transfer_error('checksum_mismatch', metadata={'sha256': '0'*64})
        self.transfer_error('media_too_large', metadata={'file_size': MAX_BYTES['image'] + 1})
        self.transfer_error('size_mismatch', metadata={'file_size': len(DATA) + 1})
        with patch.dict(MAX_BYTES, image=3):
            self.transfer_error('media_too_large', metadata={'file_size': None})

    def test_stream_failure_cleans_spool(self):
        meta, binary = self.responses()
        def chunks(**kwargs):
            yield DATA[:3]
            raise requests.ConnectionError('synthetic interruption')
        binary.iter_content.side_effect = chunks
        with patch('apps.channels.media_transfer.requests.get', side_effect=[meta, binary]):
            with self.assertRaises(MediaDownloadError), downloaded_media(self.media):
                pass
        self.assertEqual(list(self.root.glob('*.spool')), [])

    def test_scavenger_only_removes_old_dedicated_spools(self):
        spool_root()
        old = self.root / 'wa-orphan.spool'
        old.write_bytes(DATA)
        os.utime(old, (1, 1))
        keep = self.root / 'unrelated.txt'
        keep.write_bytes(DATA)
        fresh = self.root / 'wa-fresh.spool'
        fresh.write_bytes(DATA)
        self.assertEqual(scavenge_media_spools(), dict(removed=1, bytes=len(DATA)))
        self.assertTrue(keep.exists() and fresh.exists())
        self.assertEqual(scavenge_media_spools()['removed'], 0)


@override_settings(MEDIA_B2_ENDPOINT_URL='https://s3.us-west-004.backblazeb2.com', MEDIA_B2_REGION_NAME='us-west-004',
    MEDIA_B2_BUCKET='synthetic-private', MEDIA_B2_ACCESS_KEY_ID='synthetic-key', MEDIA_B2_SECRET_ACCESS_KEY='synthetic-secret')
class MediaStorageTests(SimpleTestCase):
    def test_storage_fails_closed_and_never_generates_urls(self):
        storage = InboxMediaStorage()
        with self.assertRaises(NotImplementedError):
            storage.url('any')
        with self.assertRaises(SuspiciousFileOperation):
            storage.open('../../file')
        with override_settings(MEDIA_BACKEND='local', INBOX_MEDIA_ALLOW_LOCAL=False), self.assertRaises(ImproperlyConfigured):
            storage._backend()
        with override_settings(MEDIA_BACKEND='b2', INBOX_MEDIA_PRODUCTION_APPROVED=False), self.assertRaises(ImproperlyConfigured):
            storage._backend()

    def test_b2_private_upload_and_physical_purge_all_versions_exact_key(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        client = Mock()
        client.get_paginator.return_value.paginate.side_effect = [[
            dict(Versions=[dict(Key=key, VersionId='v1'), dict(Key=key+'neighbor', VersionId='do-not-delete')]),
            dict(DeleteMarkers=[dict(Key=key, VersionId='hidden')], Versions=[dict(Key=key, VersionId='v2')])], []]
        client.delete_objects.return_value = {}
        with patch('boto3.client', return_value=client) as factory:
            storage = B2MediaStorage()
        content = ContentFile(DATA)
        content.content_type = 'image/png'
        self.assertEqual(storage.save(key, content), key)
        self.assertEqual(client.put_object.call_args.kwargs['ServerSideEncryption'], 'AES256')
        self.assertNotIn('ACL', client.put_object.call_args.kwargs)
        storage.delete(key)
        deleted = client.delete_objects.call_args.kwargs['Delete']['Objects']
        self.assertEqual({item['VersionId'] for item in deleted}, {'v1', 'v2', 'hidden'})
        self.assertTrue(all(item['Key'] == key for item in deleted))
        self.assertEqual(factory.call_args.kwargs['config'].retries['total_max_attempts'], 1)

    def test_b2_purge_errors_are_not_silenced(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        with patch('boto3.client') as factory:
            client = factory.return_value
            client.get_paginator.return_value.paginate.return_value = [dict(Versions=[dict(Key=key, VersionId='v')])]
            client.delete_objects.return_value = {'Errors': [{'Code': 'Denied'}]}
            with self.assertRaises(OSError):
                B2MediaStorage().delete(key)


@override_settings(INBOX_MEDIA_ENABLED=True)
class MediaWorkerTests(MediaFixtures, TransactionTestCase):
    def setUp(self):
        self.build()

    @contextmanager
    def binary(self, media):
        self.assertFalse(connection.in_atomic_block)
        yield ContentFile(DATA), dict(mime_type='image/png', file_size=len(DATA), sha256=SHA)

    def test_durable_success_retention_and_single_claim_for_discarded_inbound(self):
        row = self.media(message=self.message(payload_type='image', status='discarded'))
        claim = worker.claim_media()
        self.assertIsNone(worker.claim_media())
        with patch.object(worker, 'downloaded_media', side_effect=self.binary):
            self.assertTrue(worker.process_media_claim(claim))
        row.refresh_from_db()
        self.addCleanup(row.file.storage.delete, row.file.name)
        self.assertEqual(row.status, 'ready')
        self.assertEqual(row.sha256, SHA)
        self.assertEqual(row.expires_at - row.persisted_at, timedelta(days=180))
        self.assertEqual(row.attempts, 1)
        self.assertIsNone(row.worker_token)
        self.assertFalse(worker.process_media_claim(claim))

    def test_retry_backoff_new_claim_and_permanent_failure(self):
        row = self.media()
        claim = worker.claim_media()
        with patch.object(worker, 'downloaded_media', side_effect=MediaDownloadError('provider_url_expired', True)):
            self.assertFalse(worker.process_media_claim(claim))
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts), ('failed', 1))
        self.assertGreater(row.next_attempt_at, timezone.now())
        self.assertIsNone(worker.claim_media())
        MessageMedia.objects.filter(pk=row.pk).update(next_attempt_at=None)
        new = worker.claim_media()
        self.assertNotEqual(new.token, claim.token)
        self.assertFalse(worker.process_media_claim(claim))
        with patch.object(worker, 'downloaded_media', side_effect=MediaDownloadError('provider_http_404')):
            worker.process_media_claim(new)
        row.refresh_from_db()
        self.assertEqual(row.attempts, 5)
        self.assertIsNone(worker.claim_media())

    def test_expired_lease_recovers_and_old_worker_cannot_publish(self):
        row = self.media()
        old = worker.claim_media()
        MessageMedia.objects.filter(pk=row.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        new = worker.claim_media()
        self.assertNotEqual(old.token, new.token)
        self.assertFalse(worker.process_media_claim(old))
        with patch.object(worker, 'downloaded_media', side_effect=self.binary):
            self.assertTrue(worker.process_media_claim(new))
        row.refresh_from_db()
        self.addCleanup(row.file.storage.delete, row.file.name)

    def test_fifth_expired_claim_stops_without_loop(self):
        row = self.media(status='downloading', worker_token=uuid4(),
            lease_until=timezone.now()-timedelta(seconds=1), attempts=5)
        self.assertIsNone(worker.claim_media())
        row.refresh_from_db()
        self.assertEqual((row.status, row.error), ('failed', 'attempts_exhausted'))

    def test_crash_upload_pointer_is_purged_before_retry(self):
        row = self.media()
        key = media_upload_path(row, '')
        row.file.storage.save(key, ContentFile(b'partial'))
        MessageMedia.objects.filter(pk=row.pk).update(file=key)
        with patch.object(worker, 'downloaded_media', side_effect=self.binary):
            self.assertTrue(worker.process_media_claim(worker.claim_media()))
        row.refresh_from_db()
        self.addCleanup(row.file.storage.delete, row.file.name)
        self.assertFalse(row.file.storage.exists(key))

    def test_purge_retry_denies_immediately_and_preserves_caption(self):
        row = self.ready(expires_at=None)
        MessageMedia.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        key = row.file.name
        with patch.object(InboxMediaStorage, 'delete', side_effect=OSError('synthetic')):
            self.assertEqual(worker.expire_media(), 0)
        row.refresh_from_db()
        self.assertEqual((row.status, row.file.name, row.error), ('expired', key, 'purge_failed'))
        self.assertEqual(row.message.body, 'Caption preservada')
        self.assertEqual(worker.expire_media(), 0)
        MessageMedia.objects.filter(pk=row.pk).update(next_attempt_at=None)
        self.assertEqual(worker.expire_media(), 1)
        row.refresh_from_db()
        self.assertFalse(row.file.name)
        self.assertFalse(row.file.storage.exists(key))
        self.assertEqual(worker.expire_media(), 0)

    def test_missing_object_is_error_without_fabricated_expiration(self):
        row = self.ready()
        row.file.storage.delete(row.file.name)
        with self.assertLogs('agent.events', level='ERROR') as logs:
            self.assertEqual(worker.reconcile_ready_media(), 1)
        row.refresh_from_db()
        self.assertEqual((row.status, row.error), ('failed', 'object_missing'))
        self.assertIsNone(row.expired_at)
        self.assertNotIn(row.filename, '\n'.join(logs.output)) if row.filename else None

    def test_reconcile_storage_outage_preserves_ready_and_recovers(self):
        row = self.ready()
        with patch.object(InboxMediaStorage, 'exists', side_effect=OSError('secret')):
            self.assertEqual(worker.reconcile_ready_media(), 0)
        row.refresh_from_db()
        self.assertEqual(row.status, 'ready')
        self.assertIsNone(row.worker_token)
        MessageMedia.objects.filter(pk=row.pk).update(last_checked_at=None)
        self.assertEqual(worker.reconcile_ready_media(), 1)

    def test_two_workers_have_one_claim_and_two_purgers_delete_once(self):
        row = self.media()
        barrier = threading.Barrier(2, timeout=10)
        def claim():
            close_old_connections()
            try:
                barrier.wait()
                return worker.claim_media()
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(item is not None for item in claims), 1)
        with patch.object(worker, 'downloaded_media', side_effect=self.binary):
            worker.process_media_claim(next(item for item in claims if item))
        row.refresh_from_db()
        self.addCleanup(row.file.storage.delete, row.file.name)
        MessageMedia.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        entered, release = threading.Event(), threading.Event()
        original = InboxMediaStorage.delete
        def delete(storage, key):
            self.assertFalse(connection.in_atomic_block)
            entered.set()
            self.assertTrue(release.wait(10))
            return original(storage, key)
        def purge():
            close_old_connections()
            try:
                return worker.expire_media()
            finally:
                connection.close()
        with patch.object(InboxMediaStorage, 'delete', delete), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(purge)
            self.assertTrue(entered.wait(10))
            second = pool.submit(purge)
            self.assertEqual(second.result(timeout=10), 0)
            release.set()
            self.assertEqual(first.result(timeout=10), 1)

    def test_disabled_jobs_are_inert(self):
        with override_settings(INBOX_MEDIA_ENABLED=False), patch.object(worker, 'claim_media') as claim:
            self.assertEqual(worker.download_pending_media(), 0)
            self.assertFalse(worker.maintain_media()['enabled'])
            claim.assert_not_called()
