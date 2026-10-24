"""WA-RETRY-01 API, real PostgreSQL serialization, and B4 dispatch boundaries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import Mock, patch
import uuid

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import sender
from apps.agent.models import Conversation
from apps.agent.services import record_status_update
from apps.agent.tests.test_b4_sender import SenderFixture
from apps.channels.models import Message
from apps.channels.providers import SendResult
from apps.users.models import User


class InboxRetryTests(SenderFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.actor = User.objects.create(username='retry-actor', organization=self.org, role='ASSISTANT')
        self.author = User.objects.create(username='original-author', organization=self.org, role='ASSISTANT')
        self.conv.state = Conversation.STATE_HUMAN_ACTIVE
        self.conv.claimed_by = self.author
        self.conv.save(update_fields=['state', 'claimed_by'])
        Message.objects.filter(pk=self.message.pk).update(author_type=Message.AUTHOR_HUMAN,
            human_author=self.author, idempotency_key='original-key', status='failed',
            failure_reason='credentials_missing', attempts=5)
        self.message.refresh_from_db()
        self.client = APIClient()
        self.client.force_authenticate(self.actor)
        self.url = f'/api/inbox/conversations/{self.conv.public_id}/messages/{self.message.pk}/retry/'

    def post(self, **kwargs):
        return self.client.post(self.url, {}, format='json', **kwargs)

    def test_other_staff_requeues_same_row_preserving_payload_author_key_and_claim(self):
        before = Message.objects.values().get(pk=self.message.pk)
        with self.assertLogs('agent.events') as logs:
            response = self.post(HTTP_X_IDEMPOTENCY_KEY='original-key')
        self.assertEqual(response.status_code, 200, response.data)
        self.message.refresh_from_db()
        after = Message.objects.values().get(pk=self.message.pk)
        changed = {name for name in before if before[name] != after[name]}
        self.assertTrue(changed <= {'status', 'attempts', 'failure_reason', 'next_attempt_at',
                                   'updated_at', 'updated_by_id'})
        self.assertEqual((self.message.status, self.message.attempts, self.message.failure_reason),
                         ('pending', 0, ''))
        self.assertIsNotNone(self.message.next_attempt_at)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(response.data['client_message_id'], 'original-key')
        self.assertEqual(response.data['human_author_public_id'], str(self.author.public_id))
        self.assertEqual(response.data['conversation_public_id'], str(self.conv.public_id))
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.claimed_by_id, self.author.pk)
        row = [record for record in logs.records if record.getMessage() == 'INBOX_MESSAGE_RETRY'][0]
        self.assertEqual((row.organization_id, row.conversation_id, row.message_id,
                          row.actor_id, row.original_author_id, row.result),
                         (self.org.pk, self.conv.pk, self.message.pk, self.actor.pk, self.author.pk, 'pending'))
        self.assertNotIn(self.message.body, str(logs.output))
        self.assertNotIn('original-key', str(logs.output))

    def test_known_rejection_is_dispatched_by_existing_sender_once_with_new_token(self):
        Message.objects.filter(pk=self.message.pk).update(status='pending', attempts=0)
        old_claim = self.claim()
        sender.dispatch_claim(old_claim, self.factory('known_rejected', code='meta_190'))
        self.assertEqual(self.state(), 'failed')
        token = self.message.send_token
        self.assertEqual(self.post().status_code, 200)
        self.assertFalse(sender.finalize_dispatch(old_claim, SendResult('accepted', 'wamid.OLD')))
        factory = self.factory()
        sender.send_pending_outbound(provider_factory=factory)
        sender.send_pending_outbound(provider_factory=factory)
        self.assertEqual(self.state(), 'sent')
        self.assertNotEqual(self.message.send_token, token)
        self.assertFalse(sender.finalize_dispatch(old_claim, SendResult('accepted', 'wamid.OLD')))
        factory.return_value.send_text.assert_called_once()
        self.assertEqual(self.message.idempotency_key, 'original-key')

    def test_window_closed_or_unknown_returns_call_without_changes(self):
        for stamp in (None, timezone.now() - timedelta(hours=25)):
            with self.subTest(stamp=stamp):
                Conversation.objects.filter(pk=self.conv.pk).update(last_inbound_at=stamp)
                before = Message.objects.values().get(pk=self.message.pk)
                response = self.post()
                self.assertEqual(response.status_code, 400)
                self.assertEqual((response.data['code'], response.data['suggestion']), ('window_closed', 'call'))
                self.assertEqual(before, Message.objects.values().get(pk=self.message.pk))

    def test_sender_rechecks_window_between_retry_and_dispatch(self):
        self.assertEqual(self.post().status_code, 200)
        Conversation.objects.filter(pk=self.conv.pk).update(last_inbound_at=timezone.now()-timedelta(hours=25))
        factory = self.factory()
        sender.send_pending_outbound(provider_factory=factory)
        factory.assert_not_called()
        self.assertEqual(self.state(), 'failed')

    def test_nonfailed_including_uncertain_never_requeues(self):
        for status in ('pending', 'sending', 'sent', 'delivered', 'read', 'uncertain', 'discarded', 'processed'):
            with self.subTest(status=status):
                Message.objects.filter(pk=self.message.pk).update(status=status, send_token=uuid.uuid4(),
                    send_started_at=timezone.now(), send_lease_until=timezone.now()+timedelta(minutes=2),
                    uncertain_at=timezone.now() if status == 'uncertain' else None)
                self.assertEqual(self.post().status_code, 400)
                self.assertEqual(self.state(), status)

    def test_inbound_failed_is_rejected(self):
        Message.objects.filter(pk=self.message.pk).update(direction='in', author_type='client')
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.state(), 'failed')

    def test_failed_with_any_acceptance_or_uncertainty_evidence_is_unchanged(self):
        for field in ('external_message_id', 'provider_accepted_at', 'delivered_at', 'read_at', 'uncertain_at'):
            with self.subTest(field=field):
                value = 'wamid.KNOWN' if field == 'external_message_id' else timezone.now()
                Message.objects.filter(pk=self.message.pk).update(**{field: value})
                response = self.post()
                self.assertEqual((response.status_code, response.data['code']), (400, 'external_evidence'))
                self.assertEqual(self.state(), 'failed')
                self.assertEqual(getattr(self.message, field), value)
                Message.objects.filter(pk=self.message.pk).update(**{field: None})

    def test_late_receipt_reconciles_failed_and_cannot_be_reset(self):
        Message.objects.filter(pk=self.message.pk).update(external_message_id='wamid.LATE')
        record_status_update(self.channel, 'wamid.LATE', 'read')
        self.assertEqual(self.state(), 'read')
        self.assertEqual(self.post().status_code, 400)
        record_status_update(self.channel, 'wamid.LATE', 'sent')
        self.assertEqual(self.state(), 'read')

    def test_changed_epoch_or_legacy_epoch_never_renews_authority(self):
        for epoch in (None, self.conv.ownership_epoch + 1):
            Message.objects.filter(pk=self.message.pk).update(origin_epoch=epoch)
            response = self.post()
            self.assertEqual((response.status_code, response.data['code']), (400, 'retry_not_authorized'))
            self.assertEqual(self.state(), 'failed')
            self.assertEqual(self.message.origin_epoch, epoch)

    def test_closed_session_is_not_reopened(self):
        Conversation.objects.filter(pk=self.conv.pk).update(state='closed', closed_at=timezone.now())
        response = self.post()
        self.assertEqual((response.status_code, response.data['code']), (400, 'session_closed'))
        self.assertEqual(self.state(), 'failed')

    def test_paused_account_is_not_queued(self):
        type(self.channel).objects.filter(pk=self.channel.pk).update(status='paused')
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.state(), 'failed')

    def test_different_key_is_rejected_and_cannot_edit_body(self):
        self.assertEqual(self.post(HTTP_X_IDEMPOTENCY_KEY='another').status_code, 400)
        response = self.client.post(self.url, {'body': 'edited', 'idempotency_key': 'edited'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual((self.message.body, self.message.idempotency_key), ('B4 text', 'original-key'))

    def test_without_original_key_reuses_same_message(self):
        Message.objects.filter(pk=self.message.pk).update(idempotency_key=None)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['client_message_id'])
        self.assertEqual(Message.objects.count(), 1)

    def test_another_conversation_or_account_is_404_even_with_original_key(self):
        other = Conversation.objects.create(organization=self.org, contact=self.contact,
            channel_account=self.channel, state='closed', closed_at=timezone.now())
        wrong = f'/api/inbox/conversations/{other.public_id}/messages/{self.message.pk}/retry/'
        self.assertEqual(self.client.post(wrong, HTTP_X_IDEMPOTENCY_KEY='original-key').status_code, 404)
        self.assertEqual(self.state(), 'failed')

    def test_foreign_organization_is_404(self):
        from apps.organizations.models import Organization
        foreign = Organization.objects.create(name='Foreign', timezone='UTC')
        actor = User.objects.create(username='foreign', organization=foreign, role='ADMIN')
        self.client.force_authenticate(actor)
        self.assertEqual(self.post(HTTP_X_IDEMPOTENCY_KEY='original-key').status_code, 404)

    def test_corrupt_cross_account_scope_is_404(self):
        from apps.channels.models import ChannelAccount
        other = ChannelAccount.objects.create(organization=self.org, external_account_id='other')
        Message.objects.filter(pk=self.message.pk).update(channel_account=other)
        self.assertEqual(self.post().status_code, 404)

    def test_view_only_service_account_and_anonymous_are_denied(self):
        for role in ('VET', 'AGENT'):
            actor = User.objects.create(username='viewer-'+role, organization=self.org, role=role)
            self.client.force_authenticate(actor)
            self.assertEqual(self.post().status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.post().status_code, (401, 403))

    def test_double_retry_real_connections_performs_one_transition(self):
        self.assertEqual(connection.vendor, 'postgresql')
        barrier = Barrier(2)
        def concurrent_retry(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=self.actor.pk))
                barrier.wait(timeout=10)
                response = client.post(self.url, HTTP_X_IDEMPOTENCY_KEY='original-key')
                return response.status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(concurrent_retry, range(2)))
        self.assertCountEqual(statuses, [200, 400])
        self.assertEqual(self.state(), 'pending')
        self.assertEqual(Message.objects.count(), 1)
