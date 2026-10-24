"""Causal journal concurrency, real lock waits and blocked LLM isolation."""
import json
import os
import queue
import site
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import psycopg
from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.agent import durable
from apps.agent.claim_diagnostic_report import read_journal, reconstruct, attach_waits
from apps.agent.claim_diagnostic_waits import sample
from apps.agent.models import TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from .b9a_harness import ApplicationHarness
from .claim_diagnostic_evidence import save, save_equivalence


class ClaimDiagnosticProcessTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp

    def ready(self, harness=None):
        message = (harness or self.h).inbound('Consulta sintética')
        Message.objects.filter(pk=message.pk).update(available_at=durable.db_now()-timedelta(seconds=1))
        return message

    def start(self, message, mode='claim', enabled=True):
        folder = tempfile.TemporaryDirectory(prefix='e4-trace-process-')
        self.addCleanup(folder.cleanup)
        path = Path(folder.name)/'trace.jsonl'
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONPATH=os.pathsep.join(site.getsitepackages()), PYTHONIOENCODING='utf-8',
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([sys.executable, '-X','utf8','-m',
            'apps.agent.tests.claim_diagnostic_process', mode, str(message.conversation_id),
            str(message.channel_account_id), str(path), 'process-test', 'on' if enabled else 'off'],
            cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        proc.events = queue.Queue()
        proc.trace_path = path
        proc.enabled = enabled
        proc.errors = []
        def stdout():
            for line in proc.stdout:
                if line.startswith('TRACE_'):
                    kind, data = line.strip().split(' ', 1)
                    proc.events.put((kind, json.loads(data)))
        def stderr():
            for line in proc.stderr:
                proc.errors.append(line)
        threading.Thread(target=stdout, daemon=True).start()
        threading.Thread(target=stderr, daemon=True).start()
        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
            for handle in (proc.stdin, proc.stdout, proc.stderr):
                handle.close()
        self.addCleanup(cleanup)
        proc.target = self.event(proc, 'READY')
        return proc

    def event(self, proc, kind):
        try:
            actual, data = proc.events.get(timeout=45)
        except queue.Empty:
            self.fail('Worker missing '+kind+': '+''.join(proc.errors)[-2000:])
        self.assertEqual(actual, 'TRACE_'+kind)
        return data

    def go(self, proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def finish(self, proc):
        result = self.event(proc, 'RESULT')
        self.assertEqual(proc.wait(timeout=10), 0, ''.join(proc.errors)[-2000:])
        return result, read_journal(proc.trace_path) if proc.enabled else None

    def equivalent_result(self, result):
        return dict(claimed=result['turn_work_id'] is not None,
                    sql_sequence=result['sql_sequence'], commits=result['commits'], state=result['state'])

    def another_ready(self, name):
        _, channel, *_ = b9a.seed_domain(name)
        return self.ready(ApplicationHarness(channel))

    def test_01_competing_processes_correlate_single_admission(self):
        outputs = []
        for enabled in (False, True):
            message = self.another_ready('TRACE-RACE-'+str(enabled))
            first = self.start(message, 'claim_hold_commit', enabled)
            second = self.start(message, enabled=enabled)
            self.assertNotEqual(first.pid, second.pid)
            self.assertNotEqual(first.target['backend_pid'], second.target['backend_pid'])
            self.go(first)
            # Django clears in_atomic_block before invoking the driver commit;
            # the transaction/locks remain live until that call returns.
            self.assertFalse(self.event(first, 'COMMIT_HELD')['in_atomic'])
            # Hold the winner's real locks while the loser tries SKIP LOCKED.
            self.go(second)
            b, rows_b = self.finish(second)
            self.assertIsNone(b['turn_work_id'])
            self.go(first)
            a, rows_a = self.finish(first)
            self.assertIsNotNone(a['turn_work_id'])
            work = TurnWork.objects.get(conversation_id=message.conversation_id)
            self.assertEqual(durable.active_org_work(message.organization_id).count(), 1)
            self.assertEqual(work.attempts, 1)
            outputs.append([self.equivalent_result(r) for r in (a,b)])
            if enabled:
                report = reconstruct([rows_a, rows_b])
                self.assertEqual(len(report['claims']), 1)
                self.assertTrue(report['attempts_without_binding'])
                save('concurrency', [rows_a, rows_b], report)
                for proc, rows in ((first,rows_a),(second,rows_b)):
                    self.assertEqual({r['backend_pid'] for r in rows}, {proc.target['backend_pid']})
                    self.assertEqual({r['session_id'] for r in rows}, {proc.target['session_id']})
        self.assertEqual(outputs[0], outputs[1])
        save_equivalence('concurrency', outputs)

    def test_02_controlled_message_lock_is_observed_by_separate_connection(self):
        config = connection.settings_dict
        outputs = []
        with psycopg.connect(dbname=config['NAME'], user=config['USER'], password=config['PASSWORD'],
                host=config['HOST'], port=config['PORT'], autocommit=True) as observer:
            observer.read_only = True
            for enabled in (False, True):
                message = self.another_ready('TRACE-LOCK-'+str(enabled))
                proc = self.start(message, enabled=enabled)
                samples = []
                with transaction.atomic():
                    Message.objects.select_for_update().get(pk=message.pk)
                    blocker_pid = connection.connection.info.backend_pid
                    self.go(proc)
                    deadline = time.monotonic()+15
                    while time.monotonic() < deadline:
                        observed = sample(observer, [proc.target], run_id='process-test')
                        samples.extend(observed)
                        if any(s['wait_event_type'] == 'Lock' and blocker_pid in s['blocking_pids'] for s in observed):
                            break
                        time.sleep(.01)
                    else:
                        self.fail('Controlled PostgreSQL blocker was not observed')
                    # Release only after real lock evidence in both ON and OFF.
                result, rows = self.finish(proc)
                self.assertIsNotNone(result['turn_work_id'])
                outputs.append(self.equivalent_result(result))
                if enabled:
                    self.assertEqual(reconstruct([rows])['claims'][0]['status'], 'committed')
                    wait = next(s for s in samples if s['wait_event_type'] == 'Lock')
                    intervals = [r for r in rows if r['event'] == 'sql_end' and
                        r['execute_start_ns'] <= wait['sample_end_ns'] and
                        r['execute_end_ns'] >= wait['sample_start_ns']]
                    self.assertEqual(len(intervals), 1)
                    self.assertGreater(intervals[0]['duration_ns'], 0)
                    self.assertIsNotNone(wait['query_start'])
                    self.assertNotIn('query', wait)
                    report = attach_waits(reconstruct([rows]), samples)
                    self.assertTrue(any(s['wait_event_type'] == 'Lock' for s in report['waits']['matched']))
                    self.assertIsNone(report['waits']['exact_lock_wait_seconds'])
                    save('lock-wait', [rows], report, samples)
        self.assertEqual(outputs[0], outputs[1])
        save_equivalence('lock-wait', outputs)

    def test_03_journal_is_visible_during_blocked_llm_and_other_org_progresses(self):
        outputs = []
        for enabled in (False, True):
            noisy = self.another_ready('TRACE-NOISY-'+str(enabled))
            blocked = self.start(noisy, 'llm', enabled)
            self.go(blocked)
            event = self.event(blocked, 'LLM_BLOCKED')
            self.assertFalse(event['in_atomic'])
            if enabled:
                partial = [json.loads(line) for line in blocked.trace_path.read_text().splitlines()]
                self.assertIn('claim_bound', {r['event'] for r in partial})
                self.assertIn('commit_end', {r['event'] for r in partial})
            self.assertEqual(durable.active_org_work(noisy.organization_id).count(), 1)
            healthy = self.another_ready('TRACE-HEALTHY-'+str(enabled))
            progressing = self.start(healthy, enabled=enabled)
            self.go(progressing)
            result, healthy_rows = self.finish(progressing)
            self.assertIsNotNone(result['turn_work_id'])
            self.assertEqual(durable.active_org_work(healthy.organization_id).count(), 1)
            self.go(blocked)
            noisy_result, noisy_rows = self.finish(blocked)
            outputs.append([self.equivalent_result(r) for r in (noisy_result,result)])
            self.assertEqual(TurnWork.objects.get(conversation_id=noisy.conversation_id).status, TurnWork.COMPLETED)
            if enabled:
                report = reconstruct([noisy_rows, healthy_rows])
                self.assertEqual({r['organization_id'] for r in report['claims']},
                                 {noisy.organization_id, healthy.organization_id})
                self.assertEqual({r['status'] for r in report['claims']}, {'committed'})
                save('blocked-llm', [noisy_rows, healthy_rows], report)
        self.assertEqual(outputs[0], outputs[1])
        save_equivalence('blocked-llm', outputs)
