"""Fresh clock after real mutex wait; B6 consumes the full corrected context."""
import json
import os
import site
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.agent import durable, services, matter_binding, matter_resolution
from apps.channels.models import Message
from . import test_w1_mono_processes as cases
from . import test_b6_binding as b6


class MonotonicLockClockTests(TransactionTestCase):
    setUp = cases.MonotonicProcessTests.setUp
    inbound = cases.MonotonicProcessTests.inbound
    record = cases.MonotonicProcessTests.record
    cleanup = cases.MonotonicProcessTests.cleanup
    read = cases.MonotonicProcessTests.read
    go = cases.MonotonicProcessTests.go
    result = cases.MonotonicProcessTests.result
    wait_blocked = cases.MonotonicProcessTests.wait_blocked

    def test_stale_prelock_app_time_cannot_reopen_ready_after_real_pg_wait(self):
        with transaction.atomic():
            from apps.agent.models import Conversation
            Conversation.objects.select_for_update().get(pk=self.conv.pk)
            env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                PYTHONPATH=os.pathsep.join(site.getsitepackages()), PYTHONIOENCODING='utf-8')
            proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
                'apps.agent.tests.w1_mono_clock_process', str(self.conv.pk)],
                cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            self.addCleanup(self.cleanup, proc)
            ready = self.read(proc, 'READY'); proc.backend_pid = ready['backend_pid']
            deadline = parse_datetime(ready['stale_app_time']) + timedelta(seconds=1)
            Message.objects.filter(pk=self.a.pk).update(available_at=deadline)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                holder = type('Holder', (), {'backend_pid': cursor.fetchone()[0]})()
            self.go(proc); self.wait_blocked(proc, holder)
        result = self.result(proc)
        self.assertGreaterEqual(parse_datetime(result['fresh_db_time']), deadline)
        self.assertEqual(Message.objects.get(pk=self.a.pk).available_at, deadline)
        b = Message.objects.get(pk=result['message'])
        self.assertEqual(b.available_at, deadline)
        witness = durable.claim_turn(self.conv.pk)
        self.assertEqual(durable.context_for_work(witness).inbound_ids, (self.a.pk, b.pk))
        self.record('READY_CAUSALITY', dict(stale_app_time=ready['stale_app_time'],
            deadline=deadline.isoformat(), fresh_db_time=result['fresh_db_time'],
            persisted_to_eligible_b_seconds=0, second_quiet_window=False,
            members=2, work=witness.turn_work_id))


class MonotonicBindingTests(TestCase):
    setUp = b6.B6BindingTests.setUp
    inbound = b6.B6BindingTests.inbound

    def test_preclaim_tomorrow_then_friday_changes_binding_before_any_proposal(self):
        Message.objects.filter(pk=self.m1.pk).update(status='processed')
        a = services.ingest_inbound_message(self.channel, wamid='mono-binding-a',
            wa_id='5215512345678', body='Quiero una cita para Luna mañana consulta general')
        Message.objects.filter(pk=a.pk).update(available_at=durable.db_now()-timedelta(seconds=1))
        b = services.ingest_inbound_message(self.channel, wamid='mono-binding-b',
            wa_id='5215512345678', body='No, mejor el viernes')
        witness = durable.claim_turn(self.conv.pk)
        context = durable.context_for_work(witness)
        self.assertEqual(context.inbound_ids, (a.pk, b.pk))
        matter_resolution.process_turn(self.conv, context)
        goal = matter_binding.current_goal(self.conv)
        friday = context.clinic_now.date() + timedelta(days=(4-context.clinic_now.weekday()) % 7 or 7)
        self.assertEqual(matter_binding.values(goal)['date'], friday.isoformat())
        self.assertEqual(goal.bound_pet_id, self.luna.pk)
        from apps.agent.models import ConversationOperation
        self.assertFalse(ConversationOperation.objects.exists())
