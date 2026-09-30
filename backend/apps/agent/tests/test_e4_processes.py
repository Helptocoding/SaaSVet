"""E4-PROC: two actual OS planners with colliding selection snapshots."""
import json
import os
import site
import subprocess
import sys
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase
from apps.agent import durable
from apps.agent.models import TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from .b9a_harness import ApplicationHarness
from . import test_b9a_processes as b9ap
from . import test_b9c_processes as b9cp
from . import test_b9c_concurrency as b9c


class E4ProcessTests(TransactionTestCase):
    setUp = b9a.B9AE2ETests.setUp
    inbound = b9c.B9CConcurrencyTests.inbound
    cleanup = b9ap.B9AProcessTests.cleanup
    read = b9ap.B9AProcessTests.read
    result = b9ap.B9AProcessTests.result
    go = b9ap.B9AProcessTests.go
    record = b9cp.B9CProcessTests.record

    def start(self, conversation):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8',
            '-m', 'apps.agent.tests.e4_selection_process', str(conversation)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        ready = self.read(proc, 'READY')
        self.assertEqual(ready['pid'], proc.pid)
        proc.backend_pid = ready['backend_pid']
        return proc

    def collide(self, message):
        a, b = self.start(message.conversation_id), self.start(message.conversation_id)
        for proc in (a, b): self.go(proc); self.read(proc, 'SELECTED')
        self.assertNotEqual(a.pid, b.pid)
        self.assertNotEqual(a.backend_pid, b.backend_pid)
        self.go(a); self.read(a, 'CLAIMED')
        return a, b

    def test_e4_proc_01_collision_falls_through_to_other_tenant_same_poll(self):
        first = self.inbound()
        for number in range(2, 9): self.inbound(number)
        org, channel, *_ = b9a.seed_domain('B')
        healthy = self.inbound(99, ApplicationHarness(channel))
        a, b = self.collide(first)
        self.go(b); self.read(b, 'CLAIMED')
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        self.assertEqual(durable.active_org_work(org.pk).count(), 1)
        self.assertEqual(TurnWork.objects.count(), 2)
        self.go(b); rb = self.result(b)
        self.go(a); ra = self.result(a)
        self.assertEqual(rb['attempts'], [first.conversation_id, healthy.conversation_id])
        self.assertEqual(ra['processed'], 1); self.assertEqual(rb['processed'], 1)
        self.assertEqual(ra['scope_violations']+rb['scope_violations'], 0)
        self.assertEqual(Message.objects.filter(direction='in', turn_work__isnull=True).count(), 7)

    def test_e4_proc_02_colliding_planners_cannot_take_second_slot_same_org(self):
        first = self.inbound()
        self.inbound(2); self.inbound(3)
        a, b = self.collide(first)
        self.go(b); rb = self.result(b)
        self.assertEqual(rb['processed'], 0)
        self.assertEqual(rb['attempts'], [first.conversation_id])
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(durable.active_org_work(self.org.pk).count(), 1)
        self.assertEqual(Message.objects.filter(direction='in', turn_work__isnull=True).count(), 2)
        self.go(a); self.assertEqual(self.result(a)['processed'], 1)
