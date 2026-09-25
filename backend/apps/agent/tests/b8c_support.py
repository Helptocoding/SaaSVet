"""Real B7A/B7B consent and B8C adapters, isolated acceptance gates."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, time
from unittest.mock import patch
from django.test import override_settings
from apps.agent import goals, operation_execution as execution
from apps.appointments.creation import appointment_interval
from .b8b_support import AppointmentExecutionFixtures


@contextmanager
def enabled_mutations():
    with patch('apps.agent.intake.write_is_contained', return_value=False), override_settings(
            AGENT_B7B_CONSENT_ENABLED=True, AGENT_OPERATION_EXECUTION_ENABLED={
                'CREATE_APPOINTMENT': True, 'RESCHEDULE_APPOINTMENT': True,
                'CANCEL_APPOINTMENT': True}):
        yield


class MutationFixtures(AppointmentExecutionFixtures):
    capability = 'reschedule_appointment'

    def mutation(self, kind='RESCHEDULE_APPOINTMENT', appointment=None):
        self.capability = 'confirm_appointment' if kind == 'CONFIRM_ATTENDANCE' else kind.lower()
        name = {'RESCHEDULE_APPOINTMENT': goals.RESCHEDULE, 'CANCEL_APPOINTMENT': goals.CANCEL,
                'CONFIRM_ATTENDANCE': 'confirm_appointment'}[kind]
        if appointment is not None:
            from apps.agent import tools, matter_binding
            from django.utils import timezone
            self.goal.name = name
            self.goal.save(update_fields=['name'])
            self.change({'owner': self.owner.pk, 'pet': self.luna.pk, 'date': self.day,
                         'time': '12:00', 'reason': 'consulta'})
            handle = tools._add_ref(self.conv, 'cita', appointment.public_id)
            tools._save_refs(self.conv)
            matter_binding.record_derived(self.goal, self.conv, 'appointment_candidates', [{'handle': handle}],
                context=self.ctx, message_id=self.ctx.anchor.message_id,
                expected_snapshot=matter_binding.snapshot(self.goal), tool='get_appointments', observed_at=timezone.now())
            self.change({'appointment': appointment.pk})
            self.appointment = appointment
            self.goal.refresh_from_db()
            if kind == 'RESCHEDULE_APPOINTMENT': self.observe_slot()
            return appointment
        self.appointment = self.bind_appointment(name=name)
        a = self.appointment
        a.date = date.fromisoformat(self.day)
        a.start_time, a.end_time = time(15), time(15, 30)
        a.veterinarian = self.vet
        a.start_datetime, a.end_datetime = appointment_interval(self.org, a.date, a.start_time, a.end_time)
        a.timezone_at_creation = self.org.timezone
        a.save()
        self.goal.refresh_from_db()
        if kind == 'RESCHEDULE_APPOINTMENT':
            self.observe_slot()
        return a

    def prepare(self, capability=None, **kwargs):
        return super().prepare(capability or self.capability, **kwargs)

    def authorized(self):
        super().authorized()
        self.context = replace(self.context, capability=self.capability)
        return self.op

    def run_mutation(self):
        with enabled_mutations():
            return self.execute()

    def assert_no_effect(self, result):
        from apps.appointments.models import AppointmentMutationEffect
        self.assertNotEqual(result.status, 'SUCCEEDED', result)
        self.assertFalse(AppointmentMutationEffect.objects.filter(operation_id=self.op.operation_key).exists())
