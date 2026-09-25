"""Real B8D consent/effect fixtures; gates opened only in isolated tests."""
from contextlib import contextmanager
from unittest.mock import patch
from django.db import models
from django.test import override_settings
from .b8c_support import MutationFixtures


@contextmanager
def enabled_attendance():
    with patch('apps.agent.intake.write_is_contained', return_value=False), override_settings(
        AGENT_B7B_CONSENT_ENABLED=True, AGENT_OPERATION_EXECUTION_ENABLED={
            'CONFIRM_ATTENDANCE': True, 'CANCEL_APPOINTMENT': True, 'RESCHEDULE_APPOINTMENT': True}):
        yield


def make_legacy_attendance(operation):
    """Reproduce the real pre-B8D shape/digest, never migrate its consent."""
    from apps.agent.operations import digest_bindings
    from apps.agent.operation_schema import digest
    pre = dict(operation.preconditions)
    pre.pop('appointment_snapshot', None)
    pre.pop('attendance_contract', None)
    pre['schema'] = 1
    operation.preconditions = pre
    historical = digest(operation.operation_kind, operation.parameters, bindings=digest_bindings(operation))
    models.QuerySet.update(type(operation).objects.filter(pk=operation.pk),
        preconditions=pre, parameters_digest=historical)
    operation.refresh_from_db()


class AttendanceFixtures(MutationFixtures):
    capability = 'confirm_appointment'

    def mutation(self, kind='CONFIRM_ATTENDANCE', appointment=None):
        return super().mutation(kind, appointment)

    def run_mutation(self):
        with enabled_attendance():
            return self.execute()

    def human_status(self, status):
        from apps.appointments.views import update_status
        from apps.appointments.services import current_state
        from apps.users.models import User
        from rest_framework.test import APIRequestFactory, force_authenticate
        self.appointment.refresh_from_db()
        human, _ = User.objects.get_or_create(organization=self.org, username='b8d-human',
            defaults={'role': 'ADMIN', 'is_staff': True})
        request = APIRequestFactory().patch('/status/',
            {'expected_state': current_state(self.appointment), 'status': status}, format='json')
        force_authenticate(request, user=human)
        response = update_status(request, pk=str(self.appointment.public_id))
        self.assertEqual(response.status_code, 200, response.data)
        return response
