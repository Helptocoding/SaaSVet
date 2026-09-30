"""RACE-01..10 / FI-01..10: PostgreSQL decides; pipes only stage barriers."""
import json
import os
import site
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.agent import durable, services
from apps.agent.models import Conversation, HumanHandoff, TurnWork
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from . import test_b9a_processes as process_helpers


class MonotonicProcessTests(TransactionTestCase):
    cleanup = process_helpers.B9AProcessTests.cleanup
    read = process_helpers.B9AProcessTests.read
    go = process_helpers.B9AProcessTests.go
    result = process_helpers.B9AProcessTests.result
    kill = process_helpers.B9AProcessTests.kill

    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.org = Organization.objects.create(name='MONO-PG', timezone='UTC')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='mono-pg-channel')
        self.a = self.inbound('A')
        self.conv = self.a.conversation

    def record(self, kind, data):
        if os.environ.get('B8E_RESULTS_PATH'):
            path = Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.mono-processes.jsonl')
            with path.open('a', encoding='utf-8') as out:
                out.write(json.dumps(dict(test_id=self.id(), event=kind, **data)) + '\n')

    def inbound(self, key, phone='5215512345678', channel=None):
        msg = services.ingest_inbound_message(channel or self.channel, wamid=key,
            wa_id=phone, body='ordinary')
        Message.objects.filter(pk=msg.pk).update(available_at=durable.db_now() - timedelta(seconds=1))
        return msg

    def start(self, mode='claim', key='B', conv=None):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()),
            DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.w1_mono_process', mode, str(conv or self.conv.pk), key],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        ready = self.read(proc, 'READY')
        self.assertEqual(ready['pid'], proc.pid)
        proc.backend_pid = ready['backend_pid']
        return proc

    def run_child(self, mode='claim', key='B', conv=None):
        proc = self.start(mode, key, conv)
        self.go(proc)
        return self.result(proc)

    def locks(self, proc):
        with connection.cursor() as cursor:
            cursor.execute('SELECT relation::regclass::text, mode, granted FROM pg_locks WHERE pid=%s', [proc.backend_pid])
            locks = cursor.fetchall()
        self.assertTrue(any(r == 'agent_conversation' and granted for r, mode, granted in locks))
        self.record('PG_LOCKS', dict(backend_pid=proc.backend_pid, locks=locks))

    def wait_blocked(self, waiter, holder):
        end = time.monotonic() + 20
        while time.monotonic() < end:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_blocking_pids(%s)', [waiter.backend_pid])
                blockers = cursor.fetchone()[0]
            if holder.backend_pid in blockers:
                self.record('PG_BLOCKING', dict(waiter=waiter.backend_pid, blockers=blockers))
                return
            time.sleep(.02)
        self.fail('Independent ingest did not wait on the observed PostgreSQL mutex')

    def invariant(self):
        for msg in Message.objects.filter(direction='in').select_related('turn_work', 'conversation'):
            self.assertEqual(msg.organization_id, msg.conversation.organization_id)
            if msg.turn_work_id:
                self.assertEqual(msg.organization_id, msg.turn_work.organization_id)
                self.assertEqual(msg.conversation_id, msg.turn_work.conversation_id)
        for org in Organization.objects.all():
            self.assertLessEqual(durable.active_org_work(org.pk).count(), 1)
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_race_01_ingest_wins_ready_contains_a_b(self):
        ingest = self.start('ingest_hold'); self.go(ingest)
        self.read(ingest, 'BOUNDARY'); self.locks(ingest)
        self.assertIsNone(self.run_child()['work'])  # SKIP LOCKED, no ownership.
        self.go(ingest); b = self.result(ingest)['message']
        work = self.run_child()['work']
        self.assertEqual(list(Message.objects.filter(turn_work_id=work).order_by('created_at', 'id')
            .values_list('pk', flat=True)), [self.a.pk, b])
        self.invariant()

    def test_race_02_claim_wins_b_continuation(self):
        claim = self.start('claim_hold'); self.go(claim)
        boundary = self.read(claim, 'BOUNDARY'); self.locks(claim)
        ingest = self.start('ingest'); self.go(ingest)
        self.wait_blocked(ingest, claim)
        self.go(claim); first = self.result(claim)
        b = self.result(ingest)['message']
        work = TurnWork.objects.get(pk=first['work'])
        witness = durable.OwnershipWitness(self.org.pk, self.conv.pk, work.pk, work.lease_token, work.ownership_epoch)
        self.assertEqual(durable.context_for_work(witness).inbound_ids, (self.a.pk,))
        self.assertTrue(durable.has_new_input(work))
        durable.finalize_turn(witness, outputs=[{'body': 'obsolete'}])
        Message.objects.filter(pk=b).update(available_at=durable.db_now())
        second = self.run_child()['work']
        self.assertNotEqual(work.pk, second)
        self.assertEqual(list(Message.objects.filter(turn_work_id=second).values_list('pk', flat=True)), [b])
        self.invariant()

    def simultaneous(self, count, duplicate=False):
        procs = [self.start('ingest', key='DUP' if duplicate else f'B-{n}') for n in range(count)]
        for proc in procs: self.go(proc)
        results = [self.result(proc) for proc in procs]
        self.assertEqual(len({p.backend_pid for p in procs}), count)
        self.assertEqual(sum(r['message'] is not None for r in results), 1 if duplicate else count)
        work = self.run_child()['work']
        self.assertEqual(Message.objects.filter(direction='in').count(), 2 if duplicate else count + 1)
        self.assertEqual(Message.objects.filter(turn_work_id=work).count(), 2 if duplicate else count + 1)
        self.assertEqual(TurnWork.objects.count(), 1)
        self.invariant()

    def test_race_03_two_inbounds(self): self.simultaneous(2)
    def test_race_04_three_inbounds(self): self.simultaneous(3)
    def test_race_05_duplicate_inbound(self): self.simultaneous(2, duplicate=True)

    def test_race_06_fi_04_claim_crash_after_locks(self):
        proc = self.start('claim_locks'); self.go(proc)
        self.read(proc, 'BOUNDARY'); self.locks(proc); self.kill(proc)
        self.assertFalse(TurnWork.objects.exists())
        self.assertIsNone(Message.objects.get(pk=self.a.pk).turn_work_id)
        self.assertIsNotNone(self.run_child()['work'])
        self.invariant()

    def test_race_07_fi_06_07_restart_reclaims_same_members(self):
        proc = self.start('claim_live'); self.go(proc)
        work_id = self.read(proc, 'BOUNDARY')['work']; self.kill(proc)
        before = TurnWork.objects.get(pk=work_id)
        self.assertIsNone(self.run_child()['work'])
        TurnWork.objects.filter(pk=work_id).update(lease_expires_at=durable.db_now()-timedelta(seconds=1))
        after = self.run_child()
        self.assertEqual(after['work'], before.pk)
        self.assertNotEqual(after['token'], str(before.lease_token))
        self.assertEqual(TurnWork.objects.get(pk=work_id).attempts, 2)
        self.assertEqual(Message.objects.get(pk=self.a.pk).turn_work_id, work_id)
        self.invariant()

    def test_race_08_stale_worker_cannot_publish(self):
        proc = self.start('claim_live'); self.go(proc)
        work_id = self.read(proc, 'BOUNDARY')['work']
        TurnWork.objects.filter(pk=work_id).update(lease_expires_at=durable.db_now()-timedelta(seconds=1))
        self.assertEqual(self.run_child()['work'], work_id)
        self.go(proc); self.assertTrue(self.result(proc)['lost'])
        self.invariant()

    def test_race_09_two_conversations_same_org_n1(self):
        b = self.inbound('other', phone='5215512349999')
        procs = [self.start(conv=self.conv.pk), self.start(conv=b.conversation_id)]
        for proc in procs: self.go(proc)
        self.assertEqual(sum(self.result(proc)['work'] is not None for proc in procs), 1)
        self.assertEqual(Message.objects.filter(direction='in', turn_work__isnull=True).count(), 1)
        self.invariant()

    def test_race_10_two_organizations_independent(self):
        org = Organization.objects.create(name='MONO-OTHER', timezone='UTC')
        channel = ChannelAccount.objects.create(organization=org, external_account_id='mono-other')
        b = self.inbound('other', channel=channel)
        procs = [self.start(conv=self.conv.pk), self.start(conv=b.conversation_id)]
        for proc in procs: self.go(proc)
        self.assertEqual(sum(self.result(proc)['work'] is not None for proc in procs), 2)
        self.invariant()

    def rollback_ingest(self, mode):
        before = Message.objects.get(pk=self.a.pk).available_at
        proc = self.start(mode); self.go(proc)
        self.read(proc, 'BOUNDARY'); self.locks(proc); self.kill(proc)
        self.assertEqual(Message.objects.filter(direction='in').count(), 1)
        self.assertEqual(Message.objects.get(pk=self.a.pk).available_at, before)
        b = self.run_child('ingest')['message']
        work = self.run_child()['work']
        self.assertEqual(set(Message.objects.filter(turn_work_id=work).values_list('pk', flat=True)), {self.a.pk, b})
        self.invariant()

    def test_fi_01_crash_before_persist(self): self.rollback_ingest('ingest_before_save')
    def test_fi_02_crash_after_persist_before_deadlines(self): self.rollback_ingest('ingest_after_save')
    def test_fi_03_crash_after_deadlines_before_commit(self): self.rollback_ingest('ingest_after_deadlines')

    def test_fi_05_lost_commit_response_redelivery_deduplicates(self):
        proc = self.start('ingest_lost_commit'); self.go(proc)
        self.read(proc, 'BOUNDARY'); self.kill(proc)
        self.assertEqual(Message.objects.filter(direction='in').count(), 2)
        self.assertIsNone(self.run_child('ingest')['message'])
        work = self.run_child()['work']
        self.assertEqual(Message.objects.filter(turn_work_id=work).count(), 2)
        self.invariant()

    def test_fi_08_retry_keeps_work_members_and_attempts(self):
        witness = durable.claim_turn(self.conv.pk)
        durable.fail_turn(witness, reason='injected_retry')
        self.run_child('ingest')
        TurnWork.objects.filter(pk=witness.turn_work_id).update(next_attempt_at=durable.db_now())
        self.assertEqual(self.run_child()['work'], witness.turn_work_id)
        self.assertEqual(Message.objects.filter(turn_work_id=witness.turn_work_id).count(), 1)
        self.assertEqual(TurnWork.objects.get(pk=witness.turn_work_id).attempts, 2)
        self.invariant()

    def test_fi_09_concurrent_takeover_fences_live_worker(self):
        from rest_framework.test import APIClient
        from .test_inbox_api import _make_user
        proc = self.start('claim_live'); self.go(proc); self.read(proc, 'BOUNDARY')
        client = APIClient()
        client.force_authenticate(_make_user('mono-pg-human', self.org, 'ADMIN'))
        self.assertEqual(client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/').status_code, 200)
        self.go(proc); self.assertTrue(self.result(proc)['lost'])
        self.invariant()

    @override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
    def test_fi_10_safety_while_live_worker_preserves_continuation(self):
        proc = self.start('claim_live'); self.go(proc); self.read(proc, 'BOUNDARY')
        signal = services.ingest_inbound_message(self.channel, wamid='urgent',
            wa_id='5215512345678', body='Mi perro está convulsionando ahora')
        self.go(proc); self.result(proc)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertIsNone(Message.objects.get(pk=signal.pk).turn_work_id)
        from apps.agent import worker
        worker.process_pending_conversations(batch=1)
        self.assertTrue(HumanHandoff.objects.exists())
        self.assertTrue(Message.objects.filter(semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE).exists())
        self.assertLessEqual(durable.active_org_work(self.org.pk).count(), 1)
