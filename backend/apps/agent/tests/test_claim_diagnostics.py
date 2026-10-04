"""Causal instrumentation coverage/equivalence, not PROFILE acceptance."""
import io
import json
import re
import tempfile
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.agent import claim_diagnostics as trace, durable, worker
from apps.agent.claim_diagnostic_report import read_journal, reconstruct
from apps.agent.models import Conversation, TurnWork, LLMCall
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from .b9a_harness import answer
from .claim_diagnostic_evidence import save, save_equivalence


class ClaimDiagnosticTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp

    def path(self):
        folder = tempfile.TemporaryDirectory(prefix='e4-causal-test-')
        self.addCleanup(folder.cleanup)
        return Path(folder.name) / 'trace.jsonl'

    def ready(self):
        message = self.h.inbound('Consulta sintética privada TRACE_PRIVATE_PAYLOAD')
        Message.objects.filter(pk=message.pk).update(available_at=durable.db_now()-timedelta(seconds=1))
        return message

    def snapshot(self):
        return dict(
            works=list(TurnWork.objects.order_by('pk').values('id', 'organization_id',
                'conversation_id', 'anchor_message_id', 'cursor_message_id', 'status',
                'lease_token', 'lease_expires_at', 'ownership_epoch', 'attempts', 'claimed_at',
                'next_attempt_at', 'llm_calls_admitted', 'llm_output_tokens_reserved')),
            messages=list(Message.objects.order_by('pk').values('id', 'turn_work_id',
                'status', 'process_attempts', 'available_at')),
            conversations=list(Conversation.objects.order_by('pk').values('id',
                'ownership_epoch', 'processing_until')),
            admissions=LLMCall.objects.count())

    def test_01_complete_phases_and_private_data_never_serialized(self):
        path = self.path()
        with trace.capture(path, run_id='coverage', worker='planner-1'):
            message = self.h.inbound('TRACE_PRIVATE_PAYLOAD')
            # This test controls eligibility without sleeping eight seconds.
            Message.objects.filter(pk=message.pk).update(available_at=durable.db_now()-timedelta(seconds=1))
            with patch.object(worker, '_run_turn', side_effect=durable.finalize_turn):
                self.assertEqual(worker.process_pending_conversations(batch=1), 1)
        rows = read_journal(path)
        events = {row['event'] for row in rows}
        self.assertTrue({'message_persisted', 'deadline_set', 'poll_start', 'selection_start',
            'selection_result', 'selection_end', 'claim_start', 'claim_locked_start', 'sql_start',
            'sql_end', 'db_clock', 'membership_candidate', 'claim_bound', 'claim_result',
            'commit_start', 'commit_end', 'poll_end', 'capture_end'} <= events)
        report = reconstruct([rows])['claims'][0]
        message.refresh_from_db()
        self.assertEqual(report['turn_work_id'], message.turn_work_id)
        self.assertEqual(report['status'], 'committed')
        self.assertEqual(report['organization_id'], self.org.pk)
        self.assertEqual(report['conversation_id'], message.conversation_id)
        self.assertEqual(report['membership'][0]['message_id'], message.pk)
        self.assertEqual(len(report['claim_sql']), report['query_count'])
        self.assertEqual(len(report['selection_sql']), 1)
        self.assertGreater(report['selection_duration_ns'], 0)
        self.assertGreaterEqual(report['selection_end_to_claim_start_ns'], 0)
        self.assertEqual(report['backend_pid'], connection.connection.info.backend_pid)
        text = path.read_text()
        for forbidden in ('TRACE_PRIVATE_PAYLOAD', '5512345678', 'params', 'SELECT ', 'INSERT INTO',
                          str(TurnWork.objects.get(pk=message.turn_work_id).lease_token)):
            self.assertNotIn(forbidden, text)
        metrics = report['message_timelines'][0]
        self.assertGreaterEqual(metrics['persisted_to_eligible_seconds'], 0)
        lo, hi = metrics['eligible_to_selection_seconds_bounds']
        self.assertLessEqual(lo, hi)
        save('coverage', [rows], reconstruct([rows]))

    def test_02_on_off_identical_sql_and_durable_state_new_retry_and_reclaim(self):
        message = self.ready()
        for mode in ('new', 'retry', 'reclaim', 'busy', 'not_due'):
            with self.subTest(mode=mode):
                if mode == 'retry':
                    witness = durable.claim_turn(message.conversation_id)
                    durable.fail_turn(witness)
                    TurnWork.objects.filter(pk=witness.turn_work_id).update(next_attempt_at=None,
                        llm_calls_admitted=2, llm_output_tokens_reserved=1200)
                elif mode == 'reclaim':
                    TurnWork.objects.update(status=TurnWork.PROCESSING,
                        lease_expires_at=durable.db_now()-timedelta(seconds=1))
                elif mode == 'busy':
                    TurnWork.objects.update(status=TurnWork.PROCESSING,
                        lease_expires_at=durable.db_now()+timedelta(minutes=10))
                elif mode == 'not_due':
                    TurnWork.objects.update(status=TurnWork.PENDING,
                        next_attempt_at=durable.db_now()+timedelta(minutes=10))
                fixed = durable.db_now()
                original_clock = durable.db_now
                def clock():
                    original_clock()  # Keep the real SELECT in both executions.
                    return fixed
                outputs = []
                for enabled in (False, True):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT setval(pg_get_serial_sequence('agent_turnwork','id'),900000)")
                    statements = []
                    def record(execute, sql, params, many, context):
                        # Auto-generated created_at differs between runs. Claims'
                        # authority clocks/leases are asserted exactly in snapshot.
                        normalized = tuple('<datetime>' if isinstance(p, datetime) else p for p in (params or ()))
                        # Savepoint labels are generated by Django's per-thread
                        # counter; compare their operation/order, not serials.
                        sql = re.sub(r'"s[0-9]+_x[0-9]+"', '"savepoint"', sql)
                        statements.append((sql, normalized, many))
                        return execute(sql, params, many, context)
                    with (trace.capture(self.path(), run_id='equivalence', worker='planner-1')
                          if enabled else nullcontext()):
                        with transaction.atomic(), patch.object(durable, 'db_now', side_effect=clock), \
                                patch.object(durable, 'uuid4', return_value=UUID(int=1234)):
                            with connection.execute_wrapper(record):
                                selected = list(worker._pending_conversation_candidates(fixed))
                                witness = durable.claim_turn(message.conversation_id)
                            state = self.snapshot()
                            outputs.append((selected, witness, statements, state))
                            transaction.set_rollback(True)
                self.assertEqual(outputs[0][0], outputs[1][0])
                self.assertEqual(outputs[0][1], outputs[1][1])
                self.assertEqual(len(outputs[0][2]), len(outputs[1][2]))
                for ordinal, (off, on) in enumerate(zip(outputs[0][2], outputs[1][2])):
                    self.assertTrue(off == on,
                        f'SQL/params differ at ordinal {ordinal}; sql_equal={off[0] == on[0]}, params_equal={off[1] == on[1]}')
                self.assertEqual(outputs[0][3], outputs[1][3])

    def test_03_outer_rollback_and_savepoint_rollback_are_not_commits(self):
        message = self.ready()
        comparisons = []
        for nested in (False, True):
            outputs = []
            for enabled in (False, True):
                path = self.path()
                statements = []
                def record(execute, sql, params, many, context):
                    statements.append(re.sub(r'"s[0-9]+_x[0-9]+"', '"savepoint"', sql))
                    return execute(sql, params, many, context)
                with (trace.capture(path, run_id='rollback', worker='planner-1')
                      if enabled else nullcontext()), connection.execute_wrapper(record):
                    with transaction.atomic():
                        if nested:
                            with transaction.atomic():
                                self.assertIsNotNone(durable.claim_turn(message.conversation_id))
                                transaction.set_rollback(True)
                        else:
                            self.assertIsNotNone(durable.claim_turn(message.conversation_id))
                            transaction.set_rollback(True)
                self.assertFalse(TurnWork.objects.exists())
                outputs.append((statements, self.snapshot()))
                if enabled:
                    rows = read_journal(path)
                    self.assertEqual(reconstruct([rows])['claims'][0]['status'], 'rolled_back')
            self.assertEqual(outputs[0], outputs[1])
            comparisons.append(dict(savepoint=nested, equal=True, query_count=len(outputs[0][0])))
        save_equivalence('rollback', [comparisons, comparisons])

    def test_04_sql_error_preserves_exception_and_pairs_events(self):
        message = self.ready()
        path = self.path()
        def fail(execute, sql, params, many, context):
            if sql.startswith('UPDATE "agent_turnwork"'):
                raise RuntimeError('TRACE_PRIVATE_ERROR')
            return execute(sql, params, many, context)
        with trace.capture(path, run_id='error', worker='planner-1'), connection.execute_wrapper(fail):
            with self.assertRaisesRegex(RuntimeError, 'TRACE_PRIVATE_ERROR'):
                durable.claim_turn(message.conversation_id)
        rows = read_journal(path)
        self.assertTrue(any(r['event'] == 'sql_end' and r['error_class'] == 'RuntimeError' for r in rows))
        self.assertIn('rollback_end', {r['event'] for r in rows})
        self.assertNotIn('TRACE_PRIVATE_ERROR', path.read_text())
        self.assertFalse(TurnWork.objects.exists())

    @override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
    def test_05_safety_primitive_is_bound_to_outer_ingress_commit(self):
        path = self.path()
        with trace.capture(path, run_id='safety', worker='ingress'):
            message = self.h.inbound('Mi perro está convulsionando ahora')
        rows = read_journal(path)
        claims = reconstruct([rows])['claims']
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]['status'], 'committed')
        self.assertEqual(claims[0]['turn_work_id'], message.turn_work_id)
        self.assertIsNone(claims[0]['selection_duration_ns'])
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertEqual(TurnWork.objects.get(pk=message.turn_work_id).status, TurnWork.COMPLETED)

    def test_12_reconnect_and_on_off_ready_join_do_not_change_deadline_or_membership(self):
        message = self.ready()
        message.refresh_from_db()
        from apps.agent import services
        outputs = []
        for enabled in (False, True):
            path = self.path()
            connection.close()
            with (trace.capture(path, run_id='ready-join', worker='ingress') if enabled else nullcontext()):
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT setval(pg_get_serial_sequence('channels_message','id'),910000)")
                    cursor.execute("SELECT setval(pg_get_serial_sequence('agent_turnwork','id'),910000)")
                statements = []
                def record(execute, sql, params, many, context):
                    statements.append(re.sub(r'"s[0-9]+_x[0-9]+"', '"savepoint"', sql))
                    return execute(sql, params, many, context)
                fixed = message.available_at+timedelta(seconds=2)
                with transaction.atomic(), patch.object(durable, 'uuid4', return_value=UUID(int=77)), \
                        patch.object(services, 'db_now', return_value=fixed), \
                        patch.object(durable, 'db_now', return_value=fixed):
                    with connection.execute_wrapper(record):
                        joined = self.h.inbound('Corrección sintética')
                        witness = durable.claim_turn(message.conversation_id)
                    self.assertIsNotNone(witness)
                    joined.refresh_from_db()
                    self.assertEqual(joined.available_at, message.available_at)
                    self.assertEqual(joined.turn_work_id, witness.turn_work_id)
                    outputs.append((statements, self.snapshot(), witness))
                    transaction.set_rollback(True)
            if enabled:
                rows = read_journal(path)
                events = [r['event'] for r in rows]
                self.assertIn('connection_open_start', events)
                self.assertIn('connection_open_end', events)
        self.assertEqual(outputs[0], outputs[1])

    def test_06_sink_failure_does_not_change_claim_and_reader_rejects_evidence(self):
        message = self.ready()
        path = self.path()
        class Broken(io.StringIO):
            def write(self, value):
                raise OSError('sink unavailable')
        with trace.capture(path, run_id='sink', worker='planner-1') as journal:
            stream = journal.stream
            journal.stream = Broken()
            witness = durable.claim_turn(message.conversation_id)
            journal.stream = stream
            self.assertGreater(journal.failed_writes, 0)
        self.assertIsNotNone(witness)
        durable.assert_witness(witness)
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE'):
            read_journal(path)

    def test_07_reader_rejects_missing_reordered_and_truncated_events(self):
        message = self.ready()
        path = self.path()
        with trace.capture(path, run_id='integrity', worker='planner-1'):
            durable.claim_turn(message.conversation_id)
        lines = path.read_text().splitlines()
        for altered in (lines[:-1], lines[:2]+lines[3:], [lines[0], lines[2], lines[1]]+lines[3:]):
            broken = self.path()
            broken.write_text('\n'.join(altered)+'\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_journal(broken)

    def test_08_separate_preselection_delay_from_short_sql_without_sleep(self):
        message = self.ready()
        path = self.path()
        counter = 10**15
        def tick():
            nonlocal counter
            counter += 1000
            return counter
        original = worker._pending_conversation_candidates
        def delayed(*args):
            nonlocal counter
            counter += 1_900_000_000
            return original(*args)
        def sql_delay(execute, sql, params, many, context):
            nonlocal counter
            if 'ROW_NUMBER()' in sql:
                counter += 80_000_000
            return execute(sql, params, many, context)
        with patch.object(trace.time, 'perf_counter_ns', side_effect=tick), \
                trace.capture(path, run_id='clock-fixture', worker='planner-1'), \
                connection.execute_wrapper(sql_delay), \
                patch.object(worker, '_pending_conversation_candidates', side_effect=delayed), \
                patch.object(worker, '_run_turn', side_effect=durable.finalize_turn):
            worker.process_pending_conversations(batch=1)
        report = reconstruct([read_journal(path)])['claims'][0]
        self.assertGreater(report['selection_duration_ns'], 1_980_000_000)
        self.assertLess(report['selection_sql'][0]['duration_ns'], 81_000_000)
        self.assertGreaterEqual(report['selection_sql'][0]['duration_ns'], 80_000_000)

    def test_09_failed_commit_is_not_reported_as_committed(self):
        from django.db import DatabaseError
        message = self.ready()
        path = self.path()
        def broken_commit():
            raise DatabaseError('PRIVATE_COMMIT_ERROR')
        # Patch beneath the observer so the commit error is actually observed.
        with patch.object(connection, '_commit', side_effect=broken_commit):
            with trace.capture(path, run_id='commit-error', worker='planner-1'):
                with self.assertRaises(DatabaseError):
                    durable.claim_turn(message.conversation_id)
        rows = read_journal(path)
        self.assertEqual(reconstruct([rows])['claims'][0]['status'], 'rolled_back')
        self.assertNotIn('PRIVATE_COMMIT_ERROR', path.read_text())
        self.assertFalse(TurnWork.objects.exists())

    def test_10_callback_sql_is_outside_committed_transaction(self):
        message = self.ready()
        path = self.path()
        with trace.capture(path, run_id='callbacks', worker='planner-1'):
            with transaction.atomic():
                durable.claim_turn(message.conversation_id)
                transaction.on_commit(lambda: Message.objects.count())
        rows = read_journal(path)
        commit = next(r for r in rows if r['event'] == 'commit_end')
        after = [r for r in rows if r['event'] == 'sql_start' and r['seq'] > commit['seq']]
        self.assertEqual(len(after), 1)
        self.assertIsNone(after[0]['transaction_id'])

    def test_11_reclaim_retains_membership_and_rejects_old_witness_with_capture(self):
        path = self.path()
        message = self.ready()
        with trace.capture(path, run_id='reclaim', worker='planner-1'):
            old = durable.claim_turn(message.conversation_id)
            TurnWork.objects.filter(pk=old.turn_work_id).update(
                lease_expires_at=durable.db_now()-timedelta(seconds=1))
            new = durable.claim_turn(message.conversation_id)
            self.assertEqual(new.turn_work_id, old.turn_work_id)
            self.assertEqual(new.ownership_epoch, old.ownership_epoch)
            self.assertNotEqual(new.lease_token, old.lease_token)
            with self.assertRaises(durable.OwnershipLost):
                durable.assert_witness(old)
            durable.assert_witness(new)
        report = reconstruct([read_journal(path)])
        self.assertEqual(len(report['claims']), 2)
        self.assertEqual(report['claims'][0]['membership'], report['claims'][1]['membership'])
        self.assertEqual(TurnWork.objects.get(pk=new.turn_work_id).attempts, 2)
        self.assertEqual(LLMCall.objects.count(), 0)

    def test_13_failed_savepoint_rollback_marker_does_not_override_real_commit(self):
        message = self.ready()
        path = self.path()
        # Python failure before issuing rollback SQL; catch it and release the
        # still-valid savepoint. The real outer COMMIT remains authoritative.
        with patch.object(connection, '_savepoint_rollback', side_effect=RuntimeError('PRIVATE_SP_ERROR')):
            with trace.capture(path, run_id='savepoint-error', worker='planner-1'):
                with transaction.atomic():
                    with transaction.atomic():
                        sid = connection.savepoint_ids[-1]
                        witness = durable.claim_turn(message.conversation_id)
                        with self.assertRaisesRegex(RuntimeError, 'PRIVATE_SP_ERROR'):
                            connection.savepoint_rollback(sid)
        durable.assert_witness(witness)
        rows = read_journal(path)
        self.assertEqual(reconstruct([rows])['claims'][0]['status'], 'committed')
        self.assertTrue(any(r['event'] == 'savepoint_rollback_end' and
                            r['error_class'] == 'RuntimeError' for r in rows))
        self.assertNotIn('PRIVATE_SP_ERROR', path.read_text())
