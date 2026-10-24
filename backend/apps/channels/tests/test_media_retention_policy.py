"""Approved retention policy: real PostgreSQL, synthetic bytes and provider APIs."""
from datetime import timedelta
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.channels import media_incidents as incidents, media_worker as worker
from apps.channels.media_clock import media_now
from apps.channels.media_revocations import (identity, provision_ledger, revocation_record, revoke_media)
from apps.channels.media_storage import B2MediaStorage, InboxMediaStorage
from apps.channels.models import MediaPurgeIncident, MessageMedia
from apps.channels.tests.test_media_pipeline import MediaFixtures


class PurgeVerificationTests(SimpleTestCase):
    def storage(self, pages):
        storage = object.__new__(B2MediaStorage)
        storage.bucket, storage.client = 'synthetic-private', Mock()
        storage.client.get_paginator.return_value.paginate.side_effect = pages
        storage.client.delete_objects.return_value = {}
        return storage

    def test_delete_ack_with_remaining_version_or_marker_is_not_success(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        for kind in ('Versions', 'DeleteMarkers'):
            with self.subTest(kind=kind):
                page = {kind: [dict(Key=key, VersionId='still-there')]}
                storage = self.storage([[page], [page]])
                with self.assertRaises(OSError):
                    storage.delete(key)

    def test_all_pages_batches_and_exact_neighbor_are_verified(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        versions = [dict(Key=key, VersionId=str(i)) for i in range(1005)]
        storage = self.storage([[dict(Versions=versions[:600]), dict(Versions=versions[600:],
            DeleteMarkers=[dict(Key=key, VersionId='marker'), dict(Key=key+'neighbor', VersionId='keep')])],
            [dict(Versions=[dict(Key=key+'neighbor', VersionId='keep')])]])
        storage.delete(key)
        calls = storage.client.delete_objects.call_args_list
        self.assertEqual([len(c.kwargs['Delete']['Objects']) for c in calls], [1000, 6])
        self.assertTrue(all(item['Key'] == key for c in calls for item in c.kwargs['Delete']['Objects']))
        self.assertEqual(storage.client.get_paginator.return_value.paginate.call_count, 2)

    def test_verification_listing_outage_propagates(self):
        key = 'inbox-media/1/' + 'a'*32 + '/' + 'b'*32 + '.bin'
        storage = self.storage([[], OSError('synthetic verification outage')])
        with self.assertRaises(OSError):
            storage.delete(key)


@override_settings(INBOX_MEDIA_ENABLED=True, MEDIA_BACKEND='local', INBOX_MEDIA_ALLOW_LOCAL=True)
class RetentionPolicyTests(MediaFixtures, TransactionTestCase):
    def setUp(self):
        self.build()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / 'inbox-media-revocations'
        config = override_settings(INBOX_MEDIA_REVOCATION_ROOT=str(self.ledger), INBOX_MEDIA_OPS_OWNER='',
            DISCORD_WEBHOOK_URL='', INBOX_MEDIA_ACCESS_HOLD=False)
        config.enable()
        self.addCleanup(config.disable)
        provision_ledger()
        self.client = APIClient()
        self.client.force_authenticate(self.actor)

    def expired(self, days=1):
        row = self.ready()
        MessageMedia.objects.filter(pk=row.pk).update(expires_at=media_now()-timedelta(days=days))
        row.refresh_from_db()
        return row

    def get_media(self, row):
        return self.client.get(f'/api/inbox/media/{row.public_id}/')

    def fail_purge(self, row):
        with patch.object(InboxMediaStorage, 'delete', side_effect=OSError('synthetic secret must not be logged')):
            self.assertEqual(worker.expire_media(), 0)
        row.refresh_from_db()
        return MediaPurgeIncident.objects.get(media=row)

    def test_first_failure_persisted_retry_daily_access_denied_and_success_needs_evidence(self):
        row = self.expired()
        stamp = row.persisted_at, row.expires_at
        issue = self.fail_purge(row)
        first = issue.first_failed_at
        self.assertEqual(issue.failure_count, 1)
        self.assertIsNone(issue.closed_at)
        self.assertGreater(row.next_attempt_at, first+timedelta(hours=22))
        self.assertEqual(self.get_media(row).status_code, 410)
        self.assertEqual(worker.expire_media(), 0)
        MessageMedia.objects.filter(pk=row.pk).update(next_attempt_at=None)
        self.assertEqual(worker.expire_media(), 1)
        row.refresh_from_db()
        issue.refresh_from_db()
        self.assertIsNotNone(row.purge_verified_at)
        self.assertEqual((row.persisted_at, row.expires_at), stamp)
        self.assertEqual(issue.first_failed_at, first)
        self.assertIsNone(issue.closed_at)
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command('inbox_media_ops', 'close', organization=self.org.pk, incident=str(issue.public_id), operator='test-ops', stdout=output)
        call_command('inbox_media_ops', 'close', organization=self.org.pk, incident=str(issue.public_id),
            operator='test-ops', evidence='synthetic-receipt:verified-absence', stdout=output)
        issue.refresh_from_db()
        self.assertIsNotNone(issue.closed_at)

    def test_delete_without_removing_local_object_keeps_pointer_and_incident(self):
        row = self.expired()
        key = row.file.name
        with patch.object(InboxMediaStorage, 'delete'):
            self.assertEqual(worker.expire_media(), 0)
        row.refresh_from_db()
        self.assertEqual(row.file.name, key)
        self.assertIsNone(row.purge_verified_at)
        self.assertEqual(MediaPurgeIncident.objects.get(media=row).failure_count, 1)

    def test_24_hour_boundary_does_not_depend_on_retry_due_or_app_clock(self):
        row = self.expired()
        issue = self.fail_purge(row)
        first = issue.first_failed_at
        with patch.object(incidents, 'media_now', return_value=first+timedelta(hours=24)-timedelta(microseconds=1)):
            incidents.audit_purge_deadlines()
        issue.refresh_from_db()
        self.assertIsNone(issue.escalated_at)
        with patch.object(incidents, 'media_now', return_value=first+timedelta(hours=24)):
            incidents.audit_purge_deadlines()
        issue.refresh_from_db()
        self.assertEqual(issue.escalated_at, first+timedelta(hours=24))

    def test_seven_day_backlog_creates_compliance_incident_before_success_and_blocks_close(self):
        row = self.expired(days=8)
        self.assertEqual(worker.expire_media(), 1)
        issue = MediaPurgeIncident.objects.get(media=row)
        self.assertIsNotNone(issue.breached_at)
        self.assertEqual(incidents.incident_counts()['compliance_incidents'], 1)
        with self.assertRaises(CommandError):
            call_command('maintain_inbox_media', alerts_only=True, stdout=io.StringIO())

    def test_absent_recipient_is_visible_nonblocking_debt_and_sends_nothing(self):
        row = self.expired()
        self.fail_purge(row)
        with patch('apps.channels.media_incidents.requests.post') as post:
            result = incidents.dispatch_purge_alerts()
        post.assert_not_called()
        self.assertEqual(result, dict(accepted=0, pending_configuration=True))
        # A real unresolved purge still fails. Missing owner/channel alone does
        # not: after verified recovery it remains a visible accepted ops debt.
        with self.assertRaises(CommandError):
            call_command('maintain_inbox_media', alerts_only=True, stdout=io.StringIO())
        MessageMedia.objects.filter(pk=row.pk).update(next_attempt_at=None)
        self.assertEqual(worker.expire_media(), 1)
        call_command('maintain_inbox_media', alerts_only=True, stdout=io.StringIO())

    @override_settings(INBOX_MEDIA_OPS_OWNER='synthetic-ops', DISCORD_WEBHOOK_URL='https://example.invalid/synthetic')
    def test_first_alert_delivery_receipt_is_not_ack_and_escalation_is_separate(self):
        row = self.expired()
        issue = self.fail_purge(row)
        response = Mock(status_code=204)
        with patch('apps.channels.media_incidents.requests.post', return_value=response) as post:
            self.assertEqual(incidents.dispatch_purge_alerts()['accepted'], 1)
            self.assertEqual(incidents.dispatch_purge_alerts()['accepted'], 0)
            self.assertEqual(post.call_count, 1)
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            self.assertNotIn(row.provider_media_id, repr(post.call_args.kwargs['json']))
            self.assertNotIn(row.file.name, repr(post.call_args.kwargs['json']))
        issue.refresh_from_db()
        self.assertIsNone(issue.acknowledged_at)
        self.assertIsNotNone(issue.notification_receipts['failure']['accepted_at'])
        with patch.object(incidents, 'media_now', return_value=issue.first_failed_at+timedelta(hours=24)):
            incidents.audit_purge_deadlines()
            with patch('apps.channels.media_incidents.requests.post', return_value=response) as post:
                self.assertEqual(incidents.dispatch_purge_alerts()['accepted'], 1)
                self.assertIn('ESCALATION', post.call_args.kwargs['json']['content'])

    def test_failed_batch_does_not_starve_later_rows_or_exit_success(self):
        rows = [self.expired() for _ in range(3)]
        MessageMedia.objects.filter(pk=rows[0].pk).update(status='expired',
            expired_at=media_now()-timedelta(days=10), expires_at=media_now()+timedelta(days=5))
        original = InboxMediaStorage.delete
        seen = []
        def delete(storage, key):
            seen.append(key)
            if key == rows[0].file.name:
                raise OSError('synthetic denied')
            return original(storage, key)
        output = io.StringIO()
        with patch.object(InboxMediaStorage, 'delete', delete), self.assertRaises(CommandError):
            call_command('maintain_inbox_media', batch=1, max_batches=3, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual((result['attempted'], result['failed'], result['purged']), (3, 1, 2))
        self.assertEqual(seen[0], rows[0].file.name, 'Earlier revocation takes priority over later natural expiry')
        self.assertEqual(result['unresolved_failures'], 1)
        output = io.StringIO()
        call_command('inbox_media_ops', 'status', organization=self.org.pk, stdout=output)
        status = json.loads(output.getvalue())
        self.assertEqual(len(status['incidents']), 1)
        self.assertEqual(status['incidents'][0]['media__public_id'], str(rows[0].public_id))
        other = io.StringIO()
        call_command('inbox_media_ops', 'status', organization=self.org.pk+10000, stdout=other)
        self.assertEqual(json.loads(other.getvalue())['incidents'], [])

    def test_capacity_limit_reports_remaining_due_instead_of_silent_success(self):
        for _ in range(3):
            self.expired()
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command('maintain_inbox_media', batch=1, max_batches=1, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual((result['purged'], result['remaining_due']), (1, 2))
        self.assertEqual(result['failed'], 0)

    @override_settings(INBOX_MEDIA_OPS_OWNER='synthetic-ops', DISCORD_WEBHOOK_URL='https://example.invalid/synthetic')
    def test_escalation_queued_during_delivery_is_not_lost_by_older_claim(self):
        row = self.expired()
        issue = self.fail_purge(row)
        def post(*args, **kwargs):
            MediaPurgeIncident.objects.filter(pk=issue.pk).update(escalated_at=media_now(), notification_pending=True)
            return Mock(status_code=204)
        with patch('apps.channels.media_incidents.requests.post', side_effect=post):
            self.assertEqual(incidents.dispatch_purge_alerts()['accepted'], 1)
        issue.refresh_from_db()
        self.assertTrue(issue.notification_pending)
        self.assertTrue(issue.notification_receipts['failure']['accepted_at'])
        self.assertNotIn('escalation', issue.notification_receipts)

    def test_database_clock_rejects_expired_and_serves_valid_despite_wrong_app_clock(self):
        row = self.expired()
        with patch('django.utils.timezone.now', return_value=media_now()-timedelta(days=365)), patch.object(InboxMediaStorage, 'open') as opened:
            self.assertEqual(self.get_media(row).status_code, 410)
            opened.assert_not_called()
        valid = self.ready()
        with patch('django.utils.timezone.now', return_value=media_now()+timedelta(days=365)):
            response = self.get_media(valid)
            self.assertEqual(response.status_code, 200)
            list(response.streaming_content)

    def test_exact_deadline_uses_persisted_value_before_storage(self):
        row = self.ready()
        with patch('apps.agent.inbox_media.media_now', return_value=row.expires_at), patch.object(InboxMediaStorage, 'open') as opened:
            self.assertEqual(self.get_media(row).status_code, 410)
            opened.assert_not_called()

    def test_independent_revocation_survives_old_db_state_and_recreated_pending_job(self):
        row = self.ready()
        old = dict(status=row.status, expired_at=row.expired_at, persisted_at=row.persisted_at, expires_at=row.expires_at,
            file=row.file.name, attempts=row.attempts, error=row.error)
        revoke_media(organization_id=self.org.pk, public_id=row.public_id)
        MessageMedia.objects.filter(pk=row.pk).update(**old)  # Synthetic old-dump replay; ledger unchanged.
        with patch.object(InboxMediaStorage, 'open') as opened:
            self.assertEqual(self.get_media(row).status_code, 410)
            opened.assert_not_called()
        MessageMedia.objects.filter(pk=row.pk).update(status='pending', persisted_at=None, expires_at=None, file='', attempts=0)
        with patch('apps.channels.media_worker.downloaded_media') as downloaded:
            self.assertIsNone(worker.claim_media())
            downloaded.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'expired')

    def test_missing_or_corrupt_ledger_and_restore_hold_fail_closed(self):
        row = self.ready()
        for config in (dict(INBOX_MEDIA_ACCESS_HOLD=True), dict(MEDIA_BACKEND='b2', INBOX_MEDIA_REVOCATION_ROOT='')):
            with override_settings(**config), patch.object(InboxMediaStorage, 'open') as opened:
                self.assertEqual(self.get_media(row).status_code, 503)
                opened.assert_not_called()
        (self.ledger / (identity(row)+'.json')).write_text('{corrupt', encoding='utf-8')
        self.assertEqual(self.get_media(row).status_code, 503)

    def test_restore_command_preserves_dates_reapplies_revocations_and_freezes_pending(self):
        row = self.ready()
        original = row.persisted_at, row.expires_at
        revoke_media(organization_id=self.org.pk, public_id=row.public_id)
        MessageMedia.objects.filter(pk=row.pk).update(status='ready', expired_at=None)
        pending = self.media()
        expired = self.expired()
        with self.assertRaises(CommandError):
            call_command('inbox_media_ops', 'restore-check', workers_stopped=True, stdout=io.StringIO())
        output = io.StringIO()
        with override_settings(INBOX_MEDIA_ACCESS_HOLD=True):
            call_command('inbox_media_ops', 'restore-check', workers_stopped=True, stdout=output)
            self.assertEqual(self.get_media(row).status_code, 410)
        row.refresh_from_db()
        pending.refresh_from_db()
        expired.refresh_from_db()
        self.assertEqual((row.persisted_at, row.expires_at), original)
        self.assertEqual((row.status, pending.status, expired.status), ('expired', 'expired', 'expired'))
        self.assertIsNone(worker.claim_media())
        result = json.loads(output.getvalue())
        self.assertFalse(result['traffic_reopened'])
        self.assertTrue(result['requires_provider_orphan_inventory'])
