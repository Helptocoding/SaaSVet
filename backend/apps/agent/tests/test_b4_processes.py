"""SEND-FI-01/02/03/08/12: independent processes, real locks and commits."""
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from django.db import connection
from django.test import TransactionTestCase

from apps.agent import sender
from .test_b4_sender import SenderFixture


class B4ProcessTests(SenderFixture, TransactionTestCase):
    def start(self, mode):
        env = dict(os.environ, B4_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.b4_process', mode, str(self.message.pk)],
            cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=10)

    def barrier(self, proc, expected):
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                line = pool.submit(proc.stdout.readline).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        self.assertEqual(line.strip(), expected)

    def go(self, proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc, code=0):
        stdout, stderr = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, code, stderr[-3000:])
        if code:
            return None
        line = next(line for line in stdout.splitlines() if line.startswith('B4_RESULT '))
        return json.loads(line.removeprefix('B4_RESULT '))

    def test_send_fi_12_two_processes_one_claim_one_http(self):
        processes = [self.start('send'), self.start('send')]
        for proc in processes:
            self.barrier(proc, 'B4_READY')
        for proc in processes:
            self.go(proc)
        results = [self.result(proc) for proc in processes]
        self.assertEqual(sum(row['claimed'] for row in results), 1)
        self.assertEqual(sum(row['http_calls'] for row in results), 1)
        self.assertEqual(self.state(), 'sent')
        self.assertEqual(self.message.attempts, 1)

    def test_send_fi_01_process_killed_after_claim_without_admission(self):
        proc = self.start('crash_claim')
        self.barrier(proc, 'B4_READY')
        self.go(proc)
        self.result(proc, code=17)
        self.assertEqual(self.state(), 'sending')
        self.assertIsNone(self.message.send_admitted_at)
        self.expire()
        sender.recover_expired()
        self.assertEqual(self.state(), 'uncertain')
        restart = self.start('send')
        self.barrier(restart, 'B4_READY')
        self.go(restart)
        self.assertEqual(self.result(restart)['http_calls'], 0)

    def test_send_fi_03_process_killed_after_meta_acceptance(self):
        proc = self.start('crash_accepted')
        self.barrier(proc, 'B4_READY')
        self.go(proc)
        self.result(proc, code=19)
        self.assertEqual(self.state(), 'sending')
        self.assertIsNotNone(self.message.send_admitted_at)
        self.assertIsNone(self.message.external_message_id)
        self.expire()
        sender.recover_expired()
        self.assertEqual(self.state(), 'uncertain')
        restart = self.start('send')
        self.barrier(restart, 'B4_READY')
        self.go(restart)
        self.assertEqual(self.result(restart)['http_calls'], 0)

    def test_send_fi_02_takeover_in_other_process_before_admission(self):
        proc = self.start('before_http')
        self.barrier(proc, 'B4_READY')
        self.go(proc)
        self.barrier(proc, 'B4_CLAIMED')
        self.takeover()
        self.go(proc)
        self.assertEqual(self.result(proc)['http_calls'], 0)
        self.assertEqual(self.state(), 'discarded')

    def test_send_fi_08_other_transaction_progresses_while_http_blocked(self):
        proc = self.start('during_http')
        self.barrier(proc, 'B4_READY')
        self.go(proc)
        self.barrier(proc, 'B4_HTTP')
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '3s'")
        try:
            self.takeover()  # must commit BEFORE releasing external HTTP barrier
            self.assertEqual(self.state(), 'sending')
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET lock_timeout')
        self.go(proc)
        self.assertEqual(self.result(proc)['http_calls'], 1)
        self.assertEqual(self.state(), 'sent')
