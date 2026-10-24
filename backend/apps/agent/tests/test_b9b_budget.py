"""B9 budget component: real PG commits and application wire, no billing."""
import io
import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction, IntegrityError, DatabaseError
from django.test import TransactionTestCase
from django.utils import timezone

from apps.agent import durable, llm_budget, operation_authorization
from apps.agent.llm import LLMResult, LLMError, OpenAICompatibleClient
from apps.agent.models import LLMCall, TurnWork, Conversation
from apps.agent.turn_changes import TurnChanges
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
seed_domain = b9a.seed_domain
from .b9a_harness import answer, tool, ApplicationHarness


class B9BBudgetTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp

    def tearDown(self):
        import os
        from pathlib import Path
        if os.environ.get('B8E_RESULTS_PATH'):
            works = list(TurnWork.objects.values('llm_calls_admitted', 'llm_call_limit',
                'llm_output_tokens_reserved', 'llm_output_token_limit'))
            data = {'test_id': self.id(), 'works': works,
                'calls': list(LLMCall.objects.values('purpose', 'input_tokens', 'output_tokens',
                    'cost_estimate', 'reserved_output_tokens', 'error')),
                'wire_calls': sum(e['boundary'] == 'llm' for e in self.h.wire),
                'llm_calls_without_admission': sum(e['boundary'] == 'llm' and
                    not e.get('admission_observed', False) for e in self.h.wire),
                'admissions_over_budget': sum(w['llm_calls_admitted'] is not None and
                    w['llm_calls_admitted'] > w['llm_call_limit'] for w in works)}
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.b9b-corpus.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps(data, default=str) + '\n')
        super().tearDown()

    def claim(self, limit=2):
        msg = self.h.inbound('Necesito información de servicios')
        Message.objects.filter(pk=msg.pk).update(available_at=None)
        witness = durable.claim_turn(msg.conversation_id)
        TurnWork.objects.filter(pk=witness.turn_work_id).update(llm_call_limit=limit)
        self.conv = msg.conversation
        return witness

    def admit(self, witness, key=None, **kwargs):
        return llm_budget.admit(witness, admission_id=key or uuid4(), purpose='planner',
            max_tokens=600, model_id='b9a-planner', prompt_version='test', **kwargs)

    def call(self, witness, client=None):
        with TurnChanges(witness, self.conv).activate():
            return llm_budget.complete(self.conv, client or OpenAICompatibleClient(),
                purpose='planner', prompt_version='test', system='test', messages=[])

    def test_bud_01_02_03_available_last_slot_and_exhausted(self):
        w = self.claim(1)
        self.assertTrue(self.admit(w)[1])
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w)
        work = TurnWork.objects.get(pk=w.turn_work_id)
        self.assertEqual((work.llm_calls_admitted, work.llm_output_tokens_reserved), (1, 600))
        self.assertEqual(LLMCall.objects.count(), 1)

    def test_bud_04_09_admission_survives_later_rollback(self):
        w = self.claim(1); call, _ = self.admit(w)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                durable.finalize_turn(w, outputs=[{'body': 'test'}])
                raise IntegrityError('controlled rollback')
        self.assertTrue(LLMCall.objects.filter(pk=call.pk).exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w)

    def test_bud_05_stale_token_epoch_lease_tenant_and_work(self):
        w = self.claim()
        for forged in (replace(w, lease_token=uuid4()), replace(w, ownership_epoch=999),
                       replace(w, organization_id=999999), replace(w, turn_work_id=999999)):
            with self.assertRaises(durable.OwnershipLost): self.admit(forged)
        TurnWork.objects.filter(pk=w.turn_work_id).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(durable.OwnershipLost): self.admit(w)
        self.assertEqual(LLMCall.objects.count(), 0)

    def test_bud_06_duplicate_admission_is_observation_not_new_dispatch(self):
        w = self.claim(1); key = uuid4()
        a, fresh = self.admit(w, key); b, replay = self.admit(w, key)
        self.assertTrue(fresh); self.assertFalse(replay); self.assertEqual(a.pk, b.pk)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 1)

    def test_bud_07_12_timeout_retry_counted_without_refund(self):
        self.h.llm.extend([requests.Timeout('controlled'), answer()])
        self.h.inbound('Necesito información de servicios'); self.h.worker()
        calls = list(LLMCall.objects.order_by('pk'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].retry_of_id, calls[0].pk)
        self.assertIsNone(calls[0].input_tokens)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 2)
        self.assertEqual(calls[1].input_tokens, 20)

    def test_bud_08_restart_does_not_restore_slot(self):
        w = self.claim(1); self.admit(w)
        self.h.retry_due(self.conv)
        new = durable.claim_turn(self.conv.pk)
        self.assertNotEqual(new.lease_token, w.lease_token)
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(new)

    def test_bud_10_13_success_usage_and_no_locks_at_wire(self):
        w = self.claim(); self.h.llm.append(answer())
        def at_wire(boundary, event):
            if boundary == 'llm':
                self.assertFalse(connection.in_atomic_block)
                self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 1)
                self.assertIsNotNone(LLMCall.objects.get().admitted_at)
        self.h.callback = at_wire
        self.call(w)
        call = LLMCall.objects.get()
        self.assertEqual((call.input_tokens, call.output_tokens), (20, 10))
        self.assertIsNone(call.cost_estimate)
        self.assertIsNotNone(call.recorded_at)

    def test_bud_11_provider_error_preserves_admission(self):
        from .b9a_harness import response
        w = self.claim(1); self.h.llm.append(response({}, status=503))
        with self.assertRaises(LLMError): self.call(w)
        self.assertEqual(LLMCall.objects.get().error, 'provider_error')
        with self.assertRaises(llm_budget.BudgetRejected): self.call(w)
        self.assertEqual(len(self.h.wire), 1)

    def test_bud_14_missing_and_malformed_usage_are_unknown(self):
        w = self.claim(3)
        for usage in (None, {'prompt_tokens': -1, 'completion_tokens': True}, 'bad'):
            payload = answer(); payload['usage'] = usage; self.h.llm.append(payload)
            self.call(w)
        self.assertTrue(all(c.input_tokens is None and c.output_tokens is None for c in LLMCall.objects.all()))
        self.assertEqual(TurnWork.objects.get().llm_output_tokens_reserved, 1800)

    def test_bud_15_exhausted_produces_existing_deterministic_fallback(self):
        w = self.claim(1); self.admit(w)
        from apps.agent.worker import _run_turn
        _run_turn(w); self.h.sender()
        self.assertFalse(any(e['boundary'] == 'llm' for e in self.h.wire))
        self.assertEqual(Message.objects.get(direction='out').status, 'sent')

    def test_bud_16_17_tenant_and_turn_isolation_inspector(self):
        w = self.claim(1); self.admit(w)
        org, channel, *_ = seed_domain('B')
        other = ApplicationHarness(channel)
        msg = other.inbound('Consulta independiente')
        Message.objects.filter(pk=msg.pk).update(available_at=None)
        other_w = durable.claim_turn(msg.conversation_id)
        self.assertTrue(self.admit(other_w)[1])
        with self.assertRaises(TurnWork.DoesNotExist):
            llm_budget.inspect_turn(organization_id=org.pk, turn_work_id=w.turn_work_id)
        data = llm_budget.inspect_turn(organization_id=self.org.pk, turn_work_id=w.turn_work_id)
        self.assertEqual(data['calls_remaining'], 0)
        self.assertEqual(data['usage_unavailable'], 1)
        output = io.StringIO()
        call_command('agent_inspect_llm_budget', organization_id=self.org.pk,
            turn_work_id=w.turn_work_id, stdout=output)
        self.assertEqual(json.loads(output.getvalue())['calls_admitted'], 1)
        with self.assertRaises(CommandError):
            call_command('agent_inspect_llm_budget', organization_id=org.pk,
                turn_work_id=w.turn_work_id, stdout=io.StringIO())

    def test_bud_18_e2e_read_has_accounting_before_sender(self):
        self.h.llm.extend([tool('get_service_catalog'), answer()])
        self.h.inbound('¿Qué servicios ofrecen?'); self.h.worker(); self.h.sender()
        work = TurnWork.objects.get()
        self.assertEqual(work.llm_calls_admitted, 2)
        self.assertEqual(work.llm_calls.filter(recorded_at__isnull=False).count(), 2)
        self.assertEqual(Message.objects.get(direction='out').status, 'sent')
        self.assertTrue(all(not e['in_atomic'] for e in self.h.wire))

    def test_bud_19_write_preserves_guard_with_accounting(self):
        for method in ('proposal', 'human_client'):
            setattr(self, method, getattr(b9a.B9AE2ETests, method).__get__(self))
        b9a.B9AE2ETests.test_worker_reaches_b8a_and_denies_inactive_definition(self)
        self.assertGreater(LLMCall.objects.filter(admission_id__isnull=False).count(), 0)

    def test_bud_20_gates_closed(self):
        from django.conf import settings
        from apps.agent.intake import CONTAINED_WRITES
        self.assertFalse(settings.AGENT_B7B_CONSENT_ENABLED)
        self.assertEqual(settings.AGENT_OPERATION_EXECUTION_ENABLED, {})
        self.assertTrue(CONTAINED_WRITES)

    def test_fi_01_10_sql_failure_before_commit_does_not_consume(self):
        w = self.claim()
        def fail(execute, sql, params, many, context):
            if sql.startswith('UPDATE "agent_turnwork"'):
                return execute('SELECT 1/0', (), False, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(fail), self.assertRaises(DatabaseError): self.admit(w)
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 0)

    def test_fi_10_sql_failure_after_provider_retains_unknown(self):
        w = self.claim(1); self.h.llm.append(answer())
        def fail(execute, sql, params, many, context):
            if sql.startswith('UPDATE "agent_llmcall"'):
                return execute('SELECT 1/0', (), False, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(fail), self.assertRaises(DatabaseError): self.call(w)
        self.assertIsNone(LLMCall.objects.get().recorded_at)
        with self.assertRaises(llm_budget.BudgetRejected): self.call(w)

    def test_nested_application_transaction_is_rejected_before_dispatch(self):
        w = self.claim()
        with transaction.atomic(), self.assertRaises(RuntimeError): self.call(w)
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertEqual(self.h.wire, [])

    def test_token_limit_unknown_legacy_and_constraints(self):
        w = self.claim()
        TurnWork.objects.filter(pk=w.turn_work_id).update(llm_output_token_limit=599)
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w)
        TurnWork.objects.filter(pk=w.turn_work_id).update(llm_calls_admitted=None)
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TurnWork.objects.filter(pk=w.turn_work_id).update(llm_calls_admitted=3)

    def test_input_limit_rejects_before_provider_and_admission(self):
        w = self.claim()
        with TurnChanges(w, self.conv).activate(), self.assertRaises(llm_budget.BudgetRejected):
            llm_budget.complete(self.conv, OpenAICompatibleClient(), purpose='planner',
                prompt_version='test', system='x' * 65537, messages=[])
        self.assertEqual(LLMCall.objects.count(), 0)

    def test_cost_01_authorizer_verifier_planner_share_budget(self):
        w = self.claim(3)
        self.h.llm.extend([tool('assess_operation'), tool('verify_operation'), answer()])
        # Use the real role call sites; their schema validation is independent.
        with TurnChanges(w, self.conv).activate():
            for fn, args in ((operation_authorization._classify, ['{}', ['CREATE_APPOINTMENT']]),
                             (operation_authorization._verify, ['{}', 'CREATE_APPOINTMENT'])):
                try: fn(self.conv, OpenAICompatibleClient(), *args)
                except LLMError: pass
            self.call(w)
        self.assertEqual(list(LLMCall.objects.order_by('id').values_list('purpose', flat=True)),
            ['operation_authorizer', 'operation_verifier', 'planner'])
        self.assertEqual(TurnWork.objects.get().llm_output_tokens_reserved, 880)
        with self.assertRaises(llm_budget.BudgetRejected): self.call(w)

    def test_duplicate_record_does_not_overwrite_observed_usage(self):
        w = self.claim(); call, _ = self.admit(w)
        llm_budget.record(call, result=LLMResult(kind='text', input_tokens=20, output_tokens=10))
        llm_budget.record(call, result=LLMResult(kind='text', input_tokens=999, output_tokens=999))
        self.assertEqual(LLMCall.objects.get().input_tokens, 20)

    def test_malformed_tool_keeps_provider_usage(self):
        w = self.claim(); payload = answer()
        payload['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{'
        self.h.llm.append(payload)
        with self.assertRaises(LLMError): self.call(w)
        self.assertEqual(LLMCall.objects.get().input_tokens, 20)

    def test_cost_metrics_do_not_coalesce_unknown_or_leak_tenants(self):
        from apps.agent.metrics import compute_llm_usage
        w = self.claim(); self.h.llm.append(answer()); self.call(w)
        self.admit(w)
        data = compute_llm_usage(self.org, turn_work_id=w.turn_work_id)
        self.assertEqual((data['calls'], data['unknown_usage_calls']), (2, 1))
        self.assertIsNone(data['input_tokens'])
        self.assertEqual(data['known_input_tokens'], 20)
        org, *_ = seed_domain('B')
        self.assertEqual(compute_llm_usage(org)['calls'], 0)

    def test_same_tenant_new_work_has_independent_budget(self):
        w = self.claim(1); self.admit(w)
        durable.finalize_turn(w)
        msg = self.h.inbound('Otra consulta de servicios')
        Message.objects.filter(pk=msg.pk).update(available_at=None)
        newer = durable.claim_turn(msg.conversation_id)
        self.assertNotEqual(w.turn_work_id, newer.turn_work_id)
        self.assertTrue(self.admit(newer)[1])
        self.assertEqual(TurnWork.objects.get(pk=w.turn_work_id).llm_calls_admitted, 1)
        self.assertEqual(TurnWork.objects.get(pk=newer.turn_work_id).llm_calls_admitted, 1)

    def test_accounting_does_not_duplicate_conversation_content(self):
        w = self.claim(); self.h.llm.append(answer('contenido confidencial de prueba'))
        self.call(w)
        row = LLMCall.objects.values().get()
        self.assertNotIn('contenido confidencial', str(row))
        self.assertNotIn('Necesito información', str(row))
        self.assertFalse({'prompt', 'response', 'phone', 'tool_args'} & set(row))

    def test_invalid_admission_and_retry_scope_do_not_consume(self):
        w = self.claim(); before = LLMCall.objects.count()
        for tokens in (0, -1, 601, True, None):
            with self.assertRaises(llm_budget.BudgetRejected):
                llm_budget.admit(w, admission_id=uuid4(), purpose='planner', max_tokens=tokens,
                    model_id='controlled', prompt_version='test')
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w, retry_of=999999)
        self.assertEqual(LLMCall.objects.count(), before)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 0)

    def test_provider_explicit_zero_is_known_zero(self):
        w = self.claim(); payload = answer()
        payload['usage'] = {'prompt_tokens': 0, 'completion_tokens': 0}
        self.h.llm.append(payload); self.call(w)
        row = LLMCall.objects.get()
        self.assertEqual((row.input_tokens, row.output_tokens), (0, 0))
        self.assertIsNone(row.cost_estimate)

    def test_legacy_migration_keeps_counters_unknown_and_new_defaults_zero(self):
        from django.db.migrations.executor import MigrationExecutor
        w = self.claim()
        legacy = LLMCall.objects.create(organization=self.org, conversation=self.conv,
            model_id='historic', input_tokens=13, output_tokens=7, cost_estimate=0)
        before = [('agent', '0027_attendance_consent_policy')]
        after = [('agent', '0028_b9_operational_budget')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        try:
            executor.migrate(before)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
        finally:
            MigrationExecutor(connection).migrate(latest)
        work = TurnWork.objects.get(pk=w.turn_work_id)
        self.assertIsNone(work.llm_calls_admitted)
        self.assertIsNone(work.llm_output_tokens_reserved)
        legacy.refresh_from_db()
        self.assertEqual((legacy.input_tokens, legacy.output_tokens), (13, 7))
        self.assertIsNone(legacy.admission_id)
        self.assertIsNone(legacy.turn_work_id)
        with self.assertRaises(llm_budget.BudgetRejected): self.admit(w)
        self.assertEqual(TurnWork().llm_calls_admitted, 0)
        self.assertEqual(TurnWork().llm_output_tokens_reserved, 0)
