"""Real processes, committed fixtures, controlled wire; no concurrency limits."""
import json
import os
import site
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from apps.agent.models import TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as cases


class B9AProcessTests(TransactionTestCase):
    setUp = cases.B9AE2ETests.setUp
    public_read = cases.B9AE2ETests.public_read

    def start(self, mode, channel=None):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
                   DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        # Windows venv python.exe is a redirector. Kill the actual interpreter,
        # matching the historical B3/B8 process harness, not just its launcher.
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.b9a_process', mode, str((channel or self.channel).pk)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        ready = self.read(proc, 'READY')
        self.assertEqual(ready['pid'], proc.pid)
        return proc

    def cleanup(self, proc):
        if proc.poll() is None:
            proc.kill()
        if not proc.stdout.closed:
            proc.communicate(timeout=20)

    def record(self, kind, data):
        if os.environ.get('B8E_RESULTS_PATH'):
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.b9a-processes.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps({'test_id': self.id(), 'event': kind, **data}) + '\n')

    def read(self, proc, kind):
        def read_marker():
            while line := proc.stdout.readline():
                if line.startswith('B9A_'):
                    return line
            return ''
        with ThreadPoolExecutor(max_workers=1) as reader:
            try:
                line = reader.submit(read_marker).result(timeout=55)
            except Exception:
                proc.kill()
                raise
        self.assertTrue(line.startswith('B9A_' + kind + ' '), line or proc.stderr.read()[-2500:])
        data = json.loads(line.split(' ', 1)[1])
        self.record(kind, data)
        return data

    def go(self, proc):
        proc.stdin.write('go\n'); proc.stdin.flush()

    def result(self, proc):
        data = self.read(proc, 'RESULT')
        _, error = proc.communicate(timeout=55)
        self.assertEqual(proc.returncode, 0, error[-3000:])
        return data

    def kill(self, proc):
        proc.kill()
        proc.communicate(timeout=20)

    def test_duplicate_workers_compete_on_real_claim(self):
        inbound = self.h.inbound('Pregunta por los servicios')
        first = self.start('hold_llm'); self.go(first)
        a = self.read(first, 'BOUNDARY')
        second = self.start('worker'); self.go(second)
        b = self.result(second)
        self.assertNotEqual(a['pid'], b['pid'])
        self.assertNotEqual(a['backend_pid'], b['backend_pid'])
        self.assertEqual(b['wire'], [])
        self.go(first); self.result(first)
        self.assertEqual(TurnWork.objects.get(conversation=inbound.conversation).attempts, 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_kill_after_claim_preserves_membership_and_reclaims(self):
        inbound = self.h.inbound('Pregunta por los servicios')
        process = self.start('hold_llm'); self.go(process)
        self.read(process, 'BOUNDARY')
        before = TurnWork.objects.get()
        old_token = before.lease_token
        self.kill(process)
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)
        self.h.retry_due(inbound.conversation)
        restart = self.start('worker'); self.go(restart); self.result(restart)
        after = TurnWork.objects.get()
        self.assertEqual(before.pk, after.pk)
        self.assertNotEqual(old_token, after.lease_token)
        self.assertEqual(after.attempts, 2)
        self.assertEqual(after.status, 'COMPLETED')

    def test_kill_before_publication_rolls_back_and_retries(self):
        inbound = self.h.inbound('Pregunta por los servicios')
        process = self.start('hold_publication'); self.go(process)
        self.read(process, 'BOUNDARY'); self.kill(process)
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)
        self.h.retry_due(inbound.conversation)
        restart = self.start('worker'); self.go(restart); self.result(restart)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_duplicate_senders_one_admission_one_provider_call(self):
        self.public_read()
        first = self.start('hold_meta'); self.go(first); a = self.read(first, 'BOUNDARY')
        second = self.start('sender'); self.go(second); b = self.result(second)
        self.assertNotEqual(a['backend_pid'], b['backend_pid'])
        self.assertEqual(b['wire'], [])
        self.go(first); self.result(first)
        self.assertEqual(Message.objects.get(direction='out').status, 'sent')

    def test_provider_accepted_process_killed_local_response_lost_is_uncertain(self):
        self.public_read()
        process = self.start('accepted_lost'); self.go(process)
        accepted = self.read(process, 'EXTERNAL_ACCEPTED')
        self.read(process, 'BOUNDARY'); self.kill(process)
        out = Message.objects.get(direction='out')
        self.assertEqual(out.status, 'sending')
        self.assertIsNone(out.provider_accepted_at)
        Message.objects.filter(pk=out.pk).update(send_lease_until=timezone.now()-timedelta(seconds=1))
        restart = self.start('sender'); self.go(restart); result = self.result(restart)
        self.assertEqual(result['wire'], [])
        out.refresh_from_db()
        self.assertEqual(out.status, 'uncertain')
        self.h.status(out, 'delivered', provider_id=accepted['provider_id'])
        out.refresh_from_db()
        self.assertEqual(out.status, 'uncertain')

    def test_two_http_processes_deduplicate_then_worker_runs_once(self):
        workers = [self.start('duplicate_http'), self.start('duplicate_http')]
        for proc in workers: self.go(proc)
        results = [self.result(proc) for proc in workers]
        self.assertNotEqual(results[0]['backend_pid'], results[1]['backend_pid'])
        self.assertEqual(Message.objects.filter(direction='in').count(), 1)
        proc = self.start('worker'); self.go(proc); self.result(proc)
        self.assertEqual(TurnWork.objects.count(), 1)

    def test_retry_after_committed_worker_result_does_not_republish(self):
        self.h.inbound('Pregunta por los servicios')
        first = self.start('worker'); self.go(first); self.result(first)
        second = self.start('worker'); self.go(second); result = self.result(second)
        self.assertEqual(result['wire'], [])
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_stale_worker_cannot_publish_after_new_lease_completes(self):
        inbound = self.h.inbound('Pregunta por los servicios')
        first = self.start('hold_llm'); self.go(first); self.read(first, 'BOUNDARY')
        self.h.retry_due(inbound.conversation)
        second = self.start('worker'); self.go(second); self.result(second)
        self.go(first); self.result(first)
        self.assertEqual(TurnWork.objects.get().attempts, 2)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_two_tenants_progress_with_independent_workers(self):
        from .b9a_harness import ApplicationHarness
        org, channel, *_ = cases.seed_domain('B')
        a = self.h.inbound('Pregunta de la primera clínica')
        first = self.start('hold_llm'); self.go(first); self.read(first, 'BOUNDARY')
        other = ApplicationHarness(channel)
        b = other.inbound('Pregunta de la segunda clínica')
        second = self.start('worker', channel); self.go(second); self.result(second)
        self.assertTrue(TurnWork.objects.filter(conversation=b.conversation, status='COMPLETED').exists())
        self.assertTrue(TurnWork.objects.filter(conversation=a.conversation, status='PROCESSING').exists())
        self.go(first); self.result(first)
        self.assertEqual(TurnWork.objects.filter(status='COMPLETED').count(), 2)
        self.assertTrue(all(m.organization_id == m.conversation.organization_id for m in Message.objects.all()))
