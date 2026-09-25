"""CONF-01..15, causal declaration and real Agenda effects under B8A."""
from datetime import time, timedelta
from dataclasses import replace
from unittest.mock import patch
from django.db import connection, transaction, DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.agent import operation_execution as execution, operation_consent as consent
from apps.appointments.models import Appointment, AppointmentMutationEffect, AppointmentStatusChange
from .b8d_support import AttendanceFixtures, enabled_attendance, make_legacy_attendance
from .test_b8c_mutations import guard_case


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8DAttendanceTests(AttendanceFixtures, TestCase):
    def test_conf_01_exact_confirmation_only(self):
        from apps.appointments.mutations import appointment_snapshot
        from apps.medical_records.models import MedicalRecord
        from apps.billing.models import Invoice, Payment
        from apps.inventory.models import StockMovement
        a = self.mutation()
        other = Appointment.objects.create(organization=self.org, pet=self.luna, date=self.day,
            start_time='18:00', end_time='18:30', reason='Other')
        before = appointment_snapshot(a)
        related = {m._meta.label: list(m.objects.values()) for m in (MedicalRecord, Invoice, Payment, StockMovement)}
        self.authorized()
        result = self.run_mutation()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        a.refresh_from_db()
        self.assertEqual(appointment_snapshot(a), {**before, 'status': 'confirmed'})
        other.refresh_from_db()
        self.assertEqual(other.status, 'scheduled')
        self.assertEqual(related, {m._meta.label: list(m.objects.values()) for m in (MedicalRecord, Invoice, Payment, StockMovement)})
        self.assertIsNone(a.source_operation_id)
        effect = AppointmentMutationEffect.objects.get(operation_id=self.op.operation_key)
        self.assertEqual(effect.status_change.to_status, 'confirmed')
        self.assertIsNone(effect.status_change.changed_by_id)
        self.assertEqual(effect.before, self.op.preconditions['appointment_snapshot'])

    def test_contextual_declaration_is_exact_causal_and_not_a_second_ritual(self):
        self.mutation()
        self.proposal()
        self.assertIn(str(self.appointment.public_id), self.msg.body)
        self.assertIn('15:00', self.msg.body)
        self.response('Sí confirmo que asistiré', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.authorization_policy_version, 2)
        self.assertEqual(consent.execution_authorization_evidence(self.op).authorization_mode, 'CONTEXTUAL_DECLARATION')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def reject_declaration(self, text, reply=True):
        self.mutation()
        self.proposal()
        self.response(text, reply_to=self.msg.external_message_id if reply else None)
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        self.assert_no_effect(self.run_mutation())

    def test_declaration_without_reference(self): self.reject_declaration('Sí confirmo que asistiré', False)
    def test_bare_yes_does_not_declare_attendance(self): self.reject_declaration('Sí')
    def test_question_never_confirms(self): self.reject_declaration('¿Mi cita está confirmada?')
    def test_indirect_question_never_confirms(self): self.reject_declaration('Quiero saber si está confirmada')
    def test_declaration_with_correction(self): self.reject_declaration('Sí confirmo que asistiré pero para Max')
    def test_declaration_with_condition(self): self.reject_declaration('Sí confirmo que asistiré si hay lugar')
    def test_declaration_with_multiple_intents(self): self.reject_declaration('Sí confirmo que asistiré y cancela la otra')
    def test_negation(self): self.reject_declaration('No 👍')

    def changed(self, **values):
        a = self.mutation()
        self.authorized()
        Appointment.objects.filter(pk=a.pk).update(**values)
        self.assert_no_effect(self.run_mutation())
        a.refresh_from_db()
        for field, value in values.items(): self.assertEqual(getattr(a, field), value)

    def test_conf_04_snapshot_changed(self): self.changed(end_time=time(16))
    def test_conf_06_canceled(self): self.changed(status='canceled')
    def test_conf_07_in_progress(self): self.changed(status='in_progress')
    def test_conf_07_done(self): self.changed(status='done')
    def test_no_show(self): self.changed(status='no_show')
    def test_veterinarian_changed(self): self.changed(veterinarian_id=None)
    def test_inactive(self): self.changed(is_active=False)

    def test_conf_05_real_human_reschedule(self):
        from apps.appointments.services import current_state
        from apps.appointments.views import AppointmentDetailView
        from apps.users.models import User
        from rest_framework.test import APIRequestFactory, force_authenticate
        a = self.mutation()
        self.authorized()
        user = User.objects.create(organization=self.org, username='b8d-reschedule', role='ADMIN', is_staff=True)
        request = APIRequestFactory().patch('/appointment/', {'expected_state': current_state(a),
            'start_time': '14:00', 'end_time': '14:30'}, format='json')
        force_authenticate(request, user=user)
        response = AppointmentDetailView.as_view()(request, pk=str(a.public_id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_no_effect(self.run_mutation())
        a.refresh_from_db()
        self.assertEqual((a.status, a.start_time), ('scheduled', time(14)))

    def test_conf_08_real_human_confirmation_not_attributed(self):
        self.mutation()
        self.authorized()
        self.human_status('confirmed')
        audit = AppointmentStatusChange.objects.get(appointment=self.appointment)
        self.assertIsNotNone(audit.changed_by_id)
        self.assert_no_effect(self.run_mutation())
        self.assertEqual(AppointmentStatusChange.objects.count(), 1)

    def historical(self, states=()):
        self.mutation()
        self.authorized()
        first = self.run_mutation()
        self.assertEqual(first.status, 'SUCCEEDED', first)
        for state in states: self.human_status(state)
        second = self.run_mutation()
        self.assertEqual(second.status, 'SUCCEEDED', second)
        self.assertEqual(first.evidence, second.evidence)
        self.assertTrue(second.duplicate)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, states[-1] if states else 'confirmed')
        self.assertEqual(AppointmentStatusChange.objects.count(), len(states) + 1)
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def test_conf_09_retry(self): self.historical()
    def test_conf_10_retry_in_progress(self): self.historical(('in_progress',))
    def test_conf_10_retry_done(self): self.historical(('in_progress', 'done'))

    def test_conf_11_walk_in_scheduled_future(self):
        self.mutation()
        Appointment.objects.filter(pk=self.appointment.pk).update(walk_in=True)
        self.goal.refresh_from_db()
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def test_conf_11_normal_walk_in_not_eligible(self):
        from apps.agent.operations import PreparationDenied
        self.mutation()
        Appointment.objects.filter(pk=self.appointment.pk).update(walk_in=True, status='in_progress')
        self.goal.refresh_from_db()
        with self.assertRaises(PreparationDenied): self.prepare()

    def test_conf_12_past_at_execution(self):
        self.mutation()
        self.authorized()
        # Advance only the domain's clock; authorized snapshot is unmodified.
        future = self.appointment.start_datetime + timedelta(seconds=1)
        from types import SimpleNamespace
        with patch('apps.appointments.mutations.timezone', SimpleNamespace(now=lambda: future)):
            result = self.run_mutation()
        self.assert_no_effect(result)
        self.assertEqual(result.reason, 'schedule_elapsed')

    def test_conf_13_owner_changed(self):
        from apps.patients.models import Owner, Pet
        self.mutation()
        self.authorized()
        owner = Owner.objects.create(organization=self.org, name='Other', phone='5511220000')
        Pet.objects.filter(pk=self.luna.pk).update(owner=owner)
        self.assert_no_effect(self.run_mutation())

    def test_exact_fk_must_match_parameter_even_for_same_pet(self):
        self.mutation()
        other = Appointment.objects.create(organization=self.org, pet=self.luna,
            date=self.day, start_time='18:00', end_time='18:30', reason='Other')
        self.authorized()
        self.tamper(appointment_id=other.pk)
        self.assert_no_effect(self.run_mutation())
        other.refresh_from_db()
        self.assertEqual(other.status, 'scheduled')

    def test_null_veterinarian_is_explicitly_authorized(self):
        self.mutation()
        Appointment.objects.filter(pk=self.appointment.pk).update(veterinarian=None)
        self.goal.refresh_from_db()
        self.authorized()
        self.assertIn('sin asignar', self.msg.body)
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def test_future_snapshot_subminute_precision_visible(self):
        from apps.appointments.creation import appointment_interval
        a = self.mutation()
        a.start_time = time(15, 0, 17, 25)
        a.start_datetime, a.end_datetime = appointment_interval(self.org, a.date, a.start_time, a.end_time)
        a.save()
        self.goal.refresh_from_db()
        self.authorized()
        self.assertIn('15:00:17.000025', self.msg.body)
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def test_human_past_confirmation_policy_preserved(self):
        self.mutation()
        self.human_status('confirmed')
        # The domain service itself has no future guard; /status/ owns the
        # unchanged state-machine policy. Confirm a second actual past row.
        from apps.appointments.creation import appointment_interval
        a = self.appointment
        a.status = 'scheduled'
        a.date -= timedelta(days=10)
        a.start_datetime, a.end_datetime = appointment_interval(self.org, a.date, a.start_time, a.end_time)
        a.save()
        self.human_status('confirmed')

    def test_flag_requires_boolean_true(self):
        self.mutation()
        self.authorized()
        with enabled_attendance():
            for value in (False, 'true', 1, None):
                with override_settings(AGENT_OPERATION_EXECUTION_ENABLED={'CONFIRM_ATTENDANCE': value}):
                    result = self.execute()
                    self.assert_no_effect(result)
                    self.assertEqual(result.reason, 'flag_disabled')

    def test_agent_cannot_use_human_status_endpoint(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.appointments.views import update_status
        from apps.appointments.services import current_state
        from apps.users.models import User
        self.mutation()
        actor = User.objects.create(organization=self.org, username='b8d-agent', role='AGENT')
        request = APIRequestFactory().patch('/status/', {'status': 'confirmed',
            'expected_state': current_state(self.appointment)}, format='json')
        force_authenticate(request, user=actor)
        response = update_status(request, pk=str(self.appointment.public_id))
        self.assertEqual(response.status_code, 403)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'scheduled')

    def test_guard_safety_signal(self):
        from apps.agent import safety_handoff
        self.mutation()
        self.authorized()
        with patch.object(safety_handoff, 'pending_signal', return_value=True):
            result = self.run_mutation()
        self.assert_no_effect(result)
        self.assertEqual(result.reason, 'safety_handoff')

    def test_consultation_already_exists(self):
        from apps.medical_records.models import MedicalRecord
        self.mutation()
        self.authorized()
        record = MedicalRecord.objects.create(organization=self.org, pet=self.luna,
            appointment=self.appointment, veterinarian=self.vet)
        self.assert_no_effect(self.run_mutation())
        self.assertTrue(MedicalRecord.objects.filter(pk=record.pk).exists())

    def test_conf_14_contradictory_historical_evidence(self):
        self.historical(('in_progress',))
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('ALTER TABLE appointments_appointmentmutationeffect DISABLE TRIGGER appointment_mutation_evidence_guard')
            try:
                cursor.execute("UPDATE appointments_appointmentmutationeffect SET parameters_digest=%s", ['0' * 64])
            finally:
                cursor.execute('ALTER TABLE appointments_appointmentmutationeffect ENABLE TRIGGER appointment_mutation_evidence_guard')
        self.assertEqual(self.run_mutation().status, 'UNCERTAIN')
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def test_conf_14_missing_audit_is_uncertain(self):
        self.historical()
        AppointmentStatusChange.objects.filter(appointment=self.appointment).update(to_status='done')
        self.assertEqual(self.run_mutation().status, 'UNCERTAIN')

    def test_conf_15_defaults_closed_and_register_pet_disabled(self):
        from django.conf import settings
        from types import SimpleNamespace
        self.mutation()
        self.authorized()
        self.assertEqual(settings.AGENT_OPERATION_EXECUTION_ENABLED, {})
        self.assert_no_effect(self.execute())
        with enabled_attendance(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={'REGISTER_PET': True}):
            entry = execution.REGISTRY['REGISTER_PET']
            self.assertIsNone(entry.adapter)
            self.assertEqual(execution._gate(SimpleNamespace(operation_kind='REGISTER_PET'), entry), 'kind_disabled')

    def test_legacy_attendance_never_gains_consent(self):
        from apps.agent import durable
        self.mutation()
        self.op = self.prepare()
        make_legacy_attendance(self.op)
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.assertIsNone(self.op.proposal_message_id)
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        self.assert_no_effect(self.run_mutation())

    def test_cache_and_audit_once(self):
        self.mutation()
        self.authorized()
        with patch('apps.dashboard.signals._invalidate_org_dashboard') as invalidate:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
                self.assertTrue(self.run_mutation().duplicate)
            self.assertEqual(invalidate.call_count, 1)
        self.assertEqual(AppointmentStatusChange.objects.count(), 1)

    def test_evidence_sql_error_rolls_back_real_effect(self):
        self.mutation()
        self.authorized()
        def failure(*args, **kwargs):
            with connection.cursor() as cursor: cursor.execute('SELECT 1 / 0')
        with patch.object(AppointmentMutationEffect, 'save', failure):
            self.assertEqual(self.run_mutation().status, 'UNCERTAIN')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'scheduled')
        self.assertFalse(AppointmentStatusChange.objects.exists())
        self.assertFalse(AppointmentMutationEffect.objects.exists())
        self.assertEqual(self.run_mutation().status, 'UNCERTAIN')

    def test_evidence_is_immutable_and_unique(self):
        self.historical()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AppointmentMutationEffect.objects.update(parameters_digest='0'*64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            AppointmentMutationEffect.objects.all().delete()

    def test_inspector_distinguishes_historical_confirmation_from_current_done(self):
        from django.contrib.admin.sites import AdminSite
        from apps.agent.admin import ConversationOperationAdmin
        from apps.agent.models import ConversationOperation
        self.historical(('in_progress', 'done'))
        inspector = ConversationOperationAdmin(ConversationOperation, AdminSite())
        visible = inspector.appointment_effect(self.op)
        self.assertEqual(visible['historical_effect']['after']['status'], 'confirmed')
        self.assertIsNotNone(visible['historical_effect']['status_change_id'])
        self.assertEqual(visible['current_appointment']['status'], 'done')
        self.assertFalse(inspector.has_change_permission(None, self.op))


for _scenario in ('pending', 'rejected', 'missing_evidence', 'digest', 'proposal_not_emitted',
        'not_causal', 'expired', 'binding', 'identity', 'ownership', 'permission', 'safety',
        'kind_flag', 'adapter_missing', 'contextual', 'revocation', 'correction', 'tenant',
        'wrong_appointment', 'utc', 'walk_in', 'b0'):
    setattr(B8DAttendanceTests, 'test_guard_' + _scenario, guard_case('CONFIRM_ATTENDANCE', _scenario))
