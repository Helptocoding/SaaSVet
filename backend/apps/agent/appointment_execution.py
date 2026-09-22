"""B8B: narrow CREATE_APPOINTMENT adapter; callable only by the B8A registry.

No request/LLM arguments. Every field is rebuilt from the immutable operation.
This module performs no dispatch, opens no gates and sends nothing externally.
"""
import logging
from datetime import date, time
from types import SimpleNamespace

from django.db import transaction

from apps.appointments.creation import (
    AppointmentCommand, CreationRejected, appointment_interval, create_appointment, validate_creation,
)
from apps.appointments.models import Appointment, AppointmentStatusChange
from .operation_schema import canonicalize

logger = logging.getLogger('agent.events')
EVENTS = frozenset((
    'appointment_execution_requested', 'appointment_precondition_failed',
    'appointment_slot_unavailable', 'appointment_schedule_closed', 'appointment_created',
    'appointment_reconciled', 'appointment_duplicate_suppressed',
    'appointment_evidence_mismatch', 'appointment_execution_uncertain',
))


def observe(event):
    if event not in EVENTS:
        raise ValueError('Unknown appointment execution event')
    transaction.on_commit(lambda: logger.info('AGENT_B8B_' + event.upper(),
        extra={'event': event, 'count': 1, 'schema': 1}), robust=True)


def command_for(operation):
    if operation.operation_kind != 'CREATE_APPOINTMENT':
        raise ValueError('Wrong adapter kind')
    p = canonicalize(operation.operation_kind, operation.parameters,
                     version=operation.parameters_schema_version)
    if p != operation.parameters or p['pet_id'] != operation.pet_id:
        raise ValueError('Inconsistent operation parameters')
    return AppointmentCommand(organization_id=operation.organization_id, pet_id=p['pet_id'],
        veterinarian_id=p['veterinarian_id'], date=date.fromisoformat(p['date']),
        start_time=time.fromisoformat(p['start_time']), end_time=time.fromisoformat(p['end_time']),
        reason=p['reason'], source_operation_key=operation.operation_key,
        source_parameters_digest=operation.parameters_digest)


def _absence(operation):
    from .operation_execution import AdapterResult
    return AdapterResult('ABSENT', no_effect_confirmed=True,
        operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)


def _precondition_failure(reason):
    from .operation_execution import PreconditionResult
    observe('appointment_precondition_failed')
    if reason == 'slot_unavailable':
        observe('appointment_slot_unavailable')
    elif reason == 'schedule_closed':
        observe('appointment_schedule_closed')
    return PreconditionResult(False, reason)


def _state_has_creation_history(appointment):
    # Creation has scheduled as its initial state. Subsequent ordinary human
    # lifecycle transitions do not undo creation; require their durable chain.
    state = 'scheduled'
    for old, new in AppointmentStatusChange.objects.filter(
            organization_id=appointment.organization_id, appointment=appointment).order_by(
                'created_at', 'pk').values_list('from_status', 'to_status'):
        if old != state:
            return False
        state = new
    return state == appointment.status


class CreateAppointmentAdapter:
    transaction_mode = 'LOCAL_ATOMIC'
    reconcile_terminal = True

    def validate_preconditions(self, operation, context):
        from .operation_execution import PreconditionResult
        try:
            command = command_for(operation)
            if (operation.contact.owner_id != operation.owner_id
                    or operation.contact.organization_id != operation.organization_id):
                return _precondition_failure('entity_scope')
            validate_creation(command, require_schedule=True, owner_id=operation.owner_id,
                expected_timezone=operation.preconditions['clinic_timezone'])
        except CreationRejected as exc:
            return _precondition_failure(exc.reason)
        return PreconditionResult(True)

    def reconcile(self, operation, context):
        from .operation_execution import AdapterResult, EffectEvidence
        # Global UUID lookup is deliberate: a wrong-tenant link is contradictory
        # evidence, not absence. No data from this query is exposed to the actor.
        appointment = Appointment.all_objects.filter(source_operation_id=operation.operation_key).first()
        if appointment is None:
            return _absence(operation)
        try:
            command = command_for(operation)
            zone = operation.preconditions['clinic_timezone']
            start, end = appointment_interval(SimpleNamespace(timezone=zone), command.date,
                command.start_time, command.end_time, strict_local=True)
            matches = (
                appointment.source_parameters_digest == operation.parameters_digest
                and appointment.organization_id == operation.organization_id
                and appointment.pet_id == command.pet_id
                and appointment.veterinarian_id == command.veterinarian_id
                and appointment.date == command.date
                and appointment.start_time == command.start_time
                and appointment.end_time == command.end_time
                and appointment.start_datetime == start and appointment.end_datetime == end
                and appointment.timezone_at_creation == zone
                and appointment.reason == command.reason
                and appointment.category == 'general_consultation'
                and not appointment.walk_in
                and _state_has_creation_history(appointment)
            )
            evidence = EffectEvidence(operation.operation_key, appointment.source_parameters_digest,
                str(appointment.public_id), appointment.created_at)
            if matches and evidence.matches(operation):
                observe('appointment_reconciled')
                return AdapterResult('SUCCEEDED', evidence)
        except (ValueError, TypeError, KeyError, CreationRejected):
            pass
        observe('appointment_evidence_mismatch')
        observe('appointment_execution_uncertain')
        return AdapterResult('UNCERTAIN', reason='appointment_evidence_mismatch')

    def execute(self, operation, context):
        from .operation_execution import AdapterResult
        try:
            # Re-check the exact interval immediately at INSERT in the same
            # transaction. No fallback vet/date/pet/walk-in on any rejection.
            create_appointment(command_for(operation), require_schedule=True,
                owner_id=operation.owner_id, expected_timezone=operation.preconditions['clinic_timezone'])
        except CreationRejected as exc:
            _precondition_failure(exc.reason)
            absence = self.reconcile(operation, context)
            if absence.status == 'ABSENT' and absence.proves_absence_for(operation):
                return AdapterResult('FAILED', reason=exc.reason, no_effect_confirmed=True,
                    operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)
            return AdapterResult('UNCERTAIN', reason='appointment_evidence_mismatch')
        observe('appointment_created')
        return self.reconcile(operation, context)
