"""B9 R04/R12: authoritative TurnWork capacity, not provider or rate quotas."""
import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from django.db import connection, transaction, DatabaseError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.agent import durable, llm_budget, worker
from apps.agent.metrics import compute_concurrency
from apps.agent.models import AgentSettings, Conversation, LLMCall, TurnWork, HumanHandoff
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from . import test_b9b_budget as b9b
from .b9a_harness import ApplicationHarness, answer, tool


class B9CConcurrencyTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp
    public_read = b9a.B9AE2ETests.public_read
    proposal = b9a.B9AE2ETests.proposal
    accept = b9a.B9AE2ETests.accept
    human_client = b9a.B9AE2ETests.human_client
    assert_pipeline = b9a.B9AE2ETests.assert_pipeline

    def inbound(self, number=1, harness=None):
        msg = (harness or self.h).inbound('Consulta sobre servicios',
                                        wa_id=f'521551234{number:04d}')
        Message.objects.filter(pk=msg.pk).update(available_at=None)
        return msg

    def observe(self):
        value = compute_concurrency(self.org)
        self.assertLessEqual(value['active'], value['limit'])
        return value

    def tearDown(self):
        if os.environ.get('B8E_RESULTS_PATH'):
            rows = [compute_concurrency(org) for org in b9a.Organization.objects.all()]
            data = {'test_id': self.id(), 'snapshots': rows, 'capacity': self.h.capacity,
                    'wire': [{k: e.get(k) for k in ('boundary', 'in_atomic',
                        'admission_observed', 'concurrency_active', 'concurrency_observed')}
                        for e in self.h.wire]}
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.b9c-corpus.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps(data) + '\n')
        super().tearDown()

    def test_scale_n_minus_one_n_n_plus_one_distinct_conversations(self):
        a, b = self.inbound(1), self.inbound(2)
        self.assertEqual(self.observe()['active'], 0)  # canonical N-1
        first = durable.claim_turn(a.conversation_id)
        self.assertEqual(self.observe()['active'], 1)  # canonical N
        self.assertIsNone(durable.claim_turn(b.conversation_id))  # N+1 denied
        b.refresh_from_db()
        self.assertIsNone(b.turn_work_id)
        self.assertEqual(b.status, 'pending')
        self.assertEqual(b.process_attempts, 0)
        self.assertEqual(LLMCall.objects.count(), 0)
        durable.finalize_turn(first)
        self.assertIsNotNone(durable.claim_turn(b.conversation_id))

    def test_saturation_durable_http_later_e2e_without_budget_consumption(self):
        first = durable.claim_turn(self.inbound(1).conversation_id)
        second = self.inbound(2)
        self.h.worker()
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertEqual(self.h.wire, [])
        durable.finalize_turn(first)
        self.h.llm.extend([tool('get_service_catalog'), answer()])
        self.h.worker(); self.h.sender()
        second.refresh_from_db()
        self.assertEqual(second.status, 'processed')
        self.assertEqual(Message.objects.get(direction='out').status, 'sent')
        self.assert_pipeline(second.conversation)
        self.assertEqual(self.observe()['active'], 0)

    def test_scale_01_noisy_backlog_cannot_hide_healthy_org_before_batch_limit(self):
        first = durable.claim_turn(self.inbound().conversation_id)
        for n in range(2, 14): self.inbound(n)
        org, channel, *_ = b9a.seed_domain('B')
        other = ApplicationHarness(channel)
        second = self.inbound(99, other)
        self.h.llm.append(answer())
        self.assertEqual(worker.process_pending_conversations(batch=1), 1)
        second.refresh_from_db()
        self.assertEqual(second.status, 'processed')
        durable.assert_witness(first)
        self.assertEqual(TurnWork.objects.get(pk=first.turn_work_id).llm_calls_admitted, 0)
        self.assertEqual(compute_concurrency(org)['active'], 0)

    def test_retry_releases_capacity_and_reacquisition_obeys_other_work(self):
        a, b = self.inbound(), self.inbound(2)
        first = durable.claim_turn(a.conversation_id)
        durable.fail_turn(first)
        self.assertEqual(self.observe()['active'], 0)
        second = durable.claim_turn(b.conversation_id)
        self.h.retry_due(a.conversation)
        self.assertIsNone(durable.claim_turn(a.conversation_id))
        durable.finalize_turn(second)
        new = durable.claim_turn(a.conversation_id)
        self.assertEqual(first.turn_work_id, new.turn_work_id)
        self.assertNotEqual(first.lease_token, new.lease_token)

    def test_expiry_old_worker_cannot_budget_publish_or_release_other_claim(self):
        a, b = self.inbound(), self.inbound(2)
        old = durable.claim_turn(a.conversation_id)
        self.h.retry_due(a.conversation)
        current = durable.claim_turn(b.conversation_id)
        with self.assertRaises(durable.OwnershipLost): durable.finalize_turn(old)
        with self.assertRaises(durable.OwnershipLost): durable.fail_turn(old)
        with self.assertRaises(durable.OwnershipLost): b9b.B9BBudgetTests.admit(self, old)
        durable.assert_witness(current)
        self.assertEqual(self.observe()['active'], 1)
        self.assertEqual(LLMCall.objects.count(), 0)

    def test_eligibility_clock_cannot_expire_live_capacity(self):
        first = durable.claim_turn(self.inbound().conversation_id)
        b = self.inbound(2)
        self.assertIsNone(durable.claim_turn(b.conversation_id,
            eligible_at=timezone.now() + timedelta(days=10)))
        durable.assert_witness(first)

    def test_duplicate_claim_preserves_token_attempts_and_membership(self):
        a = self.inbound()
        first = durable.claim_turn(a.conversation_id)
        for _ in range(3): self.assertIsNone(durable.claim_turn(a.conversation_id))
        work = TurnWork.objects.get()
        self.assertEqual(work.attempts, 1)
        self.assertEqual(work.lease_token, first.lease_token)
        self.assertEqual(Message.objects.get(pk=a.pk).turn_work_id, work.pk)

    def test_sql_failure_acquisition_or_recovery_rolls_back_capacity(self):
        a = self.inbound()
        def fail(execute, sql, params, many, context):
            if sql.startswith('UPDATE "agent_turnwork"'):
                return execute('SELECT 1/0', (), False, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(fail), self.assertRaises(DatabaseError):
            durable.claim_turn(a.conversation_id)
        self.assertEqual(TurnWork.objects.count(), 0)
        self.assertIsNone(Message.objects.get(pk=a.pk).turn_work_id)
        old = durable.claim_turn(a.conversation_id)
        self.h.retry_due(a.conversation)
        with connection.execute_wrapper(fail), self.assertRaises(DatabaseError):
            durable.claim_turn(a.conversation_id)
        self.assertEqual(TurnWork.objects.get().lease_token, old.lease_token)
        new = durable.claim_turn(a.conversation_id)
        self.assertNotEqual(new.lease_token, old.lease_token)

    def test_budget_exhausted_releases_turn_without_provider(self):
        b9b.B9BBudgetTests.test_bud_15_exhausted_produces_existing_deterministic_fallback(self)
        self.assertEqual(self.observe()['active'], 0)
        self.assertIsNotNone(durable.claim_turn(self.inbound(2).conversation_id))

    claim = b9b.B9BBudgetTests.claim
    admit = b9b.B9BBudgetTests.admit

    def test_provider_timeout_retry_keeps_budget_and_releases_only_at_completion(self):
        self.h.llm.extend([requests.Timeout('controlled'), answer()])
        self.inbound()
        counts = []
        self.h.callback = lambda boundary, event: counts.append(self.observe()['active']) if boundary == 'llm' else None
        self.h.worker()
        self.assertEqual(counts, [1, 1])
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 2)
        self.assertEqual(self.observe()['active'], 0)

    def test_takeover_without_quota_revokes_epoch_and_allows_other_conversation(self):
        a, b = self.inbound(), self.inbound(2)
        old = durable.claim_turn(a.conversation_id)
        client = self.human_client()
        result = client.post(f'/api/inbox/conversations/{a.conversation.public_id}/claim/')
        self.assertEqual(result.status_code, 200, result.content)
        with self.assertRaises(durable.OwnershipLost): durable.assert_witness(old)
        self.assertIsNotNone(durable.claim_turn(b.conversation_id))

    def test_scale_02_safety_http_and_sender_progress_while_org_saturated(self):
        old = durable.claim_turn(self.inbound().conversation_id)
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True):
            urgent = self.h.inbound('Mi perro está convulsionando ahora', wa_id='5215512348888')
            self.assertTrue(HumanHandoff.objects.filter(conversation=urgent.conversation).exists())
            self.h.meta.append(requests.Timeout('controlled'))
            self.h.sender(); self.h.sender()
        self.assertEqual(Message.objects.get(direction='out').status, 'uncertain')
        self.assertEqual(sum(e['boundary'] == 'meta' for e in self.h.wire), 1)
        self.assertEqual(LLMCall.objects.count(), 0)
        durable.assert_witness(old)

    def test_missing_settings_still_has_finite_release_limit(self):
        AgentSettings.objects.filter(organization=self.org).delete()
        a, b = self.inbound(), self.inbound(2)
        self.assertIsNotNone(durable.claim_turn(a.conversation_id))
        self.assertIsNone(durable.claim_turn(b.conversation_id))
        self.assertEqual(self.observe()['limit'], 1)

    def test_inline_safety_sql_failure_cannot_commit_second_processing_work(self):
        first = durable.claim_turn(self.inbound().conversation_id)
        def fail(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "agent_humanhandoff"'):
                return execute('SELECT 1/0', (), False, context)
            return execute(sql, params, many, context)
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True), connection.execute_wrapper(fail):
            # Receipt deliberately catches fast-path SQL errors, preserving the
            # inbound for the durable worker. Its nested transaction must roll
            # back every partial safety claim, not reject the webhook.
            urgent = self.h.inbound('Mi perro está convulsionando ahora', wa_id='5215512347777')
        urgent.refresh_from_db()
        self.assertEqual(urgent.status, 'pending')
        self.assertIsNone(urgent.turn_work_id)
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(HumanHandoff.objects.count(), 0)
        durable.assert_witness(first)
        self.assertEqual(self.observe()['active'], 1)

    def test_observability_readonly_tenant_scoped_and_closed_events(self):
        a, b = self.inbound(), self.inbound(2)
        with self.assertLogs('agent.events', level='INFO') as events:
            w = durable.claim_turn(a.conversation_id)
            self.assertIsNone(durable.claim_turn(b.conversation_id))
        names = [r.event for r in events.records]
        self.assertIn('AGENT_CONCURRENCY_ADMITTED', names)
        self.assertIn('AGENT_CONCURRENCY_SATURATED', names)
        for row in events.records:
            if row.event.startswith('AGENT_CONCURRENCY_'):
                self.assertFalse({'organization_id','conversation_id','turn_work_id','phone','prompt'} & row.__dict__.keys())
        before = list(TurnWork.objects.values())
        self.assertEqual(self.observe()['unassigned_inbound'], 1)
        org, *_ = b9a.seed_domain('B')
        self.assertEqual(compute_concurrency(org)['active'], 0)
        self.assertEqual(list(TurnWork.objects.values()), before)
        durable.assert_witness(w)

    def test_no_time_period_quota_immediate_next_work_after_completion(self):
        for n in range(1, 4):
            w = durable.claim_turn(self.inbound(n).conversation_id)
            self.assertIsNotNone(w)
            durable.finalize_turn(w)
        self.assertEqual(TurnWork.objects.filter(status='COMPLETED').count(), 3)

    def test_e2e_write_through_concurrency_consent_and_guard(self):
        b9a.B9AE2ETests.test_e2e_write_create_complete_pipeline(self)
        self.assertTrue(all(e.get('concurrency_observed') for e in self.h.wire if e['boundary'] == 'llm'))
        self.assertEqual(self.observe()['active'], 0)

    def test_closed_production_and_fixed_process_topology(self):
        b9b.B9BBudgetTests.test_bud_20_gates_closed(self)
        import re
        root = Path(__file__).resolve().parents[4]
        compose = (root/'docker-compose.prod.yml').read_text(encoding='utf-8')
        for name, mode in (('worker','planner'), ('sender','sender')):
            block = re.split(r'\n  (?=\w)', compose.split('\n  ' + name + ':\n', 1)[1], maxsplit=1)[0]
            command = json.loads(next(line.split('command:', 1)[1].strip()
                                     for line in block.splitlines() if 'command:' in line))
            if name == 'worker': self.assertIn('replicas: 2', block)
            self.assertEqual(command[command.index('--mode')+1], mode)
            self.assertEqual(command[command.index('--poll')+1], '1')
