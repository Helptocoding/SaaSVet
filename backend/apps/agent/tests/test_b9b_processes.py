"""Committed budget evidence across process death and PostgreSQL row locks."""
import json
import os
import site
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase
from apps.agent import durable
from apps.agent.models import LLMCall, TurnWork
from . import test_b9a_processes as b9ap
from . import test_b9b_budget as b9b
from .test_b9a_e2e import seed_domain
from .b9a_harness import ApplicationHarness
from apps.channels.models import Message


class B9BProcessTests(TransactionTestCase):
    setUp = b9b.B9BBudgetTests.setUp
    claim = b9b.B9BBudgetTests.claim
    admit = b9b.B9BBudgetTests.admit
    cleanup = b9ap.B9AProcessTests.cleanup
    record = b9ap.B9AProcessTests.record
    read = b9ap.B9AProcessTests.read
    go = b9ap.B9AProcessTests.go
    result = b9ap.B9AProcessTests.result
    kill = b9ap.B9AProcessTests.kill

    def start(self, witness, mode='once', key=None):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.b9b_process', mode, json.dumps(asdict(witness), default=str), str(key or uuid4())],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        ready = self.read(proc, 'READY'); self.assertEqual(ready['pid'], proc.pid)
        proc.backend_pid = ready['backend_pid']
        return proc

    def test_fi_01_process_death_before_admission_commit_has_no_consumption(self):
        w = self.claim(1); proc = self.start(w, 'hold_before_commit')
        self.go(proc); self.read(proc, 'BOUNDARY'); self.kill(proc)
        self.assertEqual(LLMCall.objects.count(), 0)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 0)
        restart = self.start(w); self.go(restart)
        self.assertTrue(self.result(restart)['admitted'])

    def test_fi_02_04_process_death_after_commit_restart_has_no_free_slot(self):
        w = self.claim(1); proc = self.start(w, 'hold_after_commit')
        self.go(proc); self.read(proc, 'BOUNDARY'); self.kill(proc)
        self.assertEqual(LLMCall.objects.count(), 1)
        self.h.retry_due(self.conv); new = durable.claim_turn(self.conv.pk)
        restart = self.start(new); self.go(restart)
        self.assertFalse(self.result(restart)['admitted'])
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 1)

    def compete(self, same_key=False):
        w = self.claim(1); key = uuid4()
        first = self.start(w, 'hold_before_commit', key)
        second = self.start(w, key=key if same_key else None)
        self.go(first); self.read(first, 'BOUNDARY'); self.go(second)
        deadline = time.monotonic() + 15
        observed = None
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s', [second.backend_pid])
                observed = cursor.fetchone()
            if observed and observed[0] == 'Lock' and first.backend_pid in observed[1]: break
            time.sleep(.05)
        self.assertIsNotNone(observed)
        self.assertEqual(observed[0], 'Lock')
        self.record('PG_LOCK', {'first': first.backend_pid, 'second': second.backend_pid,
                               'blocking_pids': observed[1]})
        self.go(first)
        a, b = self.result(first), self.result(second)
        self.assertNotEqual(a['pid'], b['pid'])
        self.assertEqual(sum([a['admitted'], b['admitted']]), 1)
        self.assertEqual(LLMCall.objects.count(), 1)
        self.assertEqual(TurnWork.objects.get().llm_calls_admitted, 1)

    def test_fi_07_two_processes_last_slot_with_observed_lock(self):
        self.compete()

    def test_fi_06_duplicate_admission_uuid_consumes_once(self):
        self.compete(same_key=True)

    def test_fi_08_stale_witness_process_cannot_admit(self):
        w = self.claim(1)
        proc = self.start(replace(w, lease_token=uuid4())); self.go(proc)
        self.assertFalse(self.result(proc)['admitted'])
        self.assertEqual(LLMCall.objects.count(), 0)

    def test_independent_tenants_progress_while_first_holds_budget_lock(self):
        w = self.claim(1)
        org, channel, *_ = seed_domain('B'); other = ApplicationHarness(channel)
        msg = other.inbound('Consulta independiente')
        Message.objects.filter(pk=msg.pk).update(available_at=None)
        second_w = durable.claim_turn(msg.conversation_id)
        first = self.start(w, 'hold_before_commit'); self.go(first); self.read(first, 'BOUNDARY')
        second = self.start(second_w); self.go(second)
        self.assertTrue(self.result(second)['admitted'])
        self.go(first); self.assertTrue(self.result(first)['admitted'])
        self.assertEqual(LLMCall.objects.count(), 2)
