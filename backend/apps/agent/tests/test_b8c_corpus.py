"""Versioned scenarios against real adapters, distinct from process/crash tests."""
import json
from pathlib import Path
from datetime import time
from unittest.mock import patch
from django.db.models import Count
from django.db import transaction
from django.test import TestCase, override_settings
from apps.appointments.models import Appointment, AppointmentMutationEffect
from apps.appointments.mutations import appointment_snapshot
from apps.organizations.models import OrganizationSchedule
from .b8c_support import MutationFixtures, enabled_mutations

CORPUS = json.loads((Path(__file__).resolve().parents[4] /
    'docs/evals/b8c-appointment-mutations-corpus-v1json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8CCorpusTests(MutationFixtures, TestCase):
    def run_case(self, case):
        self.mutation(case['kind'])
        self.authorized()
        scenario = case['scenario']
        if scenario == 'stale': Appointment.objects.filter(pk=self.appointment.pk).update(start_time=time(14))
        elif scenario == 'human_canceled': Appointment.objects.filter(pk=self.appointment.pk).update(status='canceled')
        elif scenario == 'done': Appointment.objects.filter(pk=self.appointment.pk).update(status='done')
        elif scenario == 'in_progress': Appointment.objects.filter(pk=self.appointment.pk).update(status='in_progress')
        elif scenario == 'closed': OrganizationSchedule.objects.filter(organization=self.org).update(is_closed=True)
        elif scenario == 'digest': self.tamper(parameters_digest='0' * 64)
        elif scenario == 'revoked': self.response('No, olvida la propuesta')
        elif scenario in ('occupied', 'overlap', 'adjacent'):
            from apps.appointments.creation import AppointmentCommand, create_appointment
            start, end = {'occupied': (time(10), time(10,30)),
                'overlap': (time(10,15), time(10,45)), 'adjacent': (time(10,30), time(11))}[scenario]
            create_appointment(AppointmentCommand(organization_id=self.org.pk, pet_id=self.max.pk,
                veterinarian_id=self.vet.pk, date=self.appointment.date, start_time=start,
                end_time=end, reason='Other appointment'))
        baseline = {a.pk: appointment_snapshot(a) for a in Appointment.all_objects.all()}
        with enabled_mutations(), patch('apps.agent.intake.write_is_contained', return_value=scenario == 'b0'):
            result = self.execute()
            if scenario in ('retry', 'historical'):
                if scenario == 'historical':
                    from apps.appointments.services import lock_appointment_and_veterinarians
                    from apps.appointments.mutations import set_schedule_fields
                    with transaction.atomic():
                        current = lock_appointment_and_veterinarians(self.appointment, self.org.pk)
                        set_schedule_fields(current, day=current.date, start=time(12), end=time(12,30),
                            veterinarian_id=self.vet.pk, org=self.org)
                        current.save()
                    baseline[self.appointment.pk] = appointment_snapshot(Appointment.objects.get(pk=self.appointment.pk))
                result = self.execute()
        after = {a.pk: appointment_snapshot(a) for a in Appointment.all_objects.all()}
        changed = {pk for pk in set(baseline) | set(after) if baseline.get(pk) != after.get(pk)}
        effects = list(AppointmentMutationEffect.objects.select_related('operation').all())
        metrics = {
            'unauthorized_appointment_mutations': int(bool(changed) and case['effects'] == 0) + sum(
                e.operation.consent_state != 'AUTHORIZED' for e in effects),
            'wrong_appointment_mutations': len(changed - {self.appointment.pk}),
            'duplicate_effects_per_operation': sum(max(0, row['n'] - 1) for row in
                AppointmentMutationEffect.objects.values('operation_id').annotate(n=Count('pk'))),
            'stale_snapshot_overwrites': int(scenario in ('stale', 'human_canceled', 'done', 'in_progress') and bool(changed)),
            'invalid_destination_slot_conflicts': 0,
            'forbidden_operation_kinds_executed': sum(e.kind not in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT') for e in effects),
        }
        rows = list(Appointment.all_objects.filter(status__in=('scheduled', 'confirmed', 'in_progress')))
        metrics['invalid_destination_slot_conflicts'] = sum(
            a.veterinarian_id is not None and a.veterinarian_id == b.veterinarian_id
            and a.organization_id == b.organization_id and bool(a.start_datetime and a.end_datetime
                and b.start_datetime and b.end_datetime) and a.start_datetime < b.end_datetime
            and a.end_datetime > b.start_datetime for i, a in enumerate(rows) for b in rows[i+1:])
        CORPUS_RESULTS.append({'id': case['id'], 'kind': case['kind'], 'scenario': scenario,
            'status': result.status, 'effects': len(effects), 'metrics': metrics, 'scope': 'real_adapter'})
        self.assertEqual(result.status, case['status'], result)
        self.assertEqual(len(effects), case['effects'])
        self.assertTrue(all(v == 0 for v in metrics.values()), metrics)


def make_case(case):
    def test(self): self.run_case(case)
    return test


for _case in CORPUS['cases']:
    setattr(B8CCorpusTests, 'test_corpus_' + _case['id'], make_case(_case))
