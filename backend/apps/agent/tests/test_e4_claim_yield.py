"""E4-YIELD-01..09: one-poll advisory yield, with real PostgreSQL."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.agent import durable, worker
from apps.agent.models import LLMCall, TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a, test_b9c_concurrency as b9c
from .b9a_harness import ApplicationHarness


class E4ClaimYieldTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp
    inbound = b9c.B9CConcurrencyTests.inbound

    def pair(self, prior_healthy=False):
        org, channel, *_ = b9a.seed_domain('E4-YIELD-B')
        harness = ApplicationHarness(channel)
        if prior_healthy:
            old = self.inbound(99, harness)
            durable.finalize_turn(durable.claim_turn(old.conversation_id))
        old = self.inbound()
        durable.finalize_turn(durable.claim_turn(old.conversation_id))
        ready = self.inbound(2)
        future = self.inbound(100, harness)
        clock = timezone.now()
        Message.objects.filter(pk=future.pk).update(available_at=clock+timedelta(seconds=.5))
        return org, harness, ready, future, clock

    def test_e4_yield_01_yields_to_idle_less_recent_org_without_claim_or_budget(self):
        _, _, ready, future, clock = self.pair(prior_healthy=True)
        before = list(TurnWork.objects.values('id', 'attempts', 'llm_calls_admitted'))
        self.assertEqual(worker.process_pending_conversations(batch=1, now=clock), 0)
        self.assertEqual(list(TurnWork.objects.values('id', 'attempts', 'llm_calls_admitted')), before)
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertFalse(Message.objects.filter(pk__in=[ready.pk, future.pk], turn_work__isnull=False).exists())

    def test_e4_yield_02_deadline_due_restores_original_recency_and_batch_one(self):
        _, _, ready, future, clock = self.pair()
        due = clock+timedelta(seconds=.5)
        self.assertEqual(list(worker._pending_conversation_candidates(due)),
                         [future.conversation_id, ready.conversation_id])
        with patch.object(worker, '_run_turn', side_effect=durable.finalize_turn):
            self.assertEqual(worker.process_pending_conversations(batch=1, now=due), 1)
        self.assertIsNotNone(Message.objects.get(pk=future.pk).turn_work_id)
        self.assertIsNone(Message.objects.get(pk=ready.pk).turn_work_id)

    def test_e4_yield_03_far_future_does_not_delay_eligible_org(self):
        _, _, ready, future, clock = self.pair()
        Message.objects.filter(pk=future.pk).update(available_at=clock+timedelta(seconds=1.001))
        self.assertEqual(list(worker._pending_conversation_candidates(clock)), [ready.conversation_id])

    def test_e4_yield_04_busy_upcoming_org_does_not_reserve_capacity(self):
        org, harness, ready, future, clock = self.pair()
        busy = durable.claim_turn(self.inbound(101, harness).conversation_id)
        self.assertEqual(list(worker._pending_conversation_candidates(clock)), [ready.conversation_id])
        self.assertEqual(durable.active_org_work(org.pk).count(), 1)
        durable.assert_witness(busy)

    def test_e4_yield_05_never_claimed_org_keeps_original_priority(self):
        _, _, ready, future, clock = self.pair()
        org, channel, *_ = b9a.seed_domain('E4-YIELD-C')
        fresh = self.inbound(102, ApplicationHarness(channel))
        self.assertEqual(list(worker._pending_conversation_candidates(clock)), [fresh.conversation_id])
        self.assertEqual(durable.active_org_work(org.pk).count(), 0)

    def test_e4_yield_06_more_recent_upcoming_org_does_not_delay_older_org(self):
        _, harness, ready, future, clock = self.pair()
        newer = self.inbound(101, harness)
        durable.finalize_turn(durable.claim_turn(newer.conversation_id))
        self.assertEqual(list(worker._pending_conversation_candidates(clock)), [ready.conversation_id])

    def test_e4_yield_07_ready_join_stays_monotonic_while_selection_yields(self):
        _, _, ready, _, clock = self.pair()
        deadline = clock-timedelta(seconds=1)
        Message.objects.filter(pk=ready.pk).update(available_at=deadline)
        joined = self.h.inbound('Otra consulta', wa_id='5215512340002')
        ready.refresh_from_db(); joined.refresh_from_db()
        self.assertEqual(ready.available_at, deadline)
        self.assertEqual(joined.available_at, deadline)
        self.assertEqual(worker.process_pending_conversations(batch=1, now=clock), 0)
        ready.refresh_from_db(); joined.refresh_from_db()
        self.assertEqual(ready.available_at, deadline)
        self.assertEqual(joined.available_at, deadline)
        self.assertIsNone(ready.turn_work_id)
        self.assertIsNone(joined.turn_work_id)
        self.assertEqual(LLMCall.objects.count(), 0)

    @override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
    def test_e4_yield_08_safety_bypasses_forecast_and_occupied_org(self):
        _, _, ready, _, clock = self.pair()
        self.assertEqual(worker.process_pending_conversations(batch=1, now=clock), 0)
        busy = durable.claim_turn(ready.conversation_id)
        signal = self.h.inbound('Mi perro está convulsionando ahora', wa_id='5215512340103')
        self.assertEqual(signal.semantic_type, Message.SEMANTIC_SAFETY_SIGNAL)
        self.assertTrue(Message.objects.filter(organization=self.org,
            semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE).exists())
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        self.assertEqual(LLMCall.objects.count(), 0)
        durable.assert_witness(busy)

    @override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
    def test_e4_yield_09_pending_safety_after_live_worker_is_not_withheld(self):
        _, _, ready, future, _ = self.pair()
        busy = durable.claim_turn(ready.conversation_id)
        signal = self.h.inbound('Mi perro está convulsionando ahora', wa_id='5215512340002')
        self.assertEqual(signal.semantic_type, Message.SEMANTIC_SAFETY_SIGNAL)
        self.assertIsNone(signal.turn_work_id)
        self.assertEqual(durable.finalize_turn(busy), 'deferred_to_new_input')
        clock = timezone.now()
        Message.objects.filter(pk=future.pk).update(available_at=clock+timedelta(seconds=.5))
        self.assertEqual(list(worker._pending_conversation_candidates(clock)), [ready.conversation_id])
        self.assertEqual(LLMCall.objects.count(), 0)
