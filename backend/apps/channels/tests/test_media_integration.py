"""Entrypoints, portable keys, provider race and SDK missing-object contract."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import threading
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TransactionTestCase

from apps.channels.media_ingest import persist_inbound_media
from apps.channels.media_storage import B2MediaStorage, InboxMediaStorage
from apps.channels.models import Message, MessageMedia
from apps.channels.tests.test_media_pipeline import MediaFixtures


class MediaEntrypointTests(SimpleTestCase):
    def test_filefield_keys_remain_posix_on_windows_and_linux(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        storage = InboxMediaStorage()
        self.assertEqual(storage.generate_filename(key.replace('/', '\\')), key)
        self.assertEqual(storage.generate_filename(key), key)

    def test_b2_missing_variants_are_normalized_and_other_errors_propagate(self):
        storage = object.__new__(B2MediaStorage)
        storage.bucket, storage.client = 'synthetic-bucket', Mock()
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        for code in ('404', 'NoSuchKey', 'NotFound', 'AccessDenied'):
            storage.client.get_object.side_effect = ClientError({'Error': {'Code': code}}, 'GetObject')
            with self.subTest(code=code), self.assertRaises(ClientError if code == 'AccessDenied' else FileNotFoundError):
                storage.open(key)

    def test_media_mode_is_independent_and_uses_one_item(self):
        with patch('apps.agent.management.commands.run_agent_worker.process_pending_conversations') as planner, \
                patch('apps.agent.management.commands.run_agent_worker.send_pending_outbound') as sender, \
                patch('apps.channels.media_worker.download_pending_media', return_value=1) as media:
            call_command('run_agent_worker', mode='media', once=True, stdout=io.StringIO())
        planner.assert_not_called()
        sender.assert_not_called()
        media.assert_called_once_with(batch=1)

    def test_nightly_job_is_bounded_and_disabled_is_inert(self):
        result = dict(enabled=False, purged=0, checked=0, attempted=0, failed=0,
            alerts=dict(accepted=0, pending_configuration=True), spools=dict(removed=0, bytes=0))
        output = io.StringIO()
        with patch('apps.channels.management.commands.maintain_inbox_media.maintain_media', return_value=result) as maintain:
            call_command('maintain_inbox_media', batch=2, max_batches=3, stdout=output)
            self.assertFalse(json.loads(output.getvalue())['enabled'])
            maintain.assert_called_once_with(2, alerts_only=False)
        with self.assertRaises(CommandError):
            call_command('maintain_inbox_media', batch=0)
        result.update(enabled=True, purged=2, attempted=2)
        with patch('apps.channels.management.commands.maintain_inbox_media.maintain_media', return_value=result) as maintain, \
                patch('apps.channels.management.commands.maintain_inbox_media.incident_counts',
                    return_value=dict(open_incidents=0, compliance_incidents=0, unresolved_failures=0)), \
                patch('apps.channels.management.commands.maintain_inbox_media.purge_backlog',
                    return_value=dict(purge_pending=0, remaining_due=0)):
            call_command('maintain_inbox_media', batch=2, max_batches=3, stdout=io.StringIO())
            self.assertEqual(maintain.call_count, 3)


class MediaProviderRaceTests(MediaFixtures, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.build()

    def test_two_messages_with_same_provider_reference_create_one_media(self):
        messages = [self.message(payload_type='image') for _ in range(2)]
        barrier = threading.Barrier(2, timeout=10)
        def persist(pk):
            close_old_connections()
            try:
                message = Message.objects.for_organization(self.org).get(pk=pk)
                barrier.wait()
                return persist_inbound_media(message, {'provider_media_id': 'shared-race', 'mime_type': 'image/png'}).pk
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(persist, [message.pk for message in messages]))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(MessageMedia.objects.count(), 1)
        self.assertEqual(Message.objects.filter(pk__in=[message.pk for message in messages]).count(), 2)
