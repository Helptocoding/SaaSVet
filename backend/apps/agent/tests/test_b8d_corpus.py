"""Versioned B8D corpus, separate from PostgreSQL process/failure acceptance."""
import json
from pathlib import Path
from datetime import time
from dataclasses import replace
from django.db.models import Count
from django.test import TestCase, override_settings
from apps.agent import operation_execution as execution
from apps.appointments.models import Appointment, AppointmentMutationEffect
from .b8d_support import AttendanceFixtures, enabled_attendance

CORPUS = json.loads((Path(__file__).resolve().parents[4] /
    'docs/evals/b8d-confirm-attendance-corpus-v1.json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8DCorpusTests(AttendanceFixtures, TestCase):
    def scenario(self, case):
        from apps.agent.models import ContactIdentity
        from apps.organizations.models import Organization
        self.mutation()
        scenario = case['scenario']
        if scenario == 'pending':
            self.op = self.prepare()
        elif scenario in ('question', 'declaration', 'unreferenced'):
            self.proposal()
            self.response(case.get('text', 'Sí confirmo que asistiré'),
                reply_to=None if scenario == 'unreferenced' else self.msg.external_message_id)
            self.evaluate()
        else:
            self.authorized()
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        if scenario == 'human_confirmed': self.human_status('confirmed')
        elif scenario in ('canceled', 'in_progress', 'done'):
            Appointment.objects.filter(pk=self.appointment.pk).update(status=scenario)
        elif scenario == 'snapshot': Appointment.objects.filter(pk=self.appointment.pk).update(start_time=time(14))
        elif scenario == 'wrong_appointment': self.tamper(appointment_id=None)
        elif scenario == 'tenant':
            other = Organization.objects.create(name='Other')
            Appointment.objects.filter(pk=self.appointment.pk).update(organization=other)
        elif scenario == 'owner': ContactIdentity.objects.filter(pk=self.conv.contact_id).update(owner=None)
        elif scenario == 'evidence': self.tamper(authorization_message_id=self.op.source_message_id)
        elif scenario == 'correction': self.correct()
        elif scenario == 'revocation': self.response('No, olvida la propuesta')
        elif scenario == 'takeover': self.takeover()
        from apps.appointments.mutations import appointment_snapshot
        self.appointment.refresh_from_db()
        before = appointment_snapshot(self.appointment)
        if scenario == 'gate':
            result = self.execute()
        elif scenario == 'register_pet_flag':
            with enabled_attendance(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={'REGISTER_PET': True}):
                result = self.execute()
        else:
            result = self.run_mutation()
        if scenario in ('retry', 'historical_done'):
            self.assertEqual(result.status, 'SUCCEEDED', result)
            if scenario == 'historical_done':
                self.human_status('in_progress')
                self.human_status('done')
            result = self.run_mutation()
            self.assertTrue(result.duplicate)
        effects = AppointmentMutationEffect.objects.all()
        count = effects.count()
        self.appointment.refresh_from_db()
        after = appointment_snapshot(self.appointment)
        metrics = {
            'unauthorized_confirmations': int(case['expected_effects'] == 0 and count > 0),
            'wrong_appointment_confirmations': effects.exclude(appointment_id=self.appointment.pk).count(),
            'duplicate_effects_per_operation': effects.values('operation_id').annotate(n=Count('pk')).filter(n__gt=1).count(),
            'stale_snapshot_overwrites': int(case['expected_effects'] == 0 and before != after),
            'invalid_state_transitions': sum(e.before['status'] != 'scheduled' or e.after['status'] != 'confirmed' for e in effects),
            'forbidden_operation_kinds_executed': effects.exclude(kind='CONFIRM_ATTENDANCE').count(),
        }
        CORPUS_RESULTS.append({'id': case['id'], 'scenario': scenario, 'status': result.status,
            'effects': count, 'expected_effects': case['expected_effects'], 'metrics': metrics})
        self.assertEqual(count, case['expected_effects'], result)
        self.assertEqual(result.status == 'SUCCEEDED', case['expected_effects'] == 1, result)
        self.assertEqual(set(metrics.values()), {0})


def make_case(case):
    def test(self): self.scenario(case)
    return test


for case in CORPUS['cases']:
    setattr(B8DCorpusTests, 'test_' + case['id'].lower().replace('-', '_'), make_case(case))
