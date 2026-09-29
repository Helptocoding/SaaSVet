"""PostgreSQL process races. Threads read stdout only; never execute business."""
import json
import os
import site
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

import django
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from apps.agent import durable, goals
from apps.agent.models import ConversationGoal, TurnWork
from apps.patients.models import Pet, Owner, PetRegistrationEffect
from apps.users.models import User
from .b8e_support import RegistrationFixtures


class ProcessEvidence(list):
    def append(self, item):
        super().append(item)
        if os.environ.get('B8E_RESULTS_PATH'):
            with Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.processes.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(item)+'\n')


PROCESS_RESULTS = ProcessEvidence()


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8EProcessTests(RegistrationFixtures, TransactionTestCase):
    def snapshot(self):
        return {'witness': asdict(self.witness), 'operation_key': self.op.operation_key,
            'goal_id': self.goal.pk, 'contact_id': self.conv.contact_id, 'django_version': django.get_version()}

    def start_process(self, mode, args=None):
        self.assertEqual(connection.vendor, 'postgresql')
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()))
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8',
            '-m', 'apps.agent.tests.b8e_process', mode, json.dumps(args or self.snapshot(), default=str)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        self.barrier(proc, 'READY')
        PROCESS_RESULTS.append({'test_id': self.id(), 'mode': mode, 'pid': proc.pid})
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None: proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B8E_'): return line.strip()
            return ''
        with ThreadPoolExecutor(max_workers=1) as pool:
            try: actual = pool.submit(read).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        if not actual: self.fail('Worker exited: '+proc.stderr.read()[-2500:])
        self.assertEqual(actual, 'B8E_'+expected)

    @staticmethod
    def release(proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-2500:])
        result = json.loads(next(line.removeprefix('B8E_RESULT ') for line in stdout.splitlines()
            if line.startswith('B8E_RESULT ')))
        PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'result': result})
        return result

    def blocked(self, proc):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s', ['b8e_'+str(proc.pid)])
                if ('Lock',) in cursor.fetchall():
                    PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'postgres_wait': 'Lock'})
                    return
            time.sleep(.02)
        self.fail('No PostgreSQL lock wait observed')

    def reclaim(self):
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()
        self.context = replace(self.context, witness=self.witness)

    def second_operation(self, *, different_owner=False, different_data=False):
        saved = dict(self.__dict__)
        self.wa_id = '5215512340002'
        self.conv = self.inbound('Registrar otra mascota').conversation
        if different_owner: self.owner = Owner.objects.create(organization=self.org, name='Owner Two', phone='5512340002')
        contact = self.conv.contact
        contact.owner, contact.verification_level, contact.verified_at = self.owner, 'staff_verified', timezone.now()
        contact.save()
        from .b9c_legacy_fixture import legacy_parallel_domain_claim
        self.claim = lambda: legacy_parallel_domain_claim(self, self.conv)
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv, name=goals.ADD_PET_ONLY)
        self.change({'owner': self.owner.pk})
        self.pet_data(name='Sol' if different_data else 'Nala')
        self.authorized()
        data = self.snapshot()
        self.__dict__.update(saved)
        if 'claim' not in saved: del self.claim
        if 'wa_id' not in saved: del self.wa_id
        return data

    def test_same_operation_two_workers(self):
        self.authorized()
        first = self.start_process('hold_effect')
        self.release(first)
        self.barrier(first, 'ATTEMPTING'); self.barrier(first, 'EFFECT_PENDING')
        second = self.start_process('execute')
        self.release(second); self.barrier(second, 'ATTEMPTING'); self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual((a['status'], b['status']), ('SUCCEEDED', 'SUCCEEDED'))
        self.assertEqual(a['evidence'], b['evidence'])
        self.assertTrue(b['duplicate'])
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def distinct_operations(self, different_owner=False, different_data=False):
        self.authorized()
        second_args = self.second_operation(different_owner=different_owner, different_data=different_data)
        first = self.start_process('hold_effect')
        self.release(first); self.barrier(first, 'ATTEMPTING'); self.barrier(first, 'EFFECT_PENDING')
        second = self.start_process('execute', second_args)
        self.release(second)
        # Must commit while the first still holds org/owner shared locks.
        b = self.result(second)
        self.assertEqual(b['status'], 'SUCCEEDED', b)
        self.release(first)
        a = self.result(first)
        self.assertEqual(a['status'], 'SUCCEEDED', a)
        self.assertNotEqual(a['evidence']['domain_object_id'], b['evidence']['domain_object_id'])
        self.assertEqual(PetRegistrationEffect.objects.count(), 2)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+2)

    def test_same_owner_different_data(self): self.distinct_operations(different_data=True)
    def test_identical_data_distinct_operations(self): self.distinct_operations()
    def test_different_owners_parallel(self): self.distinct_operations(different_owner=True)

    def crash(self, mode, boundary):
        self.authorized()
        proc = self.start_process(mode)
        self.release(proc); self.barrier(proc, 'ATTEMPTING'); self.barrier(proc, boundary)
        self.assertFalse(PetRegistrationEffect.objects.exists())
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)
        self.reclaim()
        recovery = self.start_process('execute')
        self.release(recovery)
        result = self.result(recovery)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)

    def committed_retry(self, modified=False):
        self.authorized()
        proc = self.start_process('after_commit')
        self.release(proc); self.barrier(proc, 'ATTEMPTING'); self.barrier(proc, 'COMMITTED')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        if modified:
            pet = self.created_pet()
            pet.name, pet.sex = 'Sol', 'male'
            pet.save()
        self.reclaim()
        retry = self.start_process('execute')
        self.release(retry)
        result = self.result(retry)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertTrue(result['duplicate'])
        self.assertEqual(self.created_pet().name, 'Sol' if modified else 'Nala')
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_crash_after_commit(self): self.committed_retry()
    def test_retry_after_modification(self): self.committed_retry(True)

    def test_lost_commit_acknowledgement_is_uncertain_and_reconciles(self):
        self.authorized()
        proc = self.start_process('commit_db_error')
        self.release(proc)
        result = self.result(proc)
        self.assertEqual(result['status'], 'UNCERTAIN', result)
        self.assertTrue(result['reconciliation_required'])
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        retry = self.start_process('execute')
        self.release(retry)
        result = self.result(retry)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertTrue(result['duplicate'])
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def change_race(self, action, effect_first):
        self.authorized()
        first = self.start_process('hold_effect' if effect_first else 'hold_'+action)
        self.release(first)
        if effect_first: self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING' if effect_first else 'CHANGED')
        second = self.start_process(action if effect_first else 'execute')
        self.release(second)
        if not effect_first: self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual((a if effect_first else b)['status'], 'SUCCEEDED' if effect_first else 'DENIED')
        self.assertTrue((b if effect_first else a)['changed'])
        self.assertEqual(PetRegistrationEffect.objects.count(), int(effect_first))
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+int(effect_first))

    def test_human_parallel_equivalent(self):
        self.authorized()
        human = User.objects.create(organization=self.org, username='human-process', role='ADMIN', is_staff=True)
        first = self.start_process('hold_effect')
        self.release(first); self.barrier(first, 'ATTEMPTING'); self.barrier(first, 'EFFECT_PENDING')
        other = self.start_process('human', {**self.snapshot(), 'human_id': human.pk,
            'human_payload': {'name': 'Nala', 'owner_public_id': str(self.owner.public_id)}})
        self.release(other)
        result = self.result(other)
        self.assertEqual(result['status_code'], 201, result)
        self.release(first)
        self.assertEqual(self.result(first)['status'], 'SUCCEEDED')
        self.assertNotEqual(self.created_pet().pk, result['pet_id'])
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+2)

    def test_owner_phone_edit_first_avoids_identity_lock_cycle(self):
        self.authorized()
        editor = self.start_process('hold_owner_phone')
        self.release(editor); self.barrier(editor, 'OWNER_EDIT_LOCKED')
        agent = self.start_process('before_locks')
        self.release(agent)
        self.barrier(agent, 'ATTEMPTING'); self.barrier(agent, 'BEFORE_LOCKS')
        self.release(editor)
        # The real Owner post_save signal waits for the B8A ContactIdentity lock.
        self.blocked(editor)
        self.release(agent)
        result = self.result(agent)
        self.assertEqual(result['status'], 'DENIED', result)
        self.assertEqual(result['reason'], 'precondition_infrastructure', result)
        self.assertTrue(self.result(editor)['changed'])
        self.conv.contact.refresh_from_db()
        self.assertIsNone(self.conv.contact.owner_id)
        self.assertFalse(PetRegistrationEffect.objects.exists())
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)

    def test_owner_phone_edit_after_effect_preserves_pet(self):
        self.authorized()
        agent = self.start_process('hold_effect')
        self.release(agent)
        self.barrier(agent, 'ATTEMPTING'); self.barrier(agent, 'EFFECT_PENDING')
        editor = self.start_process('owner_phone')
        self.release(editor); self.blocked(editor)
        self.release(agent)
        self.assertEqual(self.result(agent)['status'], 'SUCCEEDED')
        self.assertTrue(self.result(editor)['changed'])
        self.conv.contact.refresh_from_db()
        self.assertIsNone(self.conv.contact.owner_id)
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_human_commits_equivalent_after_consent_before_agent(self):
        self.authorized()
        human = User.objects.create(organization=self.org, username='human-before', role='ADMIN', is_staff=True)
        process = self.start_process('human', {**self.snapshot(), 'human_id': human.pk,
            'human_payload': {'name': 'Nala', 'owner_public_id': str(self.owner.public_id)}})
        self.release(process)
        manual = self.result(process)
        self.assertEqual(manual['status_code'], 201, manual)
        self.assertFalse(PetRegistrationEffect.objects.exists())
        agent = self.start_process('execute')
        self.release(agent)
        result = self.result(agent)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertNotEqual(self.created_pet().pk, manual['pet_id'])
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+2)

    def test_evidence_concurrent_unique_constraint(self):
        self.authorized()
        first = self.start_process('hold_effect')
        self.release(first); self.barrier(first, 'ATTEMPTING'); self.barrier(first, 'EFFECT_PENDING')
        other = self.start_process('evidence')
        self.release(other); self.blocked(other)
        self.release(first)
        self.assertEqual(self.result(first)['status'], 'SUCCEEDED')
        result = self.result(other)
        self.assertEqual(result['error'], 'IntegrityError', result)
        self.assertIn('operation_id', result['constraint'])
        self.assertEqual(PetRegistrationEffect.objects.count(), 1)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets+1)

    def test_evidence_sql_error(self):
        self.authorized()
        proc = self.start_process('evidence_db_error')
        self.release(proc)
        result = self.result(proc)
        self.assertEqual(result['status'], 'UNCERTAIN', result)
        self.assertEqual(Pet.all_objects.count(), self.initial_pets)
        retry = self.start_process('execute')
        self.release(retry)
        self.assertEqual(self.result(retry)['status'], 'UNCERTAIN')


def case(method, *args):
    def test(self): return getattr(self, method)(*args)
    return test


for mode, boundary in [('before_locks', 'BEFORE_LOCKS'), ('after_owner', 'OWNER_LOCKED'),
        ('after_insert', 'INSERTED'), ('after_evidence', 'EVIDENCE_PENDING')]:
    setattr(B8EProcessTests, 'test_crash_'+mode, case('crash', mode, boundary))
for action in ('correction', 'revocation', 'takeover', 'binding', 'identity', 'handoff'):
    for effect_first in (False, True):
        setattr(B8EProcessTests, f'test_{action}_effect_first_{effect_first}', case('change_race', action, effect_first))
