"""Versioned corpus measures real domain effects, with gates open only in tests."""
import json
from contextlib import ExitStack
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.db.models import Count
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent import operation_execution as execution
from apps.agent.appointment_execution import command_for
from apps.agent.models import ConversationOperation
from apps.appointments.creation import create_appointment
from apps.appointments.models import Appointment
from apps.appointments.services import ACTIVE_STATUSES
from apps.organizations.models import OrganizationSchedule
from .b8b_support import AppointmentExecutionFixtures, enabled_create

CORPUS = json.loads((Path(__file__).resolve().parents[4] /
    'docs/evals/b8b-create-appointment-corpus-v1.json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


def domain_metrics(expected_effects, *, existing_appointments=0):
    linked = Appointment.all_objects.filter(source_operation__isnull=False)
    duplicates = sum(row['n'] - 1 for row in linked.values('source_operation_id').annotate(
        n=Count('pk')).filter(n__gt=1))
    rows = list(Appointment.all_objects.filter(status__in=ACTIVE_STATUSES,
        veterinarian__isnull=False, start_datetime__isnull=False, end_datetime__isnull=False))
    conflicts = sum(1 for i, a in enumerate(rows) for b in rows[i + 1:]
        if (a.organization_id, a.veterinarian_id) == (b.organization_id, b.veterinarian_id)
        and a.start_datetime < b.end_datetime and a.end_datetime > b.start_datetime)
    return {
        # Count ALL appointments, so an accidental unlinked write cannot hide
        # behind a missing source_operation. Manual fixtures are explicit.
        'unauthorized_appointments_created': max(0,
            Appointment.all_objects.count() - existing_appointments - expected_effects),
        'duplicate_appointments_from_same_operation': duplicates,
        'forbidden_operation_kinds_executed': linked.exclude(
            source_operation__operation_kind='CREATE_APPOINTMENT').count(),
        'invalid_slot_conflicts_created': conflicts,
    }


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8BCorpusTests(AppointmentExecutionFixtures, TestCase):
    def run_case(self, case):
        self.authorized()
        scenario = case['scenario']
        with ExitStack() as stack:
            if scenario != 'b0_closed':
                stack.enter_context(enabled_create())
            if scenario in ('slot_occupied', 'manual_equivalent_appointment', 'partial_overlap'):
                cmd = replace(command_for(self.op), source_operation_key=None, source_parameters_digest='')
                if scenario == 'partial_overlap':
                    cmd = replace(cmd, start_time=cmd.start_time.replace(hour=9, minute=45),
                                  end_time=cmd.end_time.replace(minute=15))
                create_appointment(cmd)
            elif scenario == 'clinic_closed':
                OrganizationSchedule.objects.filter(organization=self.org,
                    weekday=date.fromisoformat(self.day).isoweekday()).update(is_closed=True)
            elif scenario == 'pet_stale':
                self.luna.is_active = False
                self.luna.save()
            elif scenario == 'identity_stale':
                self.conv.contact.verified_at = timezone.now()
                self.conv.contact.save(update_fields=['verified_at'])
            elif scenario == 'binding_stale':
                self.correct()
            elif scenario == 'permission_revoked':
                self.conv.contact.is_blocked = True
                self.conv.contact.save(update_fields=['is_blocked'])
            elif scenario == 'takeover':
                self.takeover()
            elif scenario in ('correction', 'revocation'):
                self.response('Mejor las 11' if scenario == 'correction' else 'No, olvida la propuesta')
            elif scenario in ('duplicate_retry', 'evidence_mismatch'):
                self.assertEqual(self.execute().status, 'SUCCEEDED')
                if scenario == 'evidence_mismatch':
                    Appointment.all_objects.filter(source_operation_id=self.op.operation_key).update(
                        reason='Contradictory evidence fixture')
            elif scenario == 'operation_expired':
                stack.enter_context(patch.object(execution.durable, 'db_now',
                    return_value=self.op.expires_at + timedelta(seconds=1)))
            elif scenario == 'create_flag_closed':
                stack.enter_context(override_settings(AGENT_OPERATION_EXECUTION_ENABLED={}))
            elif scenario == 'other_kind_accidental_flag':
                stack.enter_context(override_settings(AGENT_OPERATION_EXECUTION_ENABLED={
                    kind: True for kind in execution.REGISTRY if kind != 'CREATE_APPOINTMENT'}))
                for kind, entry in execution.REGISTRY.items():
                    if kind != 'CREATE_APPOINTMENT':
                        self.assertEqual(execution._gate(SimpleNamespace(operation_kind=kind), entry),
                                         'kind_disabled')
                        self.assertIsNone(entry.adapter)
            result = self.execute()
            manual_fixture = int(scenario in ('slot_occupied', 'manual_equivalent_appointment', 'partial_overlap'))
            metrics = domain_metrics(case['effects'], existing_appointments=manual_fixture)
            effects = Appointment.all_objects.filter(source_operation__isnull=False).count()
        CORPUS_RESULTS.append({'id': case['id'], 'scenario': scenario,
            'status': result.status, 'reason': result.reason, 'effects': effects,
            'expected_status': case['status'], 'expected_effects': case['effects'], **metrics})
        self.assertEqual(result.status, case['status'], result)
        self.assertEqual(effects, case['effects'])
        self.assertTrue(all(value == 0 for value in metrics.values()), metrics)


def make_test(case):
    def test(self):
        self.run_case(case)
    return test


for case in CORPUS.get('cases', []):
    setattr(B8BCorpusTests, 'test_corpus_' + case['id'], make_test(case))
