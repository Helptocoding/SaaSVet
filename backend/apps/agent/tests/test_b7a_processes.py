"""B7A concurrency uses independent interpreters and PostgreSQL connections."""
import json
import os
import subprocess
import sys
from pathlib import Path
from dataclasses import asdict
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from apps.agent.models import ConversationOperation, TurnWork
from .test_b7a_operations import OperationFixtures


class B7AProcessTests(OperationFixtures, TransactionTestCase):
    def start_process(self, mode='prepare'):
        args = dict(witness=asdict(self.witness), goal_id=self.goal.pk,
            capability='create_appointment', expected_binding_revision=self.goal.binding_revision,
            expected_identity_revision=self.conv.contact.authorization_revision)
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'apps.agent.tests.b7a_process',
            mode, json.dumps(args, default=str)], cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        self.barrier(proc, 'B7A_READY')
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B7A_'):
                    return line.strip()
            return ''
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                actual = pool.submit(read).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        self.assertEqual(actual, expected)

    def release(self, proc):
        proc.stdin.write('go\n'); proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-4000:])
        row = next(line for line in stdout.splitlines() if line.startswith('B7A_RESULT '))
        return json.loads(row.removeprefix('B7A_RESULT '))

    def test_duplicate_preparation_two_processes_one_operation(self):
        processes = [self.start_process(), self.start_process()]
        for proc in processes:
            self.release(proc)
        rows = [self.result(proc) for proc in processes]
        self.assertEqual(rows[0]['pk'], rows[1]['pk'])
        self.assertEqual(ConversationOperation.objects.count(), 1)

    def test_concurrent_replacement_two_processes_one_current(self):
        old = self.prepare()
        self.next_turn()
        self.change({'time': '11:00'})
        self.observe_slot()
        processes = [self.start_process(), self.start_process()]
        for proc in processes:
            self.release(proc)
        rows = [self.result(proc) for proc in processes]
        self.assertEqual(rows[0]['pk'], rows[1]['pk'])
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'INVALIDATED')
        current = ConversationOperation.objects.get(consent_state='PENDING')
        self.assertEqual(current.replaces_id, old.pk)
        self.assertEqual(current.binding_revision, self.goal.binding_revision)

    def test_fi01_kill_after_validation_before_persistence(self):
        proc = self.start_process('before_persist')
        self.release(proc)
        self.barrier(proc, 'B7A_VALIDATED')
        proc.kill(); proc.communicate(timeout=15)
        self.assertFalse(ConversationOperation.objects.exists())
        self.assertEqual(self.prepare().pk, self.prepare().pk)

    def test_fi02_kill_after_persistence_before_output(self):
        proc = self.start_process('after_persist')
        self.release(proc)
        self.barrier(proc, 'B7A_COMMITTED')
        proc.kill(); proc.communicate(timeout=15)
        original = ConversationOperation.objects.get()
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(
            lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()
        self.assertEqual(self.prepare().pk, original.pk)
        self.assertIsNone(original.proposal_message_id)

    def test_fi04_revision_wins_before_waiting_preparation(self):
        old = self.prepare()
        self.next_turn()
        proc = self.start_process()
        self.change({'pet': self.max.pk})
        self.release(proc)
        self.assertIn('binding_revision_stale', self.result(proc)['denied'])
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'INVALIDATED')
        self.assertFalse(ConversationOperation.objects.filter(consent_state='PENDING').exists())

    def race_after_validation(self, mode):
        prepare = self.start_process('hold_preparation')
        self.release(prepare)
        self.barrier(prepare, 'B7A_VALIDATED')
        changing = self.start_process(mode)
        self.release(changing)
        self.release(prepare)
        self.result(prepare)
        self.result(changing)
        self.assertFalse(ConversationOperation.objects.filter(consent_state='PENDING').exists())
        self.assertFalse(ConversationOperation.objects.exclude(consent_state='INVALIDATED').exists())
        self.assertFalse(ConversationOperation.objects.exclude(proposal_message=None).exists())

    def test_fi05_identity_change_during_preparation_invalidates(self):
        self.race_after_validation('identity')

    def test_fi06_takeover_during_preparation_no_proposal_or_authorization(self):
        self.race_after_validation('takeover')
