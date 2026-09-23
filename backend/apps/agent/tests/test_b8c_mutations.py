"""B8C real-domain contract; tests assert persisted effects, never tool intent."""
from datetime import date, time, timedelta
from dataclasses import replace
from unittest.mock import patch
from django.db import connection, transaction, DatabaseError
from django.utils import timezone
from django.test import TestCase, override_settings
from apps.appointments.models import Appointment, AppointmentMutationEffect, AppointmentStatusChange
from apps.appointments.creation import appointment_interval
from apps.organizations.models import OrganizationSchedule
from .b8c_support import MutationFixtures, enabled_mutations


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8CMutationTests(MutationFixtures, TestCase):
    def test_res_01_02_03_exact_destination(self):
        a = self.mutation()
        self.authorized()
        result = self.run_mutation()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        a.refresh_from_db()
        self.assertEqual((a.start_time, a.end_time, a.veterinarian_id), (time(10), time(10, 30), self.vet.pk))
        self.assertEqual(a.status, 'scheduled')
        effect = AppointmentMutationEffect.objects.get(operation_id=self.op.operation_key)
        self.assertEqual(effect.before, self.op.preconditions['appointment_snapshot'])
        self.assertEqual(effect.after['start_time'], '10:00:00')

    def test_can_01_exact_cancellation_and_reason(self):
        a = self.mutation('CANCEL_APPOINTMENT')
        self.authorized()
        result = self.run_mutation()
        self.assertEqual(result.status, 'SUCCEEDED', result)
        a.refresh_from_db()
        self.assertEqual(a.status, 'canceled')
        self.assertEqual(a.cancellation_reason, self.op.parameters['cancellation_reason'])
        self.assertEqual(AppointmentStatusChange.objects.filter(appointment=a).count(), 1)

    def changed(self, kind, values):
        a = self.mutation(kind)
        self.authorized()
        Appointment.objects.filter(pk=a.pk).update(**values)
        self.assert_no_effect(self.run_mutation())
        a.refresh_from_db()
        for field, value in values.items():
            self.assertEqual(getattr(a, field), value)

    def test_res_04_human_time_change(self):
        self.changed('RESCHEDULE_APPOINTMENT', {'start_time': time(14)})

    def test_can_02_human_canceled_is_not_our_effect(self):
        self.changed('CANCEL_APPOINTMENT', {'status': 'canceled'})

    def test_can_03_done(self): self.changed('CANCEL_APPOINTMENT', {'status': 'done'})
    def test_can_04_in_progress(self): self.changed('CANCEL_APPOINTMENT', {'status': 'in_progress'})
    def test_can_05_changed_original(self): self.changed('CANCEL_APPOINTMENT', {'end_time': time(16)})
    def test_res_05_state(self): self.changed('RESCHEDULE_APPOINTMENT', {'status': 'no_show'})
    def test_res_12_pet(self): self.changed('RESCHEDULE_APPOINTMENT', {'pet_id': self.max.pk})

    def conflict(self, start, end, succeeds=False):
        self.mutation()
        self.authorized()
        start_utc, end_utc = appointment_interval(self.org, self.appointment.date, start, end)
        Appointment.objects.create(organization=self.org, pet=self.max, veterinarian=self.vet,
            date=self.day, start_time=start, end_time=end, start_datetime=start_utc,
            end_datetime=end_utc, reason='Other appointment')
        result = self.run_mutation()
        self.assertEqual(result.status == 'SUCCEEDED', succeeds, result)
        if not succeeds:
            self.assert_no_effect(result)
            self.assertEqual(result.reason, 'slot_unavailable')

    def test_res_06_taken(self): self.conflict(time(10), time(10, 30))
    def test_res_07_partial_overlap(self): self.conflict(time(10, 15), time(10, 45))
    def test_res_08_adjacent(self): self.conflict(time(10, 30), time(11), True)

    def test_res_09_schedule_changed(self):
        self.mutation()
        self.authorized()
        OrganizationSchedule.objects.filter(organization=self.org).update(is_closed=True)
        result = self.run_mutation()
        self.assert_no_effect(result)
        self.assertEqual(result.reason, 'schedule_closed')

    def test_res_10_timezone_changed(self):
        self.mutation()
        self.authorized()
        type(self.org).objects.filter(pk=self.org.pk).update(timezone='America/New_York')
        self.assert_no_effect(self.run_mutation())

    def historical(self, kind):
        a = self.mutation(kind)
        self.authorized()
        first = self.run_mutation()
        self.assertEqual(first.status, 'SUCCEEDED', first)
        from apps.appointments.services import current_state
        from apps.appointments.views import AppointmentDetailView
        from apps.users.models import User
        from rest_framework.test import APIRequestFactory, force_authenticate
        a.refresh_from_db()
        human = User.objects.create(organization=self.org, username='history-human', role='ADMIN', is_staff=True)
        request = APIRequestFactory().patch('/api/appointments/' + str(a.public_id) + '/',
            {'expected_state': current_state(a), 'status': 'scheduled',
             'start_time': '12:00', 'end_time': '12:30'}, format='json')
        force_authenticate(request, user=human)
        response = AppointmentDetailView.as_view()(request, pk=str(a.public_id))
        self.assertEqual(response.status_code, 200, response.data)
        again = self.run_mutation()
        self.assertEqual(again.status, 'SUCCEEDED', again)
        self.assertEqual(again.evidence, first.evidence)
        self.assertTrue(again.duplicate)
        a.refresh_from_db()
        self.assertEqual(a.start_time, time(12))
        self.assertEqual(a.status, 'scheduled')
        self.assertEqual(AppointmentMutationEffect.objects.filter(appointment=a).count(), 1)

    def test_res_13_14_historical_retry(self): self.historical('RESCHEDULE_APPOINTMENT')
    def test_can_08_09_historical_retry(self): self.historical('CANCEL_APPOINTMENT')

    def test_res_14_two_authorized_mutations_keep_distinct_history(self):
        self.mutation()
        self.authorized()
        first_op = self.op
        first = self.run_mutation()
        self.assertEqual(first.status, 'SUCCEEDED')
        self.next_turn('Ahora a las doce')
        self.goal.refresh_from_db()
        self.change({'time': '12:00'})
        self.observe_slot()
        self.authorized()
        self.assertNotEqual(first_op.operation_key, self.op.operation_key)
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        self.op = first_op
        replay = self.run_mutation()
        self.assertEqual(replay.status, 'SUCCEEDED', replay)
        self.assertEqual(replay.evidence, first.evidence)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.start_time, time(12))
        self.assertEqual(AppointmentMutationEffect.objects.count(), 2)

    def test_can_06_other_appointment_untouched(self):
        a = self.mutation('CANCEL_APPOINTMENT')
        other = Appointment.objects.create(organization=self.org, pet=self.luna, date=self.day,
            start_time='18:00', end_time='18:30', reason='Other')
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        other.refresh_from_db()
        self.assertEqual(other.status, 'scheduled')
        self.assertTrue(Appointment.objects.filter(pk=a.pk).exists())

    def test_res_15_noop(self):
        self.mutation()
        self.change({'time': '15:00'})
        self.observe_slot()
        self.authorized()
        result = self.run_mutation()
        self.assert_no_effect(result)
        self.assertEqual(result.reason, 'appointment_no_change')
        self.assertFalse(AppointmentStatusChange.objects.exists())

    def test_res_03_exact_changed_veterinarian(self):
        from apps.users.models import User
        from apps.agent.models import AgentSettings
        self.mutation()
        other = User.objects.create(organization=self.org, username='destination', role='VET')
        AgentSettings.objects.update_or_create(organization=self.org, defaults={'default_veterinarian': other})
        self.authorized()
        self.assertEqual(self.op.parameters['veterinarian_id'], other.pk)
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.veterinarian_id, other.pk)

    def test_res_02_authorized_duration_is_not_replaced_by_default(self):
        from apps.agent import matter_binding
        self.mutation()
        matter_binding.record_derived(self.goal, self.conv, 'selected_slot',
            {'date': self.day, 'time': '10:00', 'end_time': '11:15', 'available': True},
            context=self.ctx, message_id=self.ctx.anchor.message_id,
            expected_snapshot=matter_binding.snapshot(self.goal), tool='check_appointment_slot',
            observed_at=timezone.now())
        self.authorized()
        self.assertEqual(self.op.parameters['end_time'], '11:15')
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.end_time, time(11,15))

    def test_res_03_unavailable_veterinarian_has_no_substitution(self):
        from apps.users.models import User
        self.mutation()
        self.authorized()
        User.objects.filter(pk=self.vet.pk).update(is_active=False)
        self.assert_no_effect(self.run_mutation())

    def test_unimplemented_kinds_ignore_accidental_flags(self):
        from types import SimpleNamespace
        from apps.agent.operation_execution import REGISTRY, _gate
        with enabled_mutations(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={kind: True for kind in REGISTRY}):
            for kind in ('CONFIRM_ATTENDANCE', 'REGISTER_PET'):
                self.assertIsNone(REGISTRY[kind].adapter)
                self.assertFalse(REGISTRY[kind].enabled)
                self.assertEqual(_gate(SimpleNamespace(operation_kind=kind), REGISTRY[kind]), 'kind_disabled')

    def test_snapshot_ignores_notes_but_detects_utc_and_walkin(self):
        self.mutation()
        self.authorized()
        Appointment.objects.filter(pk=self.appointment.pk).update(notes='Reception note')
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def test_legacy_definition_fails_closed_without_rehashing_history(self):
        from apps.agent.operations import digest_bindings
        from apps.agent.operation_schema import digest
        self.mutation()
        self.authorized()
        old = dict(self.op.preconditions)
        old.pop('appointment_snapshot')
        old['schema'] = 1
        self.op.preconditions = old
        historical = digest(self.op.operation_kind, self.op.parameters, bindings=digest_bindings(self.op))
        self.tamper(preconditions=old, parameters_digest=historical)
        self.assert_no_effect(self.run_mutation())
        self.op.refresh_from_db()
        self.assertEqual(self.op.parameters_digest, historical)

    def test_can_10_associated_clinical_and_financial_rows_preserved(self):
        from apps.medical_records.models import MedicalRecord
        from apps.billing.models import Invoice, Payment, Checkout
        from apps.prescriptions.models import Prescription
        self.mutation('CANCEL_APPOINTMENT')
        record = MedicalRecord.objects.create(organization=self.org, pet=self.luna,
            veterinarian=self.vet, appointment=self.appointment)
        checkout = Checkout.objects.create(organization=self.org, pet=self.luna, customer=self.owner,
            medical_record=record, origin='consultation', kind='primary_consultation')
        invoice = Invoice.objects.create(organization=self.org, pet=self.luna, owner=self.owner,
            appointment=self.appointment, medical_record=record, checkout=checkout)
        before = {m._meta.label: list(m.objects.values()) for m in (MedicalRecord, Invoice, Payment, Prescription)}
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        after = {m._meta.label: list(m.objects.values()) for m in (MedicalRecord, Invoice, Payment, Prescription)}
        self.assertEqual(before, after)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_fi09_real_database_error_on_evidence_rolls_back_mutation(self):
        self.mutation('CANCEL_APPOINTMENT')
        self.authorized()
        def fail(*args, **kwargs):
            with connection.cursor() as c:
                c.execute('SELECT 1 / 0')
        with patch.object(AppointmentMutationEffect, 'save', fail):
            result = self.run_mutation()
        self.assertEqual(result.status, 'UNCERTAIN', result)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'scheduled')
        self.assertFalse(AppointmentStatusChange.objects.exists())
        self.assert_no_effect(result)
        self.assertEqual(self.run_mutation().status, 'UNCERTAIN')

    def test_fi08_contradictory_evidence_is_uncertain(self):
        self.mutation()
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        # Administrative corruption is outside ordinary writers. Reconciliation
        # still must detect it; do not weaken the DB trigger for production.
        with connection.cursor() as c:
            c.execute('SET CONSTRAINTS ALL IMMEDIATE')
            c.execute('ALTER TABLE appointments_appointmentmutationeffect DISABLE TRIGGER appointment_mutation_evidence_guard')
            try:
                c.execute("UPDATE appointments_appointmentmutationeffect SET parameters_digest=%s", ['0' * 64])
            finally:
                c.execute('ALTER TABLE appointments_appointmentmutationeffect ENABLE TRIGGER appointment_mutation_evidence_guard')
        self.assertEqual(self.run_mutation().status, 'UNCERTAIN')
        self.assertEqual(AppointmentMutationEffect.objects.count(), 1)

    def test_database_immutable_evidence(self):
        self.mutation()
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        with self.assertRaises(DatabaseError), transaction.atomic():
            AppointmentMutationEffect.objects.update(parameters_digest='0' * 64)
        with self.assertRaises(DatabaseError), transaction.atomic():
            AppointmentMutationEffect.objects.all().delete()

    def test_readonly_inspector_separates_history_and_current(self):
        from apps.agent.admin import ConversationOperationAdmin
        from apps.agent.models import ConversationOperation
        from django.contrib.admin.sites import AdminSite
        self.historical('RESCHEDULE_APPOINTMENT')
        inspector = ConversationOperationAdmin(ConversationOperation, AdminSite())
        value = inspector.appointment_effect(self.op)
        self.assertEqual(value['historical_effect']['after']['start_time'], '10:00:00')
        self.assertEqual(value['current_appointment']['start_time'], time(12))
        self.assertFalse(inspector.has_change_permission(None, self.op))

    def dst(self, month, first_day):
        year = timezone.now().year + 1
        anchor = date(year, month, first_day)
        self.day = (anchor + timedelta(days=(6-anchor.weekday()) % 7)).isoformat()
        self.org.timezone = 'America/New_York'
        self.org.save(update_fields=['timezone'])
        self.mutation()
        OrganizationSchedule.objects.filter(organization=self.org).update(opens_at='00:00')
        start = '01:00' if month == 11 else '02:00'
        self.change({'time': start})
        self.observe_slot()
        self.authorized()
        result = self.run_mutation()
        self.assert_no_effect(result)
        self.assertEqual(result.reason, 'invalid_local_time')

    def test_res_10_dst_ambiguous(self): self.dst(11, 1)
    def test_res_10_dst_nonexistent(self): self.dst(3, 8)

    def test_res_07_original_interval_does_not_conflict_with_itself(self):
        self.mutation()
        self.change({'time': '15:15'})
        self.observe_slot()
        self.authorized()
        result = self.run_mutation()
        self.assertEqual(result.status, 'SUCCEEDED', result)

    def test_original_subminute_precision_is_visible_and_bound(self):
        from apps.agent.operations import render
        a = self.mutation('CANCEL_APPOINTMENT')
        a.start_time = time(15, 0, 17)
        a.start_datetime, a.end_datetime = appointment_interval(self.org, a.date, a.start_time, a.end_time)
        a.save()
        self.goal.refresh_from_db()
        self.authorized()
        self.assertIn('15:00:17', render(self.op))
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')

    def test_closed_event_vocabulary_and_cache_once(self):
        from apps.agent.appointment_mutation_execution import EVENTS, observe
        self.mutation('CANCEL_APPOINTMENT')
        self.authorized()
        with self.assertRaises(ValueError): observe('free text')
        with patch('apps.dashboard.signals._invalidate_org_dashboard') as invalidate:
            with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
                self.assertTrue(self.run_mutation().duplicate)
            self.assertEqual(invalidate.call_count, 1)
        records = [r for r in logs.records if r.getMessage().startswith('AGENT_B8C_')]
        self.assertTrue(records)
        for record in records:
            self.assertIn(record.event, EVENTS)
            self.assertEqual(record.count, 1)
            self.assertNotIn(str(self.op.operation_key), record.getMessage())

    def replaced(self, kind):
        from apps.agent import durable
        self.mutation(kind)
        self.authorized()
        old = self.op
        self.next_turn('Cambiar la propuesta')
        self.change({'time': '11:00'} if kind == 'RESCHEDULE_APPOINTMENT' else {'reason': 'No puedo asistir'})
        if kind == 'RESCHEDULE_APPOINTMENT': self.observe_slot()
        newer = self.prepare()
        self.assertEqual(newer.replaces_id, old.pk)
        self.context = replace(self.context, witness=self.witness)
        self.assert_no_effect(self.run_mutation())

    def test_res_replaced_operation(self): self.replaced('RESCHEDULE_APPOINTMENT')
    def test_can_replaced_operation(self): self.replaced('CANCEL_APPOINTMENT')

    def test_b8b_creation_and_b8c_cancellation_preserve_both_proofs(self):
        from apps.agent.models import ConversationGoal
        self.capability = 'create_appointment'
        self.authorized()
        creation = self.op
        result = self.run_mutation()
        self.assertEqual(result.status, 'SUCCEEDED')
        a = Appointment.objects.get(source_operation_id=creation.operation_key)
        self.next_turn('Quiero cancelar esa cita')
        self.goal.status = ConversationGoal.STATUS_COMPLETED
        self.goal.save(update_fields=['status'])
        self.goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv, name='cancel_appointment')
        self.mutation('CANCEL_APPOINTMENT', appointment=a)
        self.authorized()
        self.assertEqual(self.run_mutation().status, 'SUCCEEDED')
        a.refresh_from_db()
        self.assertEqual(a.source_operation_id, creation.operation_key)
        self.assertEqual(a.source_parameters_digest, creation.parameters_digest)
        self.assertEqual(AppointmentMutationEffect.objects.get(appointment=a).operation_id, self.op.operation_key)
        from apps.agent.appointment_execution import CreateAppointmentAdapter
        self.assertEqual(CreateAppointmentAdapter().reconcile(creation, None).evidence, result.evidence)


def guard_case(kind, scenario):
    def test(self):
        from apps.agent import operation_execution as execution
        from apps.agent.models import ConversationGoal, ContactIdentity
        from apps.channels.models import Message
        from apps.organizations.models import Organization
        self.mutation(kind)
        if scenario == 'pending':
            self.op = self.prepare()
            self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        elif scenario == 'rejected':
            self.proposal()
            self.response('NO', reply_to=self.msg.external_message_id)
            self.assertEqual(self.evaluate().decision, 'REJECT')
            self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, self.capability)
        else:
            self.authorized()
        registry = dict(execution.REGISTRY)
        flags = {'RESCHEDULE_APPOINTMENT': True, 'CANCEL_APPOINTMENT': True}
        if scenario == 'missing_evidence': self.tamper(authorization_message_id=self.op.source_message_id)
        elif scenario == 'digest': self.tamper(parameters_digest='0' * 64)
        elif scenario == 'proposal_not_emitted': Message.objects.filter(pk=self.msg.pk).update(status='pending')
        elif scenario == 'not_causal':
            Message.objects.filter(pk=self.msg.pk).update(provider_accepted_at=timezone.now() + timedelta(days=1))
        elif scenario == 'expired': self.tamper(expires_at=timezone.now() - timedelta(seconds=1))
        elif scenario == 'binding':
            ConversationGoal.objects.filter(pk=self.goal.pk).update(binding_revision=self.goal.binding_revision + 1)
        elif scenario == 'identity':
            ContactIdentity.objects.filter(pk=self.conv.contact_id).update(authorization_revision=100)
        elif scenario == 'ownership': self.takeover()
        elif scenario == 'permission': ContactIdentity.objects.filter(pk=self.conv.contact_id).update(is_blocked=True)
        elif scenario == 'safety':
            from apps.agent.models import HumanHandoff
            HumanHandoff.objects.create(organization=self.org, conversation=self.conv,
                                       reason_code=HumanHandoff.REASON_EXPLICIT)
        elif scenario == 'kind_flag': flags[kind] = False
        elif scenario == 'adapter_missing': registry[kind] = replace(registry[kind], adapter=None)
        elif scenario == 'contextual': self.tamper(authorization_mode='CONTEXTUAL_DECLARATION')
        elif scenario == 'revocation': self.response('No, olvida la propuesta')
        elif scenario == 'correction': self.correct()
        elif scenario == 'tenant':
            other = Organization.objects.create(name='Other tenant')
            Appointment.all_objects.filter(pk=self.appointment.pk).update(organization=other)
        elif scenario == 'wrong_appointment': self.tamper(appointment_id=None)
        elif scenario == 'utc':
            Appointment.objects.filter(pk=self.appointment.pk).update(start_datetime=self.appointment.start_datetime + timedelta(minutes=1))
        elif scenario == 'walk_in': Appointment.objects.filter(pk=self.appointment.pk).update(walk_in=True)
        with patch.object(execution, 'REGISTRY', registry), patch(
                'apps.agent.intake.write_is_contained', return_value=scenario == 'b0'), override_settings(
                    AGENT_OPERATION_EXECUTION_ENABLED=flags):
            result = self.execute()
        self.assert_no_effect(result)
        self.assertEqual(result.status, 'DENIED', result)
    return test


for _kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT'):
    for _scenario in ('pending', 'rejected', 'missing_evidence', 'digest', 'proposal_not_emitted', 'not_causal', 'expired',
            'binding', 'identity', 'ownership', 'permission', 'safety', 'kind_flag', 'adapter_missing',
            'contextual', 'revocation', 'correction', 'tenant', 'wrong_appointment', 'utc', 'walk_in', 'b0'):
        setattr(B8CMutationTests, 'test_guard_' + _kind.lower() + '_' + _scenario, guard_case(_kind, _scenario))
