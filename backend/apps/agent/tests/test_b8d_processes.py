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
from .b8d_support import AttendanceFixtures, enabled_attendance


class ProcessEvidence(list):
    def append(self, item):
        super().append(item)
        # Preserve real PID/barrier evidence even if the parent host is stopped.
        path = os.environ.get('B8D_RESULTS_PATH')
        if path:
            with Path(path).with_suffix('.processes.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(item) + '\n')


PROCESS_RESULTS = ProcessEvidence()


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8DProcessTests(AttendanceFixtures, TransactionTestCase):
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
            '-m', 'apps.agent.tests.b8d_process', mode, json.dumps(args or self.snapshot(), default=str)],
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
                if line.startswith('B8D_'):
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
        self.assertEqual(actual, 'B8D_' + expected)

    @staticmethod
    def release(proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-3000:])
        result = json.loads(next(x.removeprefix('B8D_RESULT ') for x in stdout.splitlines()
                                 if x.startswith('B8D_RESULT ')))
        PROCESS_RESULTS.append({'test_id': self.id(), 'pid': proc.pid, 'result': result})
        return result

    def blocked(self, proc):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',
                               ['b8d_' + str(proc.pid)])
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
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.capability = 'confirm_appointment' if kind == 'CONFIRM_ATTENDANCE' else kind.lower()
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
            name={'CREATE_APPOINTMENT': goals.SCHEDULE, 'RESCHEDULE_APPOINTMENT': goals.RESCHEDULE,
                  'CANCEL_APPOINTMENT': goals.CANCEL, 'CONFIRM_ATTENDANCE': 'confirm_appointment'}[kind])
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
        if kind in ('CREATE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'): self.observe_slot()
        self.authorized()
        snapshot = self.snapshot()
        self.__dict__.update(saved)
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

    def competing(self, kind, reverse):
        self.mutation()
        self.authorized()
        other = self.second_operation(kind)
        pair = (other, self.snapshot()) if reverse else (self.snapshot(), other)
        self.race(*pair)
        from apps.appointments.models import AppointmentMutationEffect
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def committed_retry(self, later):
        self.mutation()
        self.authorized()
        proc = self.start_process('after_commit')
        self.release(proc)
        self.barrier(proc, 'ATTEMPTING')
        self.barrier(proc, 'COMMITTED')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        if later:
            self.human_status('in_progress')
            if later == 'done': self.human_status('done')
        self.reclaim()
        proc = self.start_process('execute')
        self.release(proc)
        result = self.result(proc)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertTrue(result['duplicate'])
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, later or 'confirmed')
        from apps.appointments.models import AppointmentMutationEffect, AppointmentStatusChange
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)
        self.assertEqual(AppointmentStatusChange.objects.count(), 3 if later == 'done' else 2 if later else 1)

    def human_race(self, target, effect_first):
        self.mutation()
        self.authorized()
        human = User.objects.create(organization=self.org, username='b8d-human', role='ADMIN', is_staff=True)
        args = {**self.snapshot(), 'human_id': human.pk, 'human_payload': {'status': target}}
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
        from apps.appointments.models import AppointmentMutationEffect, AppointmentStatusChange
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1 if effect_first else 0)
        self.assertEqual(AppointmentStatusChange.objects.count(), 1)


def make_case(method, *args):
    def test(self): getattr(self, method)(*args)
    return test


for mode, boundary in [('before_locks', 'BEFORE_LOCKS'), ('after_appointment', 'APPOINTMENT_LOCKED'),
        ('after_mutation', 'MUTATED'), ('after_evidence', 'EVIDENCE_PENDING')]:
    setattr(B8DProcessTests, 'test_kill_' + mode, make_case('crash_before_commit', 'CONFIRM_ATTENDANCE', mode, boundary))
for later in ('', 'in_progress', 'done'):
    setattr(B8DProcessTests, 'test_kill_after_commit_retry_' + (later or 'confirmed'), make_case('committed_retry', later))
for method in ('duplicate', 'evidence_db_error'):
    setattr(B8DProcessTests, 'test_' + method, make_case(method, 'CONFIRM_ATTENDANCE'))
for first in (False, True):
    for mode in ('correction', 'revocation', 'takeover', 'identity_revocation'):
        setattr(B8DProcessTests, 'test_' + mode + '_effect_first_' + str(first),
            make_case('change_race', 'CONFIRM_ATTENDANCE', mode, first))
    for target in ('confirmed', 'in_progress'):
        setattr(B8DProcessTests, 'test_human_' + target + '_effect_first_' + str(first),
            make_case('human_race', target, first))
    for kind in ('CONFIRM_ATTENDANCE', 'CANCEL_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'):
        setattr(B8DProcessTests, 'test_competing_' + kind.lower() + '_reverse_' + str(first),
            make_case('competing', kind, first))
