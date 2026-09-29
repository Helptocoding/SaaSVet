"""Real multi-process PostgreSQL acceptance; threads only read child stdout."""
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
from uuid import uuid4

import django
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from apps.agent import durable, goals, matter_binding, sender
from apps.agent.models import ConversationGoal, TurnWork, ToolExecution, AgentSettings
from apps.appointments.models import Appointment
from apps.users.models import User
from .b8b_support import AppointmentExecutionFixtures, enabled_create


PROCESS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8BProcessTests(AppointmentExecutionFixtures, TransactionTestCase):
    def snapshot(self):
        return {'witness': asdict(self.witness), 'operation_key': self.op.operation_key,
                'goal_id': self.goal.pk, 'contact_id': self.conv.contact_id,
                'django_version': django.get_version()}

    def start_process(self, mode, args=None):
        self.assertEqual(connection.vendor, 'postgresql')
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()))
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8',
            '-m', 'apps.agent.tests.b8b_process', mode, json.dumps(args or self.snapshot(), default=str)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        self.barrier(proc, 'READY')
        PROCESS_RESULTS.append({'test_id': self.id(), 'mode': mode, 'pid': proc.pid})
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B8B_'):
                    return line.strip()
            return ''
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                actual = pool.submit(read).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        if not actual:
            self.fail('Child exited before barrier: ' + proc.stderr.read()[-3000:])
        self.assertEqual(actual, 'B8B_' + expected)

    @staticmethod
    def release(proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-3000:])
        result = json.loads(next(x.removeprefix('B8B_RESULT ') for x in stdout.splitlines()
                                 if x.startswith('B8B_RESULT ')))
        PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'result': result})
        return result

    def blocked(self, proc):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',
                               ['b8b_' + str(proc.pid)])
                rows = cursor.fetchall()
            if ('Lock',) in rows:
                PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'postgres_wait': 'Lock'})
                return
            time.sleep(.02)
        self.fail('Independent process did not actually wait on a PostgreSQL lock')

    def reclaim(self):
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.witness = self.claim()
        self.context = replace(self.context, witness=self.witness)

    def second_operation(self, *, start='10:00', end='10:30', different_vet=False, same_pet=False):
        # Independent conversation AND ContactIdentity: contention below cannot
        # accidentally be serialized by B8A's conversation/identity lock.
        saved = dict(self.__dict__)
        self.wa_id = '5215512340002'
        message = self.inbound('Otra cita')
        self.conv = message.conversation
        contact = self.conv.contact
        contact.owner = self.owner
        contact.verification_level = 'staff_verified'
        contact.verified_at = timezone.now()
        contact.save()
        from .b9c_legacy_fixture import legacy_parallel_domain_claim
        self.claim = lambda: legacy_parallel_domain_claim(self, self.conv)
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
                                                    name=goals.SCHEDULE)
        self.change({'owner': self.owner.pk, 'pet': (self.luna if same_pet else self.max).pk,
                     'date': self.day, 'time': start, 'reason': 'consulta', 'service': 'consulta'})
        matter_binding.record_derived(self.goal, self.conv, 'selected_slot',
            {'date': self.day, 'time': start, 'end_time': end, 'available': True},
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=matter_binding.snapshot(self.goal), tool='check_appointment_slot',
            observed_at=timezone.now())
        if different_vet:
            other = User.objects.create(organization=self.org, username='b8b-other', role='VET')
            AgentSettings.objects.update_or_create(organization=self.org,
                                                   defaults={'default_veterinarian': other})
        self.authorized()
        snapshot = self.snapshot()
        self.__dict__.update(saved)
        if 'claim' not in saved:
            del self.claim
        if 'wa_id' not in saved:
            del self.wa_id
        self.assertNotEqual(snapshot['contact_id'], self.conv.contact_id)
        self.assertNotEqual(snapshot['witness']['conversation_id'], self.conv.pk)
        self.assertNotEqual(snapshot['operation_key'], self.op.operation_key)
        return snapshot

    def test_idem02_fi05_same_operation_one_durable_effect(self):
        self.authorized()
        first = self.start_process('hold_effect')
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING')
        second = self.start_process('execute')
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.assertEqual(Appointment.objects.count(), 0)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual([a['status'], b['status']], ['SUCCEEDED', 'SUCCEEDED'])
        self.assertTrue(b['duplicate'])
        self.assertEqual(a['evidence'], b['evidence'])
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)
        from .test_b8b_corpus import domain_metrics
        metrics = domain_metrics(1)
        self.assertTrue(all(value == 0 for value in metrics.values()), metrics)
        PROCESS_RESULTS.append({'test_id': self.id(), 'corpus_id': 'CA19', **metrics})

    def competing_operations(self, *, start='10:00', end='10:30', same_pet=False, raw=False):
        self.authorized()
        other = self.second_operation(start=start, end=end, same_pet=same_pet)
        first = self.start_process('hold_raw_constraint' if raw else 'hold_effect')
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'INSERTED' if raw else 'EFFECT_PENDING')
        second = self.start_process('raw_constraint' if raw else 'execute', other)
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.assertEqual(Appointment.objects.count(), 0)
        self.release(first)
        a, b = self.result(first), self.result(second)
        if raw:
            self.assertTrue(a['created'])
            self.assertEqual(b, {'error': 'IntegrityError', 'constraint': 'appointment_no_overlap_per_vet'})
        else:
            self.assertEqual(a['status'], 'SUCCEEDED')
            self.assertEqual((b['status'], b['reason']), ('DENIED', 'slot_unavailable'))
        self.assertEqual(Appointment.objects.count(), 1)
        from .test_b8b_corpus import domain_metrics
        metrics = domain_metrics(1)  # raw=True deliberately inserts one domain fixture
        self.assertTrue(all(value == 0 for value in metrics.values()), metrics)
        corpus_id = 'CA20' if self._testMethodName == 'test_conflict01_fi06_distinct_operations_same_slot' else None
        PROCESS_RESULTS.append({'test_id': self.id(), 'corpus_id': corpus_id, **metrics})

    def test_conflict01_fi06_distinct_operations_same_slot(self):
        self.competing_operations()

    def test_conflict02_identical_parameters_distinct_keys_are_not_replays(self):
        self.competing_operations(same_pet=True)

    def test_overlap_anterior_between_independent_processes(self):
        self.competing_operations(start='09:45', end='10:15')

    def test_overlap_posterior_between_independent_processes(self):
        self.competing_operations(start='10:15', end='10:45')

    def test_constraint_itself_rejects_partial_overlap_without_app_locks(self):
        self.competing_operations(start='10:15', end='10:45', raw=True)

    def test_conflict03_different_vets_can_commit_same_interval(self):
        self.authorized()
        other = self.second_operation(different_vet=True)
        first = self.start_process('hold_effect')
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING')
        second = self.start_process('execute', other)
        self.release(second)
        b = self.result(second)  # must finish while first still holds its resource
        self.assertEqual(b['status'], 'SUCCEEDED', b)
        self.assertEqual(Appointment.objects.count(), 1)
        self.release(first)
        self.assertEqual(self.result(first)['status'], 'SUCCEEDED')
        self.assertEqual(Appointment.objects.count(), 2)

    def change_wins(self, mode):
        self.authorized()
        changing = self.start_process('hold_' + mode)
        self.release(changing)
        self.barrier(changing, 'CHANGED')
        executing = self.start_process('execute')
        self.release(executing)
        self.barrier(executing, 'ATTEMPTING')
        self.blocked(executing)
        self.release(changing)
        self.assertTrue(self.result(changing)['changed'])
        self.assertEqual(self.result(executing)['status'], 'DENIED')
        self.assertEqual(Appointment.objects.count(), 0)

    def effect_wins(self, mode):
        self.authorized()
        executing = self.start_process('hold_effect')
        self.release(executing)
        self.barrier(executing, 'ATTEMPTING')
        self.barrier(executing, 'EFFECT_PENDING')
        changing = self.start_process(mode)
        self.release(changing)
        self.blocked(changing)
        self.release(executing)
        self.assertEqual(self.result(executing)['status'], 'SUCCEEDED')
        self.assertTrue(self.result(changing)['changed'])
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Appointment.objects.get().start_time.strftime('%H:%M'), '10:00')

    def test_fi07_correction_first(self): self.change_wins('correction')
    def test_correction_after_commit_is_not_reschedule(self): self.effect_wins('correction')
    def test_fi08_takeover_first(self): self.change_wins('takeover')
    def test_takeover_after_commit_keeps_appointment(self): self.effect_wins('takeover')
    def test_revocation_first(self): self.change_wins('revocation')
    def test_revocation_after_commit_keeps_appointment(self): self.effect_wins('revocation')
    def test_permission_revocation_first(self): self.change_wins('permission')
    def test_permission_revocation_after_commit_keeps_appointment(self): self.effect_wins('permission')

    def crash_before_commit(self, mode, boundary):
        self.authorized()
        process = self.start_process(mode)
        self.release(process)
        self.barrier(process, 'ATTEMPTING')
        self.barrier(process, boundary)
        self.assertEqual(Appointment.objects.count(), 0)
        self.cleanup(process)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 0)
        self.reclaim()
        recovery = self.start_process('execute')
        self.release(recovery)
        self.assertEqual(self.result(recovery)['status'], 'SUCCEEDED')
        self.assertEqual(Appointment.objects.count(), 1)

    def test_fi01_crash_after_guard_before_availability(self):
        self.crash_before_commit('before_availability', 'BEFORE_AVAILABILITY')

    def test_fi02_crash_after_resource_lock(self):
        self.crash_before_commit('after_resource', 'RESOURCE_LOCKED')

    def test_fi03_crash_after_insert_before_commit(self):
        self.crash_before_commit('after_insert', 'INSERTED')

    def committed_crash(self, mode, boundary):
        self.authorized()
        process = self.start_process(mode)
        self.release(process)
        self.barrier(process, 'ATTEMPTING')
        self.barrier(process, boundary)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        appt = Appointment.objects.get(source_operation_id=self.op.operation_key)
        self.cleanup(process)
        self.reclaim()
        recovery = self.start_process('execute')
        self.release(recovery)
        result = self.result(recovery)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['evidence']['domain_object_id'], str(appt.public_id))
        self.assertEqual(Appointment.objects.count(), 1)

    def test_recovery_after_success_in_independent_process(self):
        self.committed_crash('after_commit', 'COMMITTED')

    def test_fi04_crash_in_real_cache_on_commit_preserves_business(self):
        self.committed_crash('on_commit_crash', 'ON_COMMIT')

    def test_fi09_real_database_error_in_independent_worker(self):
        self.authorized()
        process = self.start_process('db_error')
        self.release(process)
        self.assertEqual(self.result(process)['status'], 'UNCERTAIN')
        self.assertFalse(Appointment.objects.exists())
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'UNCERTAIN')
