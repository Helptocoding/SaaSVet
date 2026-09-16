"""Real process isolation for B3 on PostgreSQL, never an SQLite/mock substitute."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase

from apps.agent import durable
from apps.agent.models import TurnWork
from apps.channels.models import Message
from . import test_b3_durable as fixtures


class B3ProcessTests(TransactionTestCase):
    setUp = fixtures.DurableTurnTests.setUp
    inbound = fixtures.DurableTurnTests.inbound
    claim = fixtures.DurableTurnTests.claim
    expire = fixtures.DurableTurnTests.expire

    def start(self, mode):
        env = dict(os.environ)
        env['B3_TEST_DATABASE'] = json.dumps(connection.settings_dict, default=str)
        env['PYTHONIOENCODING'] = 'utf-8'
        proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-m',
            'apps.agent.tests.b3_process', mode, str(self.conv.pk)],
            cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        self.addCleanup(self.cleanup_process, proc)
        return proc

    @staticmethod
    def cleanup_process(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=10)

    def ready(self, proc):
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                line = pool.submit(proc.stdout.readline).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        self.assertEqual(line.strip(), 'B3_READY')

    def result(self, proc, expected=0):
        stdout, stderr = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, expected, stderr[-2000:])
        if expected:
            return None
        line = next(line for line in stdout.splitlines() if line.startswith('B3_RESULT '))
        return json.loads(line.removeprefix('B3_RESULT '))

    def test_dup_01_two_processes_compete_for_one_lease(self):
        processes = [self.start('claim'), self.start('claim')]
        for process in processes:
            self.ready(process)
        for process in processes:
            process.stdin.write('go\n')
            process.stdin.flush()
        results = [self.result(p) for p in processes]
        self.assertEqual(sum(r['work'] is not None for r in results), 1)
        work = TurnWork.objects.get()
        self.assertEqual(work.attempts, 1)
        self.assertEqual(work.status, TurnWork.PROCESSING)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.turn_work_id, work.pk)
        self.assertEqual(self.m1.status, 'pending')

    def test_dur_01_killed_process_restarted_worker_recovers_same_work(self):
        process = self.start('crash')
        self.ready(process)
        process.stdin.write('go\n')
        process.stdin.flush()
        self.result(process, expected=17)
        work = TurnWork.objects.get()
        old = durable.OwnershipWitness(self.org.pk, self.conv.pk, work.pk,
                                        work.lease_token, work.ownership_epoch)
        context = durable.context_for_work(old)
        self.assertEqual(Message.objects.get(pk=self.m1.pk).status, 'pending')
        self.expire(old)
        restart = self.start('run')
        self.ready(restart)
        restart.stdin.write('go\n')
        restart.stdin.flush()
        result = self.result(restart)
        work.refresh_from_db()
        self.assertEqual(result['work'], work.pk)
        self.assertEqual(work.attempts, 2)
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertNotEqual(result['token'], str(old.lease_token))
        self.assertEqual((work.anchor_message_id, work.cursor_message_id),
                         (context.anchor.message_id, context.history_before.message_id))
        self.assertEqual(Message.objects.get(direction='out').output_ordinal, 0)
        self.assertEqual(TurnWork.objects.count(), 1)
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(old, outputs=[{'body': 'Old worker'}])

    def test_llm_timeout_runs_outside_transaction_and_commits_fallback(self):
        process = self.start('timeout')
        self.ready(process)
        process.stdin.write('go\n')
        process.stdin.flush()
        self.result(process)
        work = TurnWork.objects.get()
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertEqual(work.outcome_code, 'escalate')
        out = Message.objects.get(direction='out')
        self.assertEqual(out.turn_work_id, work.pk)
        self.assertEqual(out.status, 'pending')
