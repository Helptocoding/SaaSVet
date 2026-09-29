"""SCALE component evidence: PostgreSQL processes, crash and live stale owner."""
import json
import os
import site
import subprocess
import sys
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.agent import durable
from apps.agent.models import LLMCall, TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from . import test_b9a_processes as b9ap
from . import test_b9c_concurrency as cases
from .b9a_harness import ApplicationHarness


class B9CProcessTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp
    inbound = cases.B9CConcurrencyTests.inbound
    human_client = b9a.B9AE2ETests.human_client
    cleanup = b9ap.B9AProcessTests.cleanup
    read = b9ap.B9AProcessTests.read
    go = b9ap.B9AProcessTests.go
    result = b9ap.B9AProcessTests.result
    kill = b9ap.B9AProcessTests.kill

    def record(self, kind, data):
        if os.environ.get('B8E_RESULTS_PATH'):
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.b9c-processes.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps({'test_id': self.id(), 'event': kind, **data}) + '\n')

    def start(self, conv, mode='claim'):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.b9c_process', mode, str(conv)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        ready = self.read(proc, 'READY')
        self.assertEqual(ready['pid'], proc.pid)
        proc.backend_pid = ready['backend_pid']
        return proc

    def run_child(self, msg, mode='claim'):
        p = self.start(msg.conversation_id, mode)
        self.go(p)
        return self.result(p)

    def test_fi_07_three_processes_compete_last_slot_distinct_conversations(self):
        msgs = [self.inbound(n) for n in range(1, 4)]
        processes = [self.start(m.conversation_id) for m in msgs]
        for p in processes: self.go(p)
        results = [self.result(p) for p in processes]
        self.assertEqual(len({r['pid'] for r in results}), 3)
        self.assertEqual(len({r['backend_pid'] for r in results}), 3)
        self.assertEqual(sum(r['admitted'] for r in results), 1)
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        self.assertEqual(Message.objects.filter(direction='in', turn_work__isnull=True).count(), 2)
        self.assertTrue(all(r['active'] <= 1 for r in results))

    def test_org_lock_defers_claim_but_does_not_block_inbound_fk(self):
        a, b = self.inbound(), self.inbound(2)
        first = self.start(a.conversation_id, 'acquire_atomic')
        self.go(first); self.read(first, 'BOUNDARY')
        with connection.cursor() as c:
            c.execute("SELECT mode, granted FROM pg_locks WHERE pid=%s AND relation='organizations_organization'::regclass", [first.backend_pid])
            locks = c.fetchall()
        self.assertIn(('RowShareLock', True), locks)
        self.record('ORG_LOCK', {'backend_pid': first.backend_pid, 'locks': locks})
        self.assertFalse(self.run_child(b)['admitted'])
        # A webhook on another conversation remains durable while quota is
        # locked. PostgreSQL FK checks are compatible with NO KEY UPDATE.
        with connection.cursor() as c: c.execute("SET lock_timeout='3s'")
        try: third = self.inbound(3)
        finally:
            with connection.cursor() as c: c.execute('RESET lock_timeout')
        self.assertIsNotNone(third.pk)
        self.go(first); self.assertTrue(self.result(first)['admitted'])

    def test_fi_01_kill_before_claim_or_before_commit_leaves_no_capacity(self):
        a = self.inbound()
        for mode in ('before_claim', 'acquire_atomic'):
            with self.subTest(mode=mode):
                p = self.start(a.conversation_id, mode)
                self.go(p); self.read(p, 'BOUNDARY'); self.kill(p)
                self.assertEqual(TurnWork.objects.count(), 0)
                self.assertIsNone(Message.objects.get(pk=a.pk).turn_work_id)
        self.assertTrue(self.run_child(a)['admitted'])

    def test_fi_02_08_kill_after_claim_restart_preserves_capacity_until_expiry(self):
        a, b = self.inbound(), self.inbound(2)
        p = self.start(a.conversation_id, 'after_claim')
        self.go(p); self.read(p, 'BOUNDARY')
        before = TurnWork.objects.get()
        self.kill(p)
        self.assertFalse(self.run_child(b)['admitted'])
        self.assertFalse(self.run_child(a)['admitted'])
        self.assertEqual(LLMCall.objects.count(), 0)
        self.h.retry_due(a.conversation)
        self.assertTrue(self.run_child(a, 'run')['admitted'])
        after = TurnWork.objects.get()
        self.assertEqual(after.pk, before.pk)
        self.assertNotEqual(after.lease_token, before.lease_token)
        self.assertEqual(after.attempts, 2)
        self.assertEqual(after.status, 'COMPLETED')
        self.assertTrue(self.run_child(b)['admitted'])

    def test_fi_03_04_10_kill_provider_or_publication_keeps_budget_and_recovers(self):
        for n, mode in enumerate(('during_llm', 'after_response'), 1):
            with self.subTest(mode=mode):
                a = self.inbound(n)
                p = self.start(a.conversation_id, mode)
                self.go(p); self.read(p, 'BOUNDARY')
                before = TurnWork.objects.get(conversation=a.conversation)
                self.assertEqual(before.llm_calls_admitted, 1)
                self.kill(p)
                self.assertEqual(Message.objects.filter(conversation=a.conversation, direction='out').count(), 0)
                self.assertFalse(self.run_child(a)['admitted'])
                self.h.retry_due(a.conversation)
                result = self.run_child(a, 'run')
                self.assertTrue(result['admitted'])
                after = TurnWork.objects.get(pk=before.pk)
                self.assertEqual(after.llm_calls_admitted, 2)
                self.assertEqual(after.status, 'COMPLETED')
                self.assertEqual(Message.objects.filter(conversation=a.conversation, direction='out').count(), 1)

    def test_fi_05_06_live_expired_worker_cannot_progress_after_other_claim(self):
        a, b = self.inbound(), self.inbound(2)
        old = self.start(a.conversation_id, 'during_llm')
        self.go(old); self.read(old, 'BOUNDARY')
        self.h.retry_due(a.conversation)
        current = self.run_child(b)
        self.assertTrue(current['admitted'])
        self.go(old)
        result = self.result(old)
        self.assertTrue(result['lost'])
        self.assertEqual(result['active'], 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)
        self.assertEqual(LLMCall.objects.count(), 1)
        self.assertEqual(TurnWork.objects.get(conversation=b.conversation).attempts, 1)

    def test_live_takeover_fences_old_worker_without_waiting_for_org_capacity(self):
        a, b = self.inbound(), self.inbound(2)
        old = self.start(a.conversation_id, 'during_llm')
        self.go(old); self.read(old, 'BOUNDARY')
        response = self.human_client().post(f'/api/inbox/conversations/{a.conversation.public_id}/claim/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.run_child(b)['admitted'])
        self.go(old)
        self.assertTrue(self.result(old)['lost'])
        self.assertEqual(Message.objects.filter(direction='out').count(), 0)

    def test_scale_01_two_planners_cross_tenant_and_independent_sender(self):
        a = self.inbound()
        old = self.start(a.conversation_id, 'during_llm')
        self.go(old); self.read(old, 'BOUNDARY')
        for n in range(2, 14): self.inbound(n)
        org, channel, *_ = b9a.seed_domain('B')
        other = ApplicationHarness(channel)
        b = self.inbound(99, other)
        # Real command poll selects the healthy org despite the noisy backlog.
        healthy = b9ap.B9AProcessTests.start(self, 'worker', channel)
        self.go(healthy); self.result(healthy)
        self.assertEqual(TurnWork.objects.get(conversation=b.conversation).status, 'COMPLETED')
        sender = b9ap.B9AProcessTests.start(self, 'sender', channel)
        self.go(sender); result = self.result(sender)
        self.assertEqual([e['boundary'] for e in result['wire']], ['meta'])
        self.assertEqual(Message.objects.get(direction='out').status, 'sent')
        self.assertEqual(TurnWork.objects.get(conversation=a.conversation).status, 'PROCESSING')
        self.go(old); self.result(old)

    def test_scale_02_guidance_during_blocked_llm_and_slow_meta(self):
        a = self.inbound()
        old = self.start(a.conversation_id, 'during_llm')
        self.go(old); self.read(old, 'BOUNDARY')
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True):
            urgent = self.h.inbound('Mi perro está convulsionando ahora', wa_id='5215512348888')
        self.assertEqual(TurnWork.objects.get(conversation=urgent.conversation).status, 'COMPLETED')
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        sender = b9ap.B9AProcessTests.start(self, 'hold_meta')
        self.go(sender); self.read(sender, 'BOUNDARY')
        guidance = Message.objects.get(semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE)
        self.assertEqual(guidance.status, 'sending')
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        self.assertEqual(LLMCall.objects.count(), 1)
        self.go(sender); self.result(sender)
        guidance.refresh_from_db()
        self.assertEqual(guidance.status, 'sent')
        self.assertEqual(TurnWork.objects.get(conversation=a.conversation).status, 'PROCESSING')
        self.go(old); self.result(old)
