"""Independent interpreters/connections for B6 locks, CAS and crash atomicity."""
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from django.db import connection
from django.test import TransactionTestCase
from apps.agent import matter_binding as binding, confirmations
from apps.patients.models import Pet
from . import test_b6_binding as fixtures


class B6ProcessTests(TransactionTestCase):
    setUp = fixtures.B6BindingTests.setUp
    inbound = fixtures.B6BindingTests.inbound
    context = fixtures.B6BindingTests.context
    turn = fixtures.B6BindingTests.turn
    start_matter = fixtures.B6BindingTests.start
    derived = fixtures.B6BindingTests.derived
    pending = fixtures.B6BindingTests.pending

    def start_process(self, mode, pet, message):
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'apps.agent.tests.b6_process',
            mode, str(self.conv.pk), str(self.goal.pk), str(self.goal.binding_revision),
            str(message.pk), str(pet.pk)], cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B6_'):
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
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def test_race_02_two_processes_one_revision_winner(self):
        self.start_matter()
        toby = Pet.objects.create(organization=self.org, owner=self.owner, name='Toby')
        messages = [self.inbound('Mejor Max'), self.inbound('Mejor Toby')]
        revision = self.goal.binding_revision
        processes = [self.start_process('race', pet, message)
                     for pet, message in zip((self.max, toby), messages)]
        for process in processes:
            self.barrier(process, 'B6_READY')
        for process in processes:
            self.release(process)
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=45)
            self.assertEqual(process.returncode, 0, stderr[-2000:])
            line = next(line for line in stdout.splitlines() if line.startswith('B6_RESULT '))
            results.append(json.loads(line.removeprefix('B6_RESULT ')))
        self.assertEqual(sum(result['won'] for result in results), 1)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.binding_revision, revision + 1)
        self.assertIn(self.goal.bound_pet_id, (self.max.pk, toby.pk))

    def test_fi_01_process_killed_before_commit_no_partial_invalidation(self):
        self.start_matter()
        self.derived('vaccine_facts')
        pending = self.pending()
        revision = self.goal.binding_revision
        proc = self.start_process('before_commit', self.max, self.inbound('Mejor Max'))
        self.barrier(proc, 'B6_READY')
        self.release(proc)
        self.barrier(proc, 'B6_CHANGED')
        proc.kill()
        proc.communicate(timeout=15)
        self.goal.refresh_from_db()
        self.conv.refresh_from_db()
        self.assertEqual(self.goal.binding_revision, revision)
        self.assertEqual(self.goal.bound_pet_id, self.luna.pk)
        self.assertIn('vaccine_facts', binding.values(self.goal))
        self.assertEqual(confirmations.get_pending(self.conv), pending)

    def test_fi_02_process_killed_after_commit_recovery_complete(self):
        self.start_matter()
        self.derived('vaccine_facts')
        self.pending()
        revision = self.goal.binding_revision
        proc = self.start_process('after_commit', self.max, self.inbound('Mejor Max'))
        self.barrier(proc, 'B6_READY')
        self.release(proc)
        self.barrier(proc, 'B6_COMMITTED')
        proc.kill()
        proc.communicate(timeout=15)
        self.goal.refresh_from_db()
        self.conv.refresh_from_db()
        self.assertEqual(self.goal.binding_revision, revision + 1)
        self.assertEqual(self.goal.bound_pet_id, self.max.pk)
        self.assertNotIn('vaccine_facts', binding.values(self.goal))
        self.assertIsNone(confirmations.get_pending(self.conv))
