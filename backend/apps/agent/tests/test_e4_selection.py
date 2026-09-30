"""E4 candidate selection on PostgreSQL; real B3/B9C claim authority."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase
from django.utils import timezone

from apps.agent import durable, worker
from apps.agent.models import Conversation, TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from .b9a_harness import ApplicationHarness
from . import test_b9c_concurrency as b9c


class E4SelectionTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp
    inbound = b9c.B9CConcurrencyTests.inbound

    def other(self, suffix='B', number=99):
        org, channel, *_ = b9a.seed_domain(suffix)
        return org, self.inbound(number, ApplicationHarness(channel))

    def run_poll(self, batch=1):
        with patch.object(worker, '_run_turn', side_effect=durable.finalize_turn):
            return worker.process_pending_conversations(batch=batch)

    def test_e4_sel_01_idle_org_precedes_older_recently_claimed_noisy_org(self):
        old = self.inbound()
        durable.finalize_turn(durable.claim_turn(old.conversation_id))
        noisy = self.inbound(2)
        org, healthy = self.other()
        Conversation.objects.filter(pk=noisy.conversation_id).update(
            last_activity_at=timezone.now()-timedelta(hours=1))
        self.assertEqual(self.run_poll(), 1)
        healthy.refresh_from_db(); noisy.refresh_from_db()
        self.assertIsNotNone(healthy.turn_work_id)
        self.assertIsNone(noisy.turn_work_id)
        self.assertEqual(TurnWork.objects.get(pk=healthy.turn_work_id).organization_id, org.pk)

    def test_e4_sel_02_claim_miss_falls_through_to_distinct_org_with_batch_one(self):
        first = self.inbound()
        for number in range(2, 8): self.inbound(number)
        _, healthy = self.other()
        actual = worker._claim_turn
        attempts = []
        def claim(conversation, now=None):
            attempts.append(conversation)
            return None if len(attempts) == 1 else actual(conversation, now)
        with patch.object(worker, '_claim_turn', side_effect=claim):
            self.assertEqual(self.run_poll(), 1)
        self.assertEqual(attempts, [first.conversation_id, healthy.conversation_id])
        self.assertEqual(TurnWork.objects.count(), 1)

    def test_e4_sel_03_busy_org_excluded_before_lookahead(self):
        first = durable.claim_turn(self.inbound().conversation_id)
        for number in range(2, 15): self.inbound(number)
        _, healthy = self.other()
        self.assertEqual(self.run_poll(), 1)
        self.assertIsNotNone(Message.objects.get(pk=healthy.pk).turn_work_id)
        durable.assert_witness(first)
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)

    def test_e4_sel_04_larger_batch_reselects_after_success_without_repeat_conversation(self):
        messages = [self.inbound(number) for number in range(1, 5)]
        self.assertEqual(self.run_poll(batch=3), 3)
        self.assertEqual(TurnWork.objects.filter(status=TurnWork.COMPLETED).count(), 3)
        self.assertEqual(Message.objects.filter(pk__in=[m.pk for m in messages],
            turn_work__isnull=True).count(), 1)

    def test_e4_sel_05_all_misses_are_bounded_and_leave_work_durable(self):
        self.inbound(); self.other(); self.other('C', 100); self.other('D', 101)
        with patch.object(worker, '_claim_turn', return_value=None) as claim:
            self.assertEqual(self.run_poll(), 0)
        self.assertEqual(claim.call_count, 3)
        self.assertEqual(TurnWork.objects.count(), 0)
        self.assertEqual(Message.objects.filter(direction='in', status='pending').count(), 4)

    def test_e4_sel_06_recovery_keeps_work_membership_and_changes_token(self):
        message = self.inbound()
        old = durable.claim_turn(message.conversation_id)
        self.h.retry_due(message.conversation)
        self.assertEqual(self.run_poll(), 1)
        message.refresh_from_db()
        work = TurnWork.objects.get(pk=old.turn_work_id)
        self.assertEqual(message.turn_work_id, work.pk)
        self.assertEqual(work.attempts, 2)
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertNotEqual(work.lease_token, old.lease_token)
        with self.assertRaises(durable.OwnershipLost): durable.finalize_turn(old)

    def test_e4_sel_07_future_retry_and_future_inbound_are_ineligible(self):
        message = self.inbound()
        Message.objects.filter(pk=message.pk).update(available_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.run_poll(), 0)
        Message.objects.filter(pk=message.pk).update(available_at=None)
        old = durable.claim_turn(message.conversation_id)
        durable.fail_turn(old)
        TurnWork.objects.filter(pk=old.turn_work_id).update(next_attempt_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.run_poll(), 0)
