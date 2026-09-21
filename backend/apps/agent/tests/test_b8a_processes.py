"""PostgreSQL processes, actual lock waits, kill and committed test evidence."""
import json
import os
import subprocess
import sys
import site
import time
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import django
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from apps.agent.models import TurnWork, ToolExecution
from .test_operation_execution import ExecutionFixtures
from .b8a_support import enabled_test_adapter, effect_count


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8AProcessTests(ExecutionFixtures, TransactionTestCase):
    def start(self, mode):
        self.assertEqual(connection.vendor, 'postgresql')
        args = {'witness': asdict(self.witness), 'operation_key': self.op.operation_key,
                'goal_id': self.goal.pk, 'max_id': self.max.pk, 'contact_id': self.conv.contact_id,
                'django_version': django.get_version()}
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()))
        # Windows venv python.exe is a launcher. Kill and observe the actual
        # interpreter PID (same convention as the established B7B probes).
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m', 'apps.agent.tests.b8a_process',
            mode, json.dumps(args, default=str)], cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        self.barrier(proc, 'READY')
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B8A_'):
                    return line.strip()
            return ''
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                actual = pool.submit(read).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        if not actual:
            self.fail('Child exited before barrier: ' + proc.stderr.read()[-2500:])
        self.assertEqual(actual, 'B8A_' + expected)

    def release(self, proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-3000:])
        return json.loads(next(x.removeprefix('B8A_RESULT ') for x in stdout.splitlines()
                              if x.startswith('B8A_RESULT ')))

    def blocked(self, proc):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as c:
                c.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',
                          ['b8a_' + str(proc.pid)])
                rows = c.fetchall()
            if ('Lock',) in rows:
                return
            time.sleep(.02)
        self.fail('Second independent process did not actually wait on a PostgreSQL lock')

    def reclaim(self):
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(
            lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()
        self.context = replace(self.context, witness=self.witness)

    def retry(self):
        with enabled_test_adapter():
            return self.execute()

    def test_race01_fi08_two_executors_one_effect(self):
        self.authorized()
        first = self.start('hold_effect')
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING')
        second = self.start('execute')
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.assertEqual(effect_count(), 0)  # MVCC: no partial commit visible
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual([a['status'], b['status']], ['SUCCEEDED', 'SUCCEEDED'])
        self.assertTrue(b['duplicate'])
        self.assertEqual(effect_count(), 1)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)

    def change_wins(self, mode):
        self.authorized()
        changing = self.start('hold_' + mode)
        self.release(changing)
        self.barrier(changing, 'CHANGED')
        executing = self.start('execute')
        self.release(executing)
        self.barrier(executing, 'ATTEMPTING')
        self.blocked(executing)
        self.release(changing)
        self.assertTrue(self.result(changing)['changed'])
        self.assertEqual(self.result(executing)['status'], 'DENIED')
        self.assertEqual(effect_count(), 0)
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')

    def test_race02_fi07_correction_wins(self):
        self.change_wins('correction')

    def test_race04_fi06_takeover_wins(self):
        self.change_wins('takeover')

    def test_race06_revocation_committed_before_effect(self):
        self.change_wins('revocation')

    def effect_wins(self, mode):
        self.authorized()
        executing = self.start('hold_effect')
        self.release(executing)
        self.barrier(executing, 'ATTEMPTING')
        self.barrier(executing, 'EFFECT_PENDING')
        changing = self.start(mode)
        self.release(changing)
        self.blocked(changing)
        self.assertEqual(effect_count(), 0)
        self.release(executing)
        self.assertEqual(self.result(executing)['status'], 'SUCCEEDED')
        self.assertTrue(self.result(changing)['changed'])
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(effect_count(), 1)

    def test_race03_effect_before_correction_is_not_undone(self):
        self.effect_wins('correction')

    def test_race05_effect_before_takeover_is_not_undone(self):
        self.effect_wins('takeover')

    def test_effect_before_revocation_is_not_undone(self):
        self.effect_wins('revocation')

    def test_fi01_crash_before_locks(self):
        self.authorized()
        proc = self.start('before_lock')
        self.release(proc)
        self.barrier(proc, 'BEFORE_LOCK')
        self.cleanup(proc)
        self.assertEqual(effect_count(), 0)
        self.reclaim()
        self.assertEqual(self.retry().status, 'SUCCEEDED')
        self.assertEqual(effect_count(), 1)

    def test_race08_fi02_crash_after_authorization_before_effect(self):
        self.authorized()
        proc = self.start('before_effect')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'BEFORE_EFFECT')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(effect_count(), 0)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 0)
        self.reclaim()
        self.assertEqual(self.retry().status, 'SUCCEEDED')

    def test_kill_after_local_effect_before_atomic_commit_rolls_back_everything(self):
        self.authorized()
        proc = self.start('hold_effect')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'EFFECT_PENDING')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(effect_count(), 0)
        self.reclaim()
        self.assertEqual(self.retry().status, 'SUCCEEDED')

    def test_crash_after_local_commit_keeps_effect_and_ledger(self):
        self.authorized()
        proc = self.start('after_commit')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'COMMITTED')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        self.assertEqual(effect_count(), 1)
        self.reclaim()
        self.assertTrue(self.retry().duplicate)
        self.assertEqual(effect_count(), 1)

    def test_race07_fi03_independent_commit_before_ledger_reconciles(self):
        self.authorized()
        proc = self.start('external_commit_crash')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'EFFECT_COMMITTED')
        self.assertEqual(effect_count(), 1)  # independently committed while worker is alive
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.cleanup(proc)
        self.reclaim()
        recovery = self.start('execute')
        self.release(recovery)
        result = self.result(recovery)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertTrue(result['duplicate'])
        self.assertEqual(effect_count(), 1)

    def test_fi04_real_database_error_persisting_result_rolls_back_local_effect(self):
        self.authorized()
        proc = self.start('db_error')
        self.release(proc)
        self.assertEqual(self.result(proc)['error'], 'DataError')
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(effect_count(), 0)
        self.assertEqual(self.retry().status, 'SUCCEEDED')

    def test_fi05_timeout_after_independent_commit_is_uncertain_then_reconciled(self):
        self.authorized()
        proc = self.start('timeout_after_commit')
        self.release(proc)
        self.assertEqual(self.result(proc)['status'], 'UNCERTAIN')
        self.assertEqual(effect_count(), 1)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'UNCERTAIN')
        recovery = self.start('execute')
        self.release(recovery)
        self.assertEqual(self.result(recovery)['status'], 'SUCCEEDED')
        self.assertEqual(effect_count(), 1)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)

    def test_race09_retry_uncertain_has_no_blind_effect(self):
        self.authorized()
        proc = self.start('timeout_absent')
        self.release(proc)
        self.assertEqual(self.result(proc)['status'], 'UNCERTAIN')
        recovery = self.start('execute')
        self.release(recovery)
        self.assertEqual(self.result(recovery)['status'], 'UNCERTAIN')
        self.assertEqual(effect_count(), 0)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)

    def test_race10_replacement_during_preparation_cannot_execute_old_definition(self):
        self.authorized()
        proc = self.start('execute')  # captured old key, has not acquired locks
        self.response('Mejor para Max')
        from apps.agent import durable
        durable.finalize_turn(self.witness)
        self.witness = self.claim()
        self.correct()
        self.observe_slot()
        replacement = self.prepare()
        self.assertEqual(replacement.replaces_id, self.op.pk)
        self.release(proc)
        self.assertEqual(self.result(proc)['status'], 'DENIED')
        self.assertEqual(effect_count(), 0)
