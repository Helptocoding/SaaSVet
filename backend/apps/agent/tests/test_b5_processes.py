"""SAFE-FI-01/02/05, DUP/OWN races in independent PostgreSQL processes."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.agent.models import HumanHandoff, TurnWork, Conversation
from apps.channels.models import Message
from . import test_b3_processes as process_helpers
from . import test_b3_durable as fixtures


@override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
class B5ProcessTests(TransactionTestCase):
    setUp = fixtures.DurableTurnTests.setUp
    inbound = fixtures.DurableTurnTests.inbound
    expire = fixtures.DurableTurnTests.expire
    ready = process_helpers.B3ProcessTests.ready
    result = process_helpers.B3ProcessTests.result
    cleanup_process = staticmethod(process_helpers.B3ProcessTests.cleanup_process)

    def start(self, mode):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8')
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m',
            'apps.agent.tests.b5_process', mode, str(self.conv.pk)],
            cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf8')
        self.addCleanup(self.cleanup_process, process)
        return process

    def go(self, process):
        self.ready(process)
        process.stdin.write('go\n'); process.stdin.flush()

    def prepare(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.inbound('está convulsionando')

    def crash_recover(self, mode):
        from apps.agent.durable import OwnershipWitness
        self.prepare()
        proc = self.start(mode); self.go(proc); self.result(proc, expected=17)
        work = TurnWork.objects.get()
        self.assertEqual(work.status, TurnWork.PROCESSING)
        self.assertFalse(HumanHandoff.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        witness = OwnershipWitness(self.org.pk, self.conv.pk, work.pk, work.lease_token, work.ownership_epoch)
        self.expire(witness)
        proc = self.start('run'); self.go(proc); self.result(proc)
        work.refresh_from_db()
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertEqual(work.attempts, 2)
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_safe_fi_01_process_killed_after_detection(self):
        self.crash_recover('detect_crash')

    def test_safe_fi_02_process_killed_after_case_before_output(self):
        self.crash_recover('handoff_crash')

    def test_safe_dup_01_two_inbound_processes_one_handoff(self):
        processes = [self.start('duplicate'), self.start('duplicate')]
        for p in processes: self.go(p)
        results = [self.result(p) for p in processes]
        self.assertEqual(sum(r['created'] for r in results), 1)
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)

    def test_safe_fi_05_safety_worker_vs_human_takeover(self):
        self.prepare()
        processes = [self.start('run'), self.start('takeover')]
        for p in processes: self.ready(p)
        for p in processes: p.stdin.write('go\n'); p.stdin.flush()
        for p in processes: self.result(p)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HUMAN_ACTIVE)
        self.assertIn(self.conv.ownership_epoch, (1, 2))  # one or two distinct real transitions
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertFalse(Message.objects.filter(direction='out', status='pending').exists())

    def test_own_04_two_safety_workers_one_epoch_and_case(self):
        self.prepare()
        processes = [self.start('run'), self.start('run')]
        for p in processes: self.ready(p)
        for p in processes: p.stdin.write('go\n'); p.stdin.flush()
        for p in processes: self.result(p)
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
