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
from .b8c_support import MutationFixtures, enabled_mutations


class ProcessEvidence(list):
    def append(self, item):
        super().append(item)
        # Preserve real PID/barrier evidence even if the parent host is stopped.
        path = os.environ.get('B8C_RESULTS_PATH')
        if path:
            with Path(path).with_suffix('.processes.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(item) + '\n')


PROCESS_RESULTS = ProcessEvidence()


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8CProcessTests(MutationFixtures, TransactionTestCase):
    def snapshot(self):
        return {'witness': asdict(self.witness), 'operation_key': self.op.operation_key,
                'goal_id': self.goal.pk, 'contact_id': self.conv.contact_id,
                'django_version': django.get_version(), 'kind': self.op.operation_kind,
                'capability': self.capability, 'appointment_id': self.op.appointment_id}

    def start_process(self, mode, args=None):
        self.assertEqual(connection.vendor, 'postgresql')
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
            PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(site.getsitepackages()))
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8',
            '-m', 'apps.agent.tests.b8c_process', mode, json.dumps(args or self.snapshot(), default=str)],
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
                if line.startswith('B8C_'):
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
        self.assertEqual(actual, 'B8C_' + expected)

    @staticmethod
    def release(proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-3000:])
        result = json.loads(next(x.removeprefix('B8C_RESULT ') for x in stdout.splitlines()
                                 if x.startswith('B8C_RESULT ')))
        PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'result': result})
        return result

    def blocked(self, proc):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',
                               ['b8c_' + str(proc.pid)])
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

    def second_operation(self, kind='RESCHEDULE_APPOINTMENT', *, same_appointment=True,
                         start='11:00', vet=None):
        from apps.agent import tools
        from apps.appointments.creation import appointment_interval
        from datetime import time as walltime
        saved = dict(self.__dict__)
        self.wa_id = '5215512340002'
        self.conv = self.inbound('Otra operación').conversation
        contact = self.conv.contact
        contact.owner, contact.verification_level, contact.verified_at = self.owner, 'staff_verified', timezone.now()
        contact.save()
        from .b9c_legacy_fixture import legacy_parallel_domain_claim
        self.claim = lambda: legacy_parallel_domain_claim(self, self.conv)
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.capability = kind.lower()
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
            name={'CREATE_APPOINTMENT': goals.SCHEDULE, 'RESCHEDULE_APPOINTMENT': goals.RESCHEDULE,
                  'CANCEL_APPOINTMENT': goals.CANCEL}[kind])
        self.change({'owner': self.owner.pk, 'pet': self.luna.pk, 'date': self.day,
                     'time': start, 'reason': 'consulta', 'service': 'consulta'})
        if kind != 'CREATE_APPOINTMENT':
            if not same_appointment:
                original_vet = vet or self.vet
                a = Appointment.objects.create(organization=self.org, pet=self.luna,
                    veterinarian=original_vet, date=self.day, start_time='16:00', end_time='16:30', reason='Other')
                a.refresh_from_db()
                a.start_datetime, a.end_datetime = appointment_interval(self.org, a.date, a.start_time, a.end_time)
                a.timezone_at_creation = self.org.timezone
                a.save()
            else:
                a = self.appointment
            handle = tools._add_ref(self.conv, 'cita', a.public_id)
            tools._save_refs(self.conv)
            matter_binding.record_derived(self.goal, self.conv, 'appointment_candidates', [{'handle': handle}],
                context=self.ctx, message_id=self.ctx.anchor.message_id,
                expected_snapshot=matter_binding.snapshot(self.goal), tool='get_appointments', observed_at=timezone.now())
            self.change({'appointment': a.pk})
        if kind != 'CANCEL_APPOINTMENT': self.observe_slot()
        self.authorized()
        snapshot = self.snapshot()
        self.__dict__.update(saved)
        if 'claim' not in saved: del self.claim
        if 'wa_id' not in saved: del self.wa_id
        self.assertNotEqual(snapshot['contact_id'], self.conv.contact_id)
        return snapshot

    def race(self, first_args, second_args, *, both=False):
        first = self.start_process('hold_effect', first_args)
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING')
        second = self.start_process('execute', second_args)
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual(a['status'], 'SUCCEEDED', a)
        self.assertEqual(b['status'], 'SUCCEEDED' if both else 'DENIED', b)
        return a, b

    def competing(self, variant, reverse=False):
        self.mutation()
        self.authorized()
        other = self.second_operation(
            'CANCEL_APPOINTMENT' if variant == 'cancel' else
            'CREATE_APPOINTMENT' if variant == 'create' else 'RESCHEDULE_APPOINTMENT',
            same_appointment=variant != 'distinct', start='11:00' if variant in ('same', 'cancel') else '10:00')
        a, b = (other, self.snapshot()) if reverse else (self.snapshot(), other)
        self.race(a, b)
        from apps.appointments.models import AppointmentMutationEffect
        self.assertEqual(AppointmentMutationEffect.objects.count(), 0 if reverse and variant == 'create' else 1)

    def duplicate(self, kind):
        self.mutation(kind)
        self.authorized()
        a, b = self.race(self.snapshot(), self.snapshot(), both=True)
        self.assertTrue(b['duplicate'])
        self.assertEqual(a['evidence'], b['evidence'])
        from apps.appointments.models import AppointmentMutationEffect
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def crash_before_commit(self, kind, mode, boundary):
        from apps.appointments.models import AppointmentMutationEffect, AppointmentStatusChange
        self.mutation(kind)
        self.authorized()
        original = self.op.preconditions['appointment_snapshot']
        process = self.start_process(mode)
        self.release(process)
        self.barrier(process, 'ATTEMPTING')
        self.barrier(process, boundary)
        self.assertFalse(AppointmentMutationEffect.objects.exists())
        self.cleanup(process)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.appointment.refresh_from_db()
        from apps.appointments.mutations import appointment_snapshot
        self.assertEqual(appointment_snapshot(self.appointment), original)
        self.assertFalse(AppointmentStatusChange.objects.exists())
        self.reclaim()
        recovery = self.start_process('execute')
        self.release(recovery)
        self.assertEqual(self.result(recovery)['status'], 'SUCCEEDED')
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def committed_crash(self, kind):
        from datetime import time as walltime
        from apps.appointments.services import lock_appointment_and_veterinarians
        from apps.appointments.mutations import set_schedule_fields
        from django.db import transaction
        self.mutation(kind)
        self.authorized()
        proc = self.start_process('after_commit')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'COMMITTED')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        # A later legitimate human generic PATCH is allowed by existing policy.
        with transaction.atomic():
            a = lock_appointment_and_veterinarians(self.appointment, self.org.pk)
            set_schedule_fields(a, day=a.date, start=walltime(12), end=walltime(12,30),
                                veterinarian_id=self.vet.pk, org=self.org)
            a.save()
        self.reclaim()
        recovery = self.start_process('execute')
        self.release(recovery)
        result = self.result(recovery)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertTrue(result['duplicate'])
        a.refresh_from_db()
        self.assertEqual(a.start_time, walltime(12))

    def evidence_db_error(self, kind):
        from apps.appointments.models import AppointmentMutationEffect, AppointmentStatusChange
        self.mutation(kind)
        self.authorized()
        proc = self.start_process('evidence_db_error')
        self.release(proc)
        result = self.result(proc)
        self.assertEqual(result['status'], 'UNCERTAIN', result)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.start_time.strftime('%H:%M'), '15:00')
        self.assertEqual(self.appointment.status, 'scheduled')
        self.assertFalse(AppointmentMutationEffect.objects.exists())
        self.assertFalse(AppointmentStatusChange.objects.exists())

    def change_race(self, kind, mode, effect_first):
        self.mutation(kind)
        self.authorized()
        if effect_first:
            first = self.start_process('hold_effect')
            self.release(first)
            self.barrier(first, 'ATTEMPTING')
            self.barrier(first, 'EFFECT_PENDING')
            second = self.start_process(mode)
            self.release(second)
            self.blocked(second)
        else:
            first = self.start_process('hold_' + mode)
            self.release(first)
            self.barrier(first, 'CHANGED')
            second = self.start_process('execute')
            self.release(second)
            self.barrier(second, 'ATTEMPTING')
            self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual((a if effect_first else b)['status'], 'SUCCEEDED' if effect_first else 'DENIED')
        self.assertTrue((b if effect_first else a)['changed'])

    def human_race(self, kind, effect_first):
        self.mutation(kind)
        self.authorized()
        human = User.objects.create(organization=self.org, username='b8c-human', role='ADMIN', is_staff=True)
        args = {**self.snapshot(), 'human_id': human.pk,
                'human_payload': {'start_time': '14:00', 'end_time': '14:30'}}
        first = self.start_process('hold_effect' if effect_first else 'hold_human', args)
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING' if effect_first else 'CHANGED')
        second = self.start_process('human' if effect_first else 'execute', args)
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        self.assertEqual((a if effect_first else b)['status'], 'SUCCEEDED' if effect_first else 'DENIED')
        self.assertEqual((b if effect_first else a)['status_code'], 409 if effect_first else 200)

    def test_exchange_veterinarians_ordered_locks(self):
        self.mutation()
        other_vet = User.objects.create(organization=self.org, username='b8c-vet2', role='VET')
        AgentSettings.objects.update_or_create(organization=self.org, defaults={'default_veterinarian': other_vet})
        self.authorized()
        AgentSettings.objects.filter(organization=self.org).update(default_veterinarian=self.vet)
        other = self.second_operation(same_appointment=False, start='10:00', vet=other_vet)
        self.race(self.snapshot(), other, both=True)

    def constraint_race(self, create_first):
        self.mutation()
        self.authorized()
        other = self.second_operation('CREATE_APPOINTMENT', start='10:00')
        first = self.start_process('hold_effect' if create_first else 'hold_raw_reschedule',
                                   other if create_first else self.snapshot())
        self.release(first)
        self.barrier(first, 'ATTEMPTING')
        self.barrier(first, 'EFFECT_PENDING' if create_first else 'MUTATED')
        second = self.start_process('raw_reschedule' if create_first else 'execute',
                                    self.snapshot() if create_first else other)
        self.release(second)
        self.barrier(second, 'ATTEMPTING')
        self.blocked(second)
        self.release(first)
        a, b = self.result(first), self.result(second)
        if create_first:
            self.assertEqual(a['status'], 'SUCCEEDED')
            self.assertEqual(b['constraint'], 'appointment_no_overlap_per_vet', b)
        else:
            self.assertTrue(a['mutated'])
            self.assertEqual((b['status'], b['reason']), ('FAILED', 'slot_unavailable'), b)

    def test_gist_update_vs_b8b_insert(self): self.constraint_race(False)
    def test_gist_b8b_insert_vs_update(self): self.constraint_race(True)


def make_case(method, *args):
    def test(self): getattr(self, method)(*args)
    return test


for _kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT'):
    _prefix = 'test_' + _kind.lower() + '_'
    for _mode, _boundary in [('before_locks', 'BEFORE_LOCKS'), ('after_appointment', 'APPOINTMENT_LOCKED'),
            ('after_mutation', 'MUTATED'), ('after_evidence', 'EVIDENCE_PENDING')]:
        setattr(B8CProcessTests, _prefix + 'kill_' + _mode, make_case('crash_before_commit', _kind, _mode, _boundary))
    setattr(B8CProcessTests, _prefix + 'kill_after_commit_historical_retry', make_case('committed_crash', _kind))
    setattr(B8CProcessTests, _prefix + 'duplicate_workers', make_case('duplicate', _kind))
    setattr(B8CProcessTests, _prefix + 'evidence_database_error', make_case('evidence_db_error', _kind))
    for _first in (False, True):
        for _mode in ('correction', 'revocation', 'takeover'):
            setattr(B8CProcessTests, _prefix + _mode + '_effect_first_' + str(_first),
                    make_case('change_race', _kind, _mode, _first))
        setattr(B8CProcessTests, _prefix + 'human_effect_first_' + str(_first), make_case('human_race', _kind, _first))
for _variant in ('same', 'cancel', 'create', 'distinct'):
    for _reverse in (False, True):
        setattr(B8CProcessTests, 'test_race_' + _variant + '_reverse_' + str(_reverse),
                make_case('competing', _variant, _reverse))
