"""E4 observation races with separate processes and PostgreSQL connections."""
import json
import os
import site
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase

from apps.agent import durable
from apps.agent.models import LLMCall, TurnWork
from apps.channels.models import Message
from . import test_e4_claim_yield as e4, test_b9a_processes as b9ap, test_b9c_processes as b9cp


class E4SQLProcessTests(TransactionTestCase):
    setUp = e4.E4ClaimYieldTests.setUp
    inbound = e4.E4ClaimYieldTests.inbound
    pair = e4.E4ClaimYieldTests.pair
    cleanup = b9ap.B9AProcessTests.cleanup
    read = b9ap.B9AProcessTests.read
    record = b9cp.B9CProcessTests.record

    def start(self):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict,default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-X','utf8','-m',
            'apps.agent.tests.e4_sql_process'],cwd=Path(__file__).resolve().parents[3],env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.addCleanup(self.cleanup,proc)
        proc.backend_pid = self.read(proc,'READY')['backend_pid']
        return proc

    def send(self, proc, action, kind, now=None, **kwargs):
        proc.stdin.write(json.dumps(dict(action=action,now=now.isoformat() if now else None,**kwargs))+'\n')
        proc.stdin.flush()
        result = self.read(proc,kind)
        self.assertEqual(result.get('admissions',0),0)
        self.assertTrue(all(n<=1 for n in result.get('active',{}).values()),result)
        return result

    def observers(self, now):
        a,b = self.start(),self.start()
        self.assertNotEqual(a.pid,b.pid)
        self.assertNotEqual(a.backend_pid,b.backend_pid)
        before = TurnWork.objects.count()
        left = self.send(a,'observe','OBSERVED',now)
        right = self.send(b,'observe','OBSERVED',now)
        self.assertEqual((left['ids'],left['org_ids']),(right['ids'],right['org_ids']))
        self.assertEqual(TurnWork.objects.count(),before)
        self.assertEqual(LLMCall.objects.count(),0)
        return a,b,left['ids']

    def finish(self, *processes):
        for proc in processes:
            self.send(proc,'finalize','FINALIZED')
            self.send(proc,'exit','RESULT')
            _,error = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode,0,error)

    def test_sql_proc_01_same_candidate_miss_and_distinct_org_fallback(self):
        _,_,ready,future,clock = self.pair(prior_healthy=True)
        due = clock+timedelta(seconds=1)
        a,b,ids = self.observers(due)
        self.assertEqual(ids,[future.conversation_id,ready.conversation_id])
        self.assertTrue(self.send(a,'claim','CLAIMED',due,conversation=ids[0])['claimed'])
        self.assertFalse(self.send(b,'claim','CLAIMED',due,conversation=ids[0])['claimed'])
        self.assertTrue(self.send(b,'claim','CLAIMED',due,conversation=ids[1])['claimed'])
        self.finish(a,b)

    def test_sql_proc_02_org_slot_occupied_after_observation(self):
        org,_,ready,future,clock = self.pair(prior_healthy=True)
        due = clock+timedelta(seconds=1)
        a,b,ids = self.observers(due)
        parent = durable.claim_turn(future.conversation_id,eligible_at=due)
        self.assertIsNotNone(parent)
        self.assertFalse(self.send(a,'claim','CLAIMED',due,conversation=ids[0])['claimed'])
        self.assertTrue(self.send(b,'claim','CLAIMED',due,conversation=ready.conversation_id)['claimed'])
        self.assertEqual(durable.active_org_work(org.pk).count(),1)
        durable.finalize_turn(parent)
        self.finish(a,b)

    def test_sql_proc_03_candidate_disappears_after_observation(self):
        _,_,ready,future,clock = self.pair(prior_healthy=True)
        due = clock+timedelta(seconds=1)
        a,b,ids = self.observers(due)
        Message.objects.filter(pk=future.pk).update(status=Message.STATUS_DISCARDED)
        self.assertFalse(self.send(a,'claim','CLAIMED',due,conversation=ids[0])['claimed'])
        self.assertFalse(self.send(b,'claim','CLAIMED',due,conversation=ids[0])['claimed'])
        self.assertTrue(self.send(a,'claim','CLAIMED',due,conversation=ready.conversation_id)['claimed'])
        self.assertFalse(self.send(b,'claim','CLAIMED',due,conversation=ready.conversation_id)['claimed'])
        self.finish(a,b)

    def test_sql_proc_04_safety_arrival_and_deadline_crossing(self):
        _,_,ready,future,clock = self.pair(prior_healthy=True)
        a,b,ids = self.observers(clock)
        self.assertEqual(ids,[])
        Message.objects.filter(pk=ready.pk).update(semantic_type=Message.SEMANTIC_SAFETY_SIGNAL)
        self.assertEqual(self.send(a,'observe','OBSERVED',clock)['ids'],[ready.conversation_id])
        self.assertTrue(self.send(a,'claim','CLAIMED',clock,conversation=ready.conversation_id)['claimed'])
        self.assertEqual(self.send(b,'observe','OBSERVED',clock)['ids'],[])
        self.send(a,'finalize','FINALIZED')
        due = clock+timedelta(seconds=1)
        self.assertEqual(self.send(b,'observe','OBSERVED',due)['ids'],[future.conversation_id])
        self.assertTrue(self.send(b,'claim','CLAIMED',due,conversation=future.conversation_id)['claimed'])
        self.finish(a,b)

    def test_sql_proc_05_ordinary_join_preserves_ready_and_claim_membership(self):
        _,_,ready,future,clock = self.pair(prior_healthy=True)
        deadline = clock-timedelta(seconds=1)
        Message.objects.filter(pk=ready.pk).update(available_at=deadline)
        Message.objects.filter(pk=future.pk).update(status=Message.STATUS_DISCARDED)
        a,b,ids = self.observers(clock)
        self.assertEqual(ids,[ready.conversation_id])
        joined = self.h.inbound('synthetic ordinary input',wa_id='5215512340002')
        ready.refresh_from_db(); joined.refresh_from_db()
        self.assertEqual((ready.available_at,joined.available_at),(deadline,deadline))
        result = self.send(a,'claim','CLAIMED',clock,conversation=ready.conversation_id)
        self.assertTrue(result['claimed'])
        self.assertEqual(set(result['members']),{ready.pk,joined.pk})
        self.assertFalse(self.send(b,'claim','CLAIMED',clock,conversation=ready.conversation_id)['claimed'])
        self.finish(a,b)
