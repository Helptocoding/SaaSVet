"""SEND-01/03/04 and OWN-03 against real PostgreSQL transactions."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock, patch
import uuid

from django.db import connection, transaction, IntegrityError
from django.test import TransactionTestCase
from django.utils import timezone

from apps.agent import durable, sender
from apps.agent.models import ContactIdentity, Conversation
from apps.agent.services import record_status_update
from apps.channels.models import ChannelAccount, Message
from apps.channels.providers import SendResult, ProviderError
from apps.organizations.models import Organization
from apps.users.models import User


class SenderFixture:
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.org = Organization.objects.create(name='B4', timezone='UTC')
        self.channel = ChannelAccount.objects.create(organization=self.org, external_account_id='b4')
        self.contact = ContactIdentity.objects.create(organization=self.org, external_id='5215512345678')
        self.conv = Conversation.objects.create(organization=self.org, channel_account=self.channel,
            contact=self.contact, last_inbound_at=timezone.now())
        self.message = self.outbound()

    def outbound(self, **kwargs):
        values = dict(organization=self.org, channel_account=self.channel, conversation=self.conv,
            contact=self.contact, direction='out', author_type=Message.AUTHOR_AGENT, body='B4 text',
            origin_epoch=self.conv.ownership_epoch)
        values.update(kwargs)
        return Message.objects.create(**values)

    def claim(self, message=None):
        return sender.claim_message((message or self.message).pk, organization_id=self.org.pk,
                                    channel_account_id=self.channel.pk)

    def takeover(self):
        with transaction.atomic():
            conv = Conversation.objects.select_for_update().get(pk=self.conv.pk)
            durable.invalidate_ownership(conv, reason='test_takeover')
            conv.state = Conversation.STATE_HUMAN_ACTIVE
            conv.save(update_fields=['state'])

    def expire(self):
        Message.objects.filter(pk=self.message.pk).update(
            send_lease_until=timezone.now() - timedelta(seconds=1))

    def state(self):
        self.message.refresh_from_db()
        return self.message.status

    def factory(self, kind='accepted', **kwargs):
        factory = Mock()
        factory.return_value.send_text.return_value = SendResult(kind,
            provider_id='wamid.B4' if kind == 'accepted' else '', **kwargs)
        return factory


class B4SenderTests(SenderFixture, TransactionTestCase):
    def test_disabled_organization_keeps_queue_without_provider_admission(self):
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        factory = self.factory()
        sender.send_pending_outbound(provider_factory=factory)
        factory.assert_not_called()
        self.assertEqual(self.state(), 'pending')
        self.assertIsNone(self.message.send_admitted_at)

    def test_deactivation_between_claim_and_admission_preserves_unsent_message(self):
        claim = self.claim()
        self.assertIsNotNone(claim)
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        self.assertIsNone(sender.admit_dispatch(claim))
        self.assertEqual(self.state(), 'pending')
        self.assertIsNone(self.message.send_admitted_at)

    def test_send_01_individual_durable_claim_and_single_admission(self):
        other = self.outbound()
        claim = self.claim()
        self.assertEqual(self.state(), 'sending')
        self.assertIsInstance(self.message.send_token, uuid.UUID)
        self.assertIsNotNone(self.message.send_started_at)
        self.assertGreater(self.message.send_lease_until, self.message.send_started_at)
        self.assertIsNone(self.message.send_admitted_at)
        self.assertIsNone(self.claim())
        self.assertEqual(Message.objects.get(pk=other.pk).status, 'pending')
        factory = self.factory()
        self.assertTrue(sender.dispatch_claim(claim, factory))
        self.assertFalse(sender.dispatch_claim(claim, factory))
        factory.return_value.send_text.assert_called_once()

    def test_http_runs_outside_transaction(self):
        factory = self.factory()
        def http(*args):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(connection.get_autocommit())
            self.assertEqual(self.state(), 'sending')
            self.assertIsNotNone(self.message.send_admitted_at)
            return SendResult('accepted', 'wamid.B4')
        factory.return_value.send_text.side_effect = http
        sender.send_pending_outbound(provider_factory=factory)
        self.assertEqual(self.state(), 'sent')
        self.assertIsNotNone(self.message.provider_accepted_at)
        self.assertIsNone(self.message.delivered_at)

    def test_caller_transaction_is_rejected(self):
        with transaction.atomic(), self.assertRaises(RuntimeError):
            sender.send_pending_outbound(provider_factory=self.factory())
        self.assertEqual(self.state(), 'pending')

    def test_send_fi_01_claim_crash_never_admitted_and_no_replay(self):
        claim = self.claim()
        self.expire()
        self.assertEqual(sender.recover_expired(), 1)
        self.assertEqual(self.state(), 'uncertain')
        self.assertIsNone(self.message.send_admitted_at)
        self.assertEqual(self.message.failure_reason, 'lease_expired_before_admission')
        self.assertIsNone(sender.admit_dispatch(claim))
        factory = self.factory()
        sender.send_pending_outbound(provider_factory=factory)
        factory.assert_not_called()

    def test_own_03_takeover_before_claim(self):
        self.takeover()
        factory = self.factory()
        sender.send_pending_outbound(provider_factory=factory)
        factory.assert_not_called()
        self.assertEqual(self.state(), 'discarded')

    def test_send_fi_02_takeover_after_claim_before_http(self):
        claim = self.claim()
        self.takeover()
        factory = self.factory()
        self.assertFalse(sender.dispatch_claim(claim, factory))
        factory.assert_not_called()
        self.assertEqual(self.state(), 'discarded')
        self.assertIsNone(self.message.send_admitted_at)

    def test_epoch_change_without_discard_is_checked_at_admission(self):
        claim = self.claim()
        Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=1)
        self.assertIsNone(sender.admit_dispatch(claim))
        self.assertEqual(self.state(), 'discarded')

    def test_send_fi_03_post_acceptance_db_failure_is_uncertain_no_retry(self):
        claim = self.claim()
        factory = self.factory()
        with patch.object(sender, 'finalize_dispatch', side_effect=IntegrityError('injected')):
            with self.assertRaises(IntegrityError):
                sender.dispatch_claim(claim, factory)
        self.assertEqual(self.state(), 'sending')
        self.assertIsNone(self.message.external_message_id)
        self.expire()
        sender.send_pending_outbound(provider_factory=factory)
        factory.return_value.send_text.assert_called_once()
        self.assertEqual(self.state(), 'uncertain')

    def test_send_fi_08_takeover_during_http_records_acceptance(self):
        factory = self.factory()
        def http(*args):
            self.takeover()
            self.outbound()  # old epoch, cannot dispatch
            return SendResult('accepted', 'wamid.B4')
        factory.return_value.send_text.side_effect = http
        sender.dispatch_claim(self.claim(), factory)
        sender.send_pending_outbound(provider_factory=factory)
        self.assertEqual(self.state(), 'sent')
        factory.return_value.send_text.assert_called_once()
        self.assertEqual(Message.objects.exclude(pk=self.message.pk).get().status, 'discarded')

    def test_send_fi_09_takeover_during_http_records_uncertainty(self):
        factory = self.factory()
        def http(*args):
            self.takeover()
            return SendResult('uncertain', code='timeout')
        factory.return_value.send_text.side_effect = http
        sender.dispatch_claim(self.claim(), factory)
        self.assertEqual(self.state(), 'uncertain')

    def test_takeover_during_http_rejection_is_failed_not_retry(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        self.takeover()
        sender.finalize_dispatch(claim, SendResult('known_rejected', code='meta_130429', retryable=True))
        self.assertEqual(self.state(), 'failed')

    def test_invalid_token_cannot_finalize_external_result(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        self.assertFalse(sender.finalize_dispatch(replace(claim, token=uuid.uuid4()),
                                                 SendResult('accepted', 'wamid.B4')))
        self.assertEqual(self.state(), 'sending')

    def test_finalization_scope_cannot_be_forged(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        self.assertFalse(sender.finalize_dispatch(replace(claim, organization_id=self.org.pk + 1000),
                                                 SendResult('accepted', 'wamid.B4')))
        self.assertEqual(self.state(), 'sending')

    def test_expired_lease_can_record_late_acceptance_with_same_token(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        self.expire()
        sender.recover_expired()
        stamp = Message.objects.get(pk=self.message.pk).uncertain_at
        sender.finalize_dispatch(claim, SendResult('accepted', 'wamid.B4'))
        self.assertEqual(self.state(), 'sent')
        self.assertEqual(self.message.uncertain_at, stamp)

    def test_legacy_retryable_exception_is_uncertain(self):
        factory = self.factory()
        factory.return_value.send_text.side_effect = ProviderError('500', retryable=True)
        sender.dispatch_claim(self.claim(), factory)
        self.assertEqual(self.state(), 'uncertain')
        self.assertIsNone(self.message.next_attempt_at)

    def test_invalid_accepted_result_is_uncertain(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('accepted'))
        self.assertEqual(self.state(), 'uncertain')

    def test_known_retry_has_backoff_new_token_and_limit(self):
        original = self.claim()
        sender.dispatch_claim(original, self.factory('known_rejected', code='meta_130429', retryable=True))
        self.assertEqual(self.state(), 'pending')
        self.assertGreater(self.message.next_attempt_at, timezone.now())
        self.assertIsNone(self.claim())
        Message.objects.filter(pk=self.message.pk).update(next_attempt_at=None, attempts=4)
        last = self.claim()
        self.assertNotEqual(last.token, original.token)
        self.assertFalse(sender.finalize_dispatch(original, SendResult('accepted', 'wamid.OLD')))
        sender.dispatch_claim(last, self.factory('known_rejected', code='meta_130429', retryable=True))
        self.assertEqual(self.state(), 'failed')
        self.assertEqual(self.message.attempts, 5)

    def test_retryable_flag_without_approved_rejection_code_does_not_retry(self):
        sender.dispatch_claim(self.claim(), self.factory('known_rejected', code='unknown', retryable=True))
        self.assertEqual(self.state(), 'failed')
        self.assertIsNone(self.message.next_attempt_at)

    def test_legacy_pending_without_epoch_is_discarded(self):
        Message.objects.filter(pk=self.message.pk).update(origin_epoch=None)
        self.assertIsNone(self.claim())
        self.assertEqual(self.state(), 'discarded')
        self.assertEqual(self.message.failure_reason, 'legacy_unverified')

    def test_claim_wrong_account_or_org_is_denied(self):
        for scope in ({'organization_id': self.org.pk + 99, 'channel_account_id': self.channel.pk},
                      {'organization_id': self.org.pk, 'channel_account_id': self.channel.pk + 99}):
            self.assertIsNone(sender.claim_message(self.message.pk, **scope))
        self.assertEqual(self.state(), 'pending')

    def test_pending_with_prior_external_evidence_is_quarantined(self):
        Message.objects.filter(pk=self.message.pk).update(external_message_id='wamid.legacy')
        self.assertIsNone(self.claim())
        self.assertEqual(self.state(), 'uncertain')
        self.assertEqual(self.message.external_message_id, 'wamid.legacy')

    def test_nonpending_states_are_never_selected(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        for status in ('uncertain', 'sent', 'delivered', 'read', 'failed', 'discarded'):
            Message.objects.filter(pk=self.message.pk).update(status=status)
            factory = self.factory()
            self.assertEqual(sender.send_pending_outbound(provider_factory=factory), 0)
            factory.assert_not_called()

    def test_window_closed_after_claim_blocks_admission(self):
        claim = self.claim()
        Conversation.objects.filter(pk=self.conv.pk).update(last_inbound_at=timezone.now()-timedelta(hours=25))
        factory = self.factory()
        self.assertFalse(sender.dispatch_claim(claim, factory))
        factory.assert_not_called()
        self.assertEqual(self.state(), 'failed')

    def test_first_message_survives_second_finalize_failure(self):
        first = self.claim()
        sender.dispatch_claim(first, self.factory())
        other = self.outbound()
        with patch.object(sender, 'finalize_dispatch', side_effect=IntegrityError('injected')):
            with self.assertRaises(IntegrityError):
                sender.dispatch_claim(self.claim(other), self.factory())
        self.assertEqual(self.state(), 'sent')
        self.assertEqual(Message.objects.get(pk=other.pk).status, 'sending')

    def test_reemission_new_message_with_actor_reason_and_idempotency(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        self.message.refresh_from_db()
        token, stamp = self.message.send_token, self.message.uncertain_at
        actor = User.objects.create(username='b4staff', organization=self.org, role='ASSISTANT')
        new = sender.reemit_uncertain(self.message.pk, actor=actor, reason='Operador decide reemitir',
                                     idempotency_key='b4-explicit')
        again = sender.reemit_uncertain(self.message.pk, actor=actor, reason='Mismo intento',
                                       idempotency_key='b4-explicit')
        self.assertEqual(new.pk, again.pk)
        self.assertNotEqual(new.pk, self.message.pk)
        self.assertEqual((new.status, new.supersedes_message_id, new.human_author_id),
                         ('pending', self.message.pk, actor.pk))
        self.assertEqual(self.state(), 'uncertain')
        self.assertEqual((self.message.send_token, self.message.uncertain_at), (token, stamp))

    def test_constraints_reject_claimless_sending_and_timestampless_uncertainty(self):
        for status in ('sending', 'uncertain'):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Message.objects.filter(pk=self.message.pk).update(status=status)

    def test_snapshot_makes_uncertainty_visible_without_pii(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        with self.assertLogs('agent.events') as logs:
            snapshot = sender.observe_outbound()
        self.assertEqual(snapshot['uncertain']['count'], 1)
        self.assertGreaterEqual(snapshot['uncertain']['age_seconds'], 0)
        self.assertNotIn(self.message.body, str(logs.output))

    def test_real_db_error_in_finalize_preserves_durable_sending(self):
        from django.db import DatabaseError
        apply = sender.apply_evidence
        def fail(*args, **kwargs):
            fields = apply(*args, **kwargs)
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')
            return fields
        with patch.object(sender, 'apply_evidence', side_effect=fail):
            with self.assertRaises(DatabaseError):
                sender.dispatch_claim(self.claim(), self.factory())
        self.assertEqual(self.state(), 'sending')
        self.assertIsNone(self.message.external_message_id)
        self.expire()
        sender.recover_expired()
        self.assertEqual(self.state(), 'uncertain')

    def test_partial_safe_id_survives_uncertainty_for_later_webhook(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('uncertain', 'wamid.B4', 'partial_evidence'))
        self.assertEqual(self.state(), 'uncertain')
        self.assertEqual(self.message.external_message_id, 'wamid.B4')
        record_status_update(self.channel, 'wamid.B4', 'delivered')
        self.assertEqual(self.state(), 'delivered')

    def test_meta_failure_matrix_through_real_sender(self):
        import requests
        from apps.channels.providers import MetaWhatsAppProvider
        cases = [(200, {}, None, 'uncertain'), (200, ValueError(), None, 'uncertain'),
                 (200, {}, requests.Timeout(), 'uncertain'),
                 (500, {'error': {'code': 131000}}, None, 'uncertain'),
                 (401, {'error': {'code': 190}}, None, 'failed'),
                 (200, {'messages': [{'id': 'wamid.B4'}]}, None, 'sent')]
        for index, (http, payload, exc, expected) in enumerate(cases):
            with self.subTest(index=index):
                message = self.message if index == 0 else self.outbound()
                response = Mock(status_code=http)
                if isinstance(payload, Exception):
                    response.json.side_effect = payload
                else:
                    response.json.return_value = payload
                def post(*args, **kwargs):
                    self.assertFalse(connection.in_atomic_block)
                    if exc:
                        raise exc
                    return response
                with patch.object(MetaWhatsAppProvider, '_access_token', return_value='test'), \
                     patch('apps.channels.providers.requests.post', side_effect=post):
                    sender.dispatch_claim(self.claim(message), MetaWhatsAppProvider)
                message.refresh_from_db()
                self.assertEqual(message.status, expected)
                self.assertIsNone(message.next_attempt_at)

    def test_reemission_rejects_agent_and_other_org(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        other = Organization.objects.create(name='Foreign', timezone='UTC')
        actors = [User.objects.create(username='b4agent', organization=self.org, role='AGENT',
                                      is_service_account=True),
                  User.objects.create(username='b4foreign', organization=other, role='ADMIN')]
        for actor in actors:
            with self.subTest(actor=actor.username), self.assertRaises(ValueError):
                sender.reemit_uncertain(self.message.pk, actor=actor, reason='check', idempotency_key='check')
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)


class B4StatusTests(SenderFixture, TransactionTestCase):
    def accepted(self):
        sender.dispatch_claim(self.claim(), self.factory())

    def status(self, status, **kwargs):
        return record_status_update(kwargs.get('channel', self.channel),
                                    kwargs.get('wamid', 'wamid.B4'), status)

    def test_send_03_monotonic_sent_delivered_read_and_duplicate_timestamps(self):
        self.accepted()
        self.status('delivered')
        self.assertEqual(self.state(), 'delivered')
        delivered = self.message.delivered_at
        self.status('delivered')
        self.status('read')
        self.assertEqual(self.state(), 'read')
        read = self.message.read_at
        self.status('read')
        self.status('delivered')
        self.status('sent')
        self.assertEqual(self.state(), 'read')
        self.assertEqual((self.message.delivered_at, self.message.read_at), (delivered, read))

    def test_send_fi_10_webhook_reconciles_uncertain_preserves_history(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        # An exact provider ID known from durable evidence, never a text/time match.
        Message.objects.filter(pk=self.message.pk).update(external_message_id='wamid.B4')
        self.message.refresh_from_db()
        stamp = self.message.uncertain_at
        self.status('delivered')
        self.assertEqual(self.state(), 'delivered')
        self.assertEqual(self.message.uncertain_at, stamp)
        self.assertIsNone(self.message.provider_accepted_at)

    def test_send_fi_11_read_before_delivered_never_degrades(self):
        self.accepted()
        self.status('read')
        self.status('delivered')
        self.assertEqual(self.state(), 'read')

    def test_unknown_status_unknown_id_and_wrong_account_do_nothing(self):
        self.accepted()
        other = ChannelAccount.objects.create(organization=self.org, external_account_id='other')
        self.assertIsNone(self.status('alien'))
        self.assertIsNone(self.status('read', wamid='wamid.unknown'))
        self.assertIsNone(self.status('read', channel=other))
        self.assertEqual(self.state(), 'sent')

    def test_correct_wamid_wrong_org_cannot_mutate(self):
        self.accepted()
        org = Organization.objects.create(name='Other', timezone='UTC')
        channel = ChannelAccount.objects.create(organization=org, external_account_id='foreign')
        self.assertIsNone(self.status('read', channel=channel))
        self.channel.organization_id = org.pk  # forged in-memory account context
        self.assertIsNone(self.status('read'))
        self.assertEqual(self.state(), 'sent')

    def test_webhook_cannot_resurrect_pending_or_discarded(self):
        Message.objects.filter(pk=self.message.pk).update(external_message_id='wamid.B4')
        self.status('read')
        self.assertEqual(self.state(), 'pending')
        self.takeover()
        self.status('sent')
        self.assertEqual(self.state(), 'discarded')

    def test_failed_delivery_never_erases_acceptance_or_read(self):
        self.accepted()
        self.status('failed')
        self.assertEqual(self.state(), 'sent')
        self.assertEqual(self.message.failure_reason, 'provider_delivery_failed')
        self.status('read')
        self.status('failed')
        self.assertEqual(self.state(), 'read')

    def test_uncertain_without_persisted_id_stays_unmatched(self):
        sender.dispatch_claim(self.claim(), self.factory('uncertain', code='timeout'))
        self.assertIsNone(self.status('delivered'))
        self.assertEqual(self.state(), 'uncertain')

    def test_duplicate_provider_id_is_ambiguous_not_first_match(self):
        self.accepted()
        self.outbound(status='sent', external_message_id='wamid.B4')
        self.assertIsNone(self.status('read'))
        self.assertEqual(self.state(), 'sent')

    def test_legacy_sent_keeps_unknown_acceptance_timestamp(self):
        Message.objects.filter(pk=self.message.pk).update(status='sent', external_message_id='wamid.B4')
        self.status('delivered')
        self.assertEqual(self.state(), 'delivered')
        self.assertIsNone(self.message.provider_accepted_at)

    def test_webhook_wins_race_with_uncertain_finalize(self):
        claim = self.claim()
        sender.admit_dispatch(claim)
        Message.objects.filter(pk=self.message.pk).update(external_message_id='wamid.B4')
        self.status('read')
        self.assertFalse(sender.finalize_dispatch(claim, SendResult('uncertain', code='timeout')))
        self.assertEqual(self.state(), 'read')
