"""E4-YIELD-PROC-01..02; real processes/PG connections, no capacity mutex in Python."""
import json
import os
from pathlib import Path
import site
import subprocess
import sys

from django.db import connection
from django.test import TransactionTestCase

from apps.agent import durable
from apps.agent.models import LLMCall, TurnWork
from apps.channels.models import Message
from . import test_b9a_processes as b9ap, test_b9c_processes as b9cp
from .test_e4_claim_yield import E4ClaimYieldTests


class E4YieldProcessTests(TransactionTestCase):
    setUp = E4ClaimYieldTests.setUp
    inbound = E4ClaimYieldTests.inbound
    pair = E4ClaimYieldTests.pair
    cleanup = b9ap.B9AProcessTests.cleanup
    read = b9ap.B9AProcessTests.read
    go = b9ap.B9AProcessTests.go
    result = b9ap.B9AProcessTests.result
    record = b9cp.B9CProcessTests.record

    def start(self, clock):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict,default=str),
            E4_YIELD_TEST_CLOCK=clock.isoformat(), PYTHONIOENCODING='utf-8',
            PYTHONPATH=os.pathsep.join(site.getsitepackages()), DISABLE_SENTRY='True',SENTRY_DSN='',REDIS_URL='')
        proc = subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-X','utf8','-m',
            'apps.agent.tests.e4_yield_process'],cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.addCleanup(self.cleanup,proc)
        ready = self.read(proc,'READY')
        proc.backend_pid = ready['backend_pid']
        return proc

    def forecast_pair(self, clock):
        a,b = self.start(clock),self.start(clock)
        self.assertNotEqual(a.pid,b.pid)
        self.assertNotEqual(a.backend_pid,b.backend_pid)
        for proc in (a,b):
            self.go(proc)
            observed = self.read(proc,'FORECAST')
            self.assertEqual((observed['processed'],observed['active'],observed['admissions']),(0,0,0))
            self.read(proc,'FORECAST_WAIT')
        self.assertEqual(LLMCall.objects.count(),0)
        for proc in (a,b):
            self.go(proc); self.read(proc,'SELECTED')
        return a,b

    def test_e4_yield_proc_01_both_forecasts_reserve_nothing_then_collide_and_fall_through(self):
        org,_,ready,future,clock = self.pair(prior_healthy=True)
        a,b = self.forecast_pair(clock)
        self.assertEqual(TurnWork.objects.count(),2)
        self.go(a); self.read(a,'CLAIMED')
        self.go(b); self.read(b,'CLAIMED')
        self.assertEqual(durable.active_org_work(org.pk).count(),1)
        self.assertEqual(durable.active_org_work(self.org.pk).count(),1)
        self.assertEqual(TurnWork.objects.count(),4)
        self.go(b); rb = self.result(b)
        self.go(a); ra = self.result(a)
        self.assertEqual(ra['attempts'],[future.conversation_id])
        self.assertEqual(rb['attempts'],[future.conversation_id,ready.conversation_id])
        self.assertEqual((ra['processed'],rb['processed']),(1,1))
        self.assertEqual(ra['scope_violations']+rb['scope_violations'],0)
        self.assertEqual(ra['admissions']+rb['admissions'],0)

    def test_e4_yield_proc_02_stale_candidate_discarded_and_last_org_slot_revalidated(self):
        _,_,ready,future,clock = self.pair()
        a,b = self.forecast_pair(clock)
        Message.objects.filter(pk=future.pk).update(status=Message.STATUS_DISCARDED)
        self.go(a); self.read(a,'CLAIMED')
        self.go(b); rb = self.result(b)
        self.assertEqual(rb['processed'],0)
        self.assertEqual(rb['attempts'],[future.conversation_id,ready.conversation_id])
        self.assertEqual(durable.active_org_work(self.org.pk).count(),1)
        self.assertEqual(TurnWork.objects.count(),2)
        self.assertIsNone(Message.objects.get(pk=future.pk).turn_work_id)
        self.go(a); ra = self.result(a)
        self.assertEqual(ra['processed'],1)
        self.assertEqual(LLMCall.objects.count(),0)
