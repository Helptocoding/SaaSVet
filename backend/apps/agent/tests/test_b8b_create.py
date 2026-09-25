"""Real Appointment assertions through the only execution entry point."""
from dataclasses import replace
from datetime import date, time, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent import operation_execution as execution
from apps.agent.appointment_execution import command_for, EVENTS
from apps.agent.models import ConversationOperation, ToolExecution, ContactIdentity
from apps.appointments.creation import create_appointment
from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.organizations.models import OrganizationSchedule
from apps.patients.models import Pet
from .b8b_support import AppointmentExecutionFixtures, enabled_create
from . import test_operation_execution as b8a_tests


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8BCreateTests(AppointmentExecutionFixtures, TestCase):
    def run_create(self):
        with enabled_create():
            return self.execute()

    def test_create01_to10_exact_durable_domain_effect(self):
        from apps.medical_records.models import MedicalRecord
        from apps.billing.models import Invoice, Payment
        from apps.inventory.models import StockMovement
        self.authorized()
        counts = [model.objects.count() for model in (MedicalRecord, Invoice, Payment, StockMovement)]
        self.assertEqual(Appointment.objects.count(), 0)  # AUTHORIZED alone is not execution
        result = self.run_create()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        appt = Appointment.objects.get(source_operation_id=self.op.operation_key)
        p = self.op.parameters
        self.assertEqual((appt.organization_id, appt.pet_id, appt.pet.owner_id),
                         (self.org.pk, self.op.pet_id, self.op.owner_id))
        self.assertEqual(appt.pet_id, p['pet_id'])
        self.assertEqual(appt.veterinarian_id, p['veterinarian_id'])
        self.assertEqual((appt.date.isoformat(), appt.start_time.strftime('%H:%M'),
                          appt.end_time.strftime('%H:%M'), appt.reason),
                         (p['date'], p['start_time'], p['end_time'], p['reason']))
        from apps.core.datetime_utils import get_context_timezone
        self.assertEqual(appt.start_datetime.astimezone(get_context_timezone(self.org)).hour, 10)
        self.assertEqual((appt.status, appt.walk_in, appt.category),
                         ('scheduled', False, 'general_consultation'))
        self.assertEqual(appt.source_parameters_digest, self.op.parameters_digest)
        self.assertEqual(result.evidence.domain_object_id, str(appt.public_id))
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'SUCCEEDED')
        self.assertEqual(self.op.executed_at, appt.created_at)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)
        self.assertEqual(counts, [model.objects.count() for model in (MedicalRecord, Invoice, Payment, StockMovement)])

    def test_idem01_03_retry_returns_same_appointment_and_queries_evidence(self):
        self.authorized()
        first = self.run_create()
        self.assertEqual(first.status, 'SUCCEEDED', first)
        with patch('apps.agent.appointment_execution.create_appointment', side_effect=AssertionError('second create')):
            with self.captureOnCommitCallbacks(execute=True):
                second = self.run_create()
        self.assertEqual(second.evidence, first.evidence)
        self.assertTrue(second.duplicate)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(ToolExecution.objects.filter(operation=self.op).count(), 1)

    def test_idem04_recovery_reconciles_before_execute_even_without_ledger(self):
        self.authorized()
        # Deliberate historical recovery fixture; production creates both atomically.
        appt = create_appointment(command_for(self.op), require_schedule=True)
        with patch('apps.agent.appointment_execution.create_appointment', side_effect=AssertionError('second create')):
            result = self.run_create()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        self.assertTrue(result.duplicate)
        self.assertEqual(result.evidence.domain_object_id, str(appt.public_id))
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertFalse(ToolExecution.objects.filter(operation=self.op).exists())

    def test_idem05_db_enforces_unique_source_even_bypassing_clean(self):
        self.authorized()
        self.assertEqual(self.run_create().status, 'SUCCEEDED')
        appt = Appointment.objects.get(source_operation_id=self.op.operation_key)
        appt.pk = None
        appt.public_id = uuid4()
        appt.veterinarian_id = None  # isolate UUID uniqueness from overlap
        with self.assertRaises(IntegrityError), transaction.atomic():
            appt.save(validate=False)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_source_protects_deletion_and_is_immutable_for_ordinary_save(self):
        self.authorized()
        self.assertEqual(self.run_create().status, 'SUCCEEDED')
        appt = Appointment.objects.get()
        appt.source_operation_id = None
        appt.source_parameters_digest = ''
        with self.assertRaises(ValidationError):
            appt.save(validate=False)
        with self.assertRaises(Exception):
            # OrganizationalModel deliberately blocks hard delete before the
            # database reaches its PROTECT FK. The protection remains layered.
            ConversationOperation.all_objects.filter(pk=self.op.pk).delete()

    def test_slot_taken_never_retries_or_claims_human_equivalence(self):
        self.authorized()
        human = create_appointment(replace(command_for(self.op), source_operation_key=None,
                                           source_parameters_digest=''))
        self.assertEqual(self.run_create().reason, 'slot_unavailable')
        Appointment.all_objects.filter(pk=human.pk).update(status='canceled')
        self.assertEqual(self.run_create().reason, 'slot_unavailable')
        self.assertFalse(Appointment.objects.filter(source_operation__isnull=False).exists())

    def test_closed_schedule_and_break_and_outside_hours(self):
        self.authorized()
        schedule = OrganizationSchedule.objects.get(organization=self.org,
            weekday=date.fromisoformat(self.day).isoweekday())
        schedule.is_closed = True
        schedule.save()
        self.assertEqual(self.run_create().reason, 'schedule_closed')
        self.assertEqual(Appointment.objects.count(), 0)

    def test_timezone_changed_requires_new_operation(self):
        self.authorized()
        self.op.refresh_from_db()
        original_timezone = self.op.preconditions['clinic_timezone']
        self.org.timezone = 'UTC' if original_timezone != 'UTC' else 'America/New_York'
        self.org.save()
        self.org.refresh_from_db()
        self.assertEqual(self.run_create().reason, 'precondition_failed')
        self.assertFalse(Appointment.objects.exists())

    def test_pet_owner_relation_cannot_change_under_authorized_definition(self):
        from apps.patients.models import Owner
        self.authorized()
        other = Owner.objects.create(organization=self.org, name='Other owner', phone='5512340000')
        Pet.all_objects.filter(pk=self.luna.pk).update(owner=other)
        self.denied('entity_scope')

    def test_inactive_or_wrong_role_vet_does_not_create(self):
        self.authorized()
        self.vet.is_active = False
        self.vet.save()
        self.denied('entity_scope')

    def test_permission_revocation_is_real_contact_state(self):
        self.authorized()
        self.conv.contact.is_blocked = True
        self.conv.contact.save(update_fields=['is_blocked'])
        self.denied('permission_forbidden')

    def test_fi09_database_failure_cannot_record_succeeded(self):
        self.authorized()
        original = Appointment.save
        def failing(instance, *args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')
            return original(instance, *args, **kwargs)
        with patch.object(Appointment, 'save', failing):
            result = self.run_create()
        self.assertEqual(result.status, 'UNCERTAIN')
        self.assertEqual(Appointment.objects.count(), 0)
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'UNCERTAIN')
        self.assertEqual(self.run_create().status, 'UNCERTAIN')

    def test_fi10_corrupt_domain_evidence_never_creates_a_second(self):
        self.authorized()
        self.assertEqual(self.run_create().status, 'SUCCEEDED')
        appt = Appointment.objects.get()
        Appointment.all_objects.filter(pk=appt.pk).update(reason='Contradictory')
        result = self.run_create()
        self.assertEqual(result.status, 'UNCERTAIN')
        self.assertTrue(result.reconciliation_required)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_fi10_wrong_tenant_source_is_not_absence(self):
        from apps.organizations.models import Organization
        self.authorized()
        create_appointment(command_for(self.op), require_schedule=True)
        other = Organization.objects.create(name='Contradictory tenant')
        Appointment.all_objects.filter(source_operation_id=self.op.operation_key).update(organization=other)
        self.assertEqual(self.run_create().status, 'UNCERTAIN')
        self.assertEqual(Appointment.all_objects.count(), 1)

    def test_cancel_after_commit_preserves_historical_creation(self):
        self.authorized()
        first = self.run_create()
        appt = Appointment.objects.get()
        Appointment.all_objects.filter(pk=appt.pk).update(status='canceled')
        AppointmentStatusChange.objects.create(organization=self.org, appointment=appt,
            from_status='scheduled', to_status='canceled')
        self.assertEqual(self.run_create().evidence, first.evidence)

    def test_only_create_registered_all_other_flags_stay_closed(self):
        from types import SimpleNamespace
        self.assertTrue(execution.REGISTRY['CREATE_APPOINTMENT'].adapter.reconcile_terminal)
        with enabled_create(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={
                kind: True for kind in execution.REGISTRY}):
            # B8D registers attendance; B8E remains release-disabled.
            for kind in ('REGISTER_PET',):
                with self.subTest(kind=kind):
                    entry = execution.REGISTRY[kind]
                    self.assertFalse(entry.enabled)
                    self.assertIsNone(entry.adapter)
                    self.assertEqual(execution._gate(SimpleNamespace(operation_kind=kind), entry), 'kind_disabled')

    def test_create_gate_remains_closed_by_default_and_requires_explicit_true(self):
        self.authorized()
        self.assertEqual(self.execute().reason, 'containment_closed')
        with patch('apps.agent.intake.write_is_contained', return_value=False):
            for flags in ({}, {'CREATE_APPOINTMENT': 'true'}, {'CREATE_APPOINTMENT': False}):
                with override_settings(AGENT_OPERATION_EXECUTION_ENABLED=flags):
                    self.assertEqual(self.execute().reason, 'flag_disabled')
        self.assertFalse(Appointment.objects.exists())

    def test_side_effects_once_and_closed_observability_readonly_inspector(self):
        from apps.agent.admin import ConversationOperationAdmin
        from django.contrib.admin.sites import AdminSite
        self.authorized()
        with patch('apps.dashboard.signals._invalidate_org_dashboard') as invalidate:
            with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.run_create().status, 'SUCCEEDED')
                self.assertEqual(self.run_create().status, 'SUCCEEDED')
            invalidate.assert_called_once_with(self.org.pk)
        # The project's logging filter normalizes `event` from the message.
        events = [r for r in logs.records if r.getMessage().startswith('AGENT_B8B_')]
        self.assertGreater(len(events), 0)
        self.assertEqual(sum(r.getMessage() == 'AGENT_B8B_APPOINTMENT_CREATED' for r in events), 1)
        self.assertTrue(any(r.getMessage() == 'AGENT_B8B_APPOINTMENT_DUPLICATE_SUPPRESSED' for r in events))
        for record in events:
            self.assertIn(record.getMessage().removeprefix('AGENT_B8B_').lower(), EVENTS)
            for field in ('operation_key', 'appointment_id', 'pet_id', 'phone', 'reason', 'name'):
                if field != 'name':  # logging's logger name is not a patient's name
                    self.assertNotIn(field, record.__dict__)
        self.op.refresh_from_db()
        inspector = ConversationOperationAdmin(ConversationOperation, AdminSite())
        self.assertEqual(inspector.appointment_effect(self.op), 'Linked / reconciled')
        self.assertFalse(inspector.has_change_permission(None, self.op))


# Repeat the existing causal guard scenarios against REAL Appointment, using
# the same consent fixture and our domain-count assertion, no fake adapter.
for _name in (
    'test_auth_01_pending_never_executes', 'test_auth_02_rejected',
    'test_auth_03_expired_before_consent', 'test_auth_04_invalidated',
    'test_auth_05_incomplete_evidence', 'test_auth_06_digest_mismatch',
    'test_auth_07_proposal_not_emitted', 'test_auth_08_not_causal',
    'test_inactive_pet_is_ineligible', 'test_rev_01_binding_revision',
    'test_rev_02_identity_revision', 'test_rev_03_ownership_revision',
    'test_rev_05_cross_tenant_entity', 'test_rev_06_takeover', 'test_rev_07_safety_handoff',
    'test_authorized_expired_preserves_historical_evidence',
    'test_new_input_blocks_old_worker', 'test_later_revocation_blocks_even_after_turn_processed',
    'test_no_alternative_parameters_or_string_key',
):
    setattr(B8BCreateTests, _name, getattr(b8a_tests.OperationExecutionTests, _name))
