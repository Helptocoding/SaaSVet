"""Narrow Agenda mutation authority, shared by human writes and B8C.

Human validation policy is preserved. Restricted commands additionally require an
immutable exact snapshot, clinic windows and current owner. No external effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from apps.core.datetime_utils import local_date_time_to_utc
from apps.core.sanitize import sanitize_text
from apps.organizations.models import Organization, OrganizationSchedule
from apps.patients.models import Owner, Pet
from apps.users.models import User
from .creation import (_share_rows, appointment_interval, schedule_windows, slot_conflicts,
                       CreationRejected)
from .models import Appointment, AppointmentStatusChange, AppointmentMutationEffect
from .services import lock_veterinarians, NO_OVERLAP_EXCEPTIONS, is_no_overlap_violation

MUTATION_KINDS = frozenset(('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT', 'CONFIRM_ATTENDANCE'))
ALLOWED_TRANSITIONS = {
    'scheduled': {'confirmed', 'in_progress', 'canceled', 'no_show'},
    'confirmed': {'in_progress', 'canceled', 'no_show'},
    'in_progress': {'done', 'canceled'}, 'done': set(),
    'canceled': {'scheduled'}, 'no_show': {'scheduled'},
}


class MutationRejected(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def appointment_snapshot(appointment):
    """Business precondition, deliberately independent of updated_at/audit/cache."""
    return {
        'schema': 1, 'appointment_id': appointment.pk,
        'public_id': str(appointment.public_id), 'organization_id': appointment.organization_id,
        'pet_id': appointment.pet_id, 'status': appointment.status,
        'date': appointment.date.isoformat(), 'start_time': appointment.start_time.isoformat(),
        'end_time': appointment.end_time.isoformat(),
        'start_datetime': appointment.start_datetime.isoformat() if appointment.start_datetime else None,
        'end_datetime': appointment.end_datetime.isoformat() if appointment.end_datetime else None,
        'timezone_at_creation': appointment.timezone_at_creation,
        'veterinarian_id': appointment.veterinarian_id,
        'walk_in': appointment.walk_in, 'is_active': appointment.is_active,
        'cancellation_reason': appointment.cancellation_reason,
    }


@dataclass(frozen=True)
class MutationCommand:
    kind: str
    organization_id: int
    appointment_id: int
    pet_id: int
    owner_id: int
    operation_key: UUID
    parameters_digest: str
    original: dict
    clinic_timezone: str
    date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    veterinarian_id: int | None = None
    cancellation_reason: str = ''


def appointment_has_started(appointment):
    start = appointment.start_datetime or local_date_time_to_utc(
        appointment.organization, appointment.date, appointment.start_time)
    return start <= timezone.now()


def set_schedule_fields(appointment, *, day, start, end, veterinarian_id, org,
                        strict_local=False):
    """Shared schedule transformation. Caller validates and saves under vet/row locks."""
    start_utc, end_utc = appointment_interval(org, day, start, end, strict_local=strict_local)
    appointment.date, appointment.start_time, appointment.end_time = day, start, end
    appointment.veterinarian_id = veterinarian_id
    appointment.start_datetime, appointment.end_datetime = start_utc, end_utc
    appointment.timezone_at_creation = org.timezone


def cancel_locked(appointment, *, reason='', actor=None, audit_reason=None):
    """Existing /status/ cancellation, without deleting clinical/financial records."""
    if 'canceled' not in ALLOWED_TRANSITIONS.get(appointment.status, set()):
        raise MutationRejected('appointment_not_mutable')
    if appointment_has_started(appointment):
        raise MutationRejected('schedule_elapsed')
    previous = appointment.status
    appointment.status = 'canceled'
    fields = ['status']
    if reason:
        appointment.cancellation_reason = reason
        fields.append('cancellation_reason')
    appointment.save(update_fields=fields)
    AppointmentStatusChange.objects.create(organization_id=appointment.organization_id,
        appointment=appointment, from_status=previous, to_status='canceled', changed_by=actor,
        reason=reason if audit_reason is None else audit_reason)


def confirm_locked(appointment, *, actor=None):
    """Human Agenda confirmation: intention to attend, no clinical side effects.

    Caller holds veterinarians then Appointment in its transaction. Human policy
    has no future-date restriction; the autonomous command validates it separately.
    """
    if not connection.in_atomic_block:
        raise MutationRejected('precondition_failed')
    if 'confirmed' not in ALLOWED_TRANSITIONS.get(appointment.status, set()):
        raise MutationRejected('appointment_not_mutable')
    previous = appointment.status
    appointment.status = 'confirmed'
    appointment.save(update_fields=['status'])
    return AppointmentStatusChange.objects.create(
        organization_id=appointment.organization_id, appointment=appointment,
        from_status=previous, to_status='confirmed', changed_by=actor, reason='')


def expected_after(command):
    """Pure authorized transition used both at effect and historical reconciliation."""
    after = dict(command.original)
    if command.kind == 'CONFIRM_ATTENDANCE':
        if after['status'] != 'scheduled':
            raise MutationRejected('appointment_not_mutable')
        after['status'] = 'confirmed'
    elif command.kind == 'CANCEL_APPOINTMENT':
        after['status'] = 'canceled'
        if command.cancellation_reason:
            after['cancellation_reason'] = command.cancellation_reason
    elif command.kind == 'RESCHEDULE_APPOINTMENT':
        start, end = appointment_interval(SimpleNamespace(timezone=command.clinic_timezone),
            command.date, command.start_time, command.end_time, strict_local=True)
        after.update(date=command.date.isoformat(), start_time=command.start_time.isoformat(),
            end_time=command.end_time.isoformat(), veterinarian_id=command.veterinarian_id,
            start_datetime=start.isoformat(), end_datetime=end.isoformat(),
            timezone_at_creation=command.clinic_timezone)
    else:
        raise MutationRejected('precondition_failed')
    return after


def validate_mutation(command):
    if command.kind not in MUTATION_KINDS or not connection.in_atomic_block:
        raise MutationRejected('precondition_failed')
    organizations = _share_rows(Organization, pk=command.organization_id)
    if not organizations:
        raise MutationRejected('entity_scope')
    org = organizations[0]
    if org.timezone != command.clinic_timezone:
        raise MutationRejected('precondition_failed')
    schedules = _share_rows(OrganizationSchedule, organization_id=org.pk,
        weekday=command.date.isoweekday()) if command.kind == 'RESCHEDULE_APPOINTMENT' else []
    # Only authorized resources, in deterministic order; a new original vet is
    # stale, never an additional lock acquired after Appointment.
    lock_veterinarians(org.pk, command.original['veterinarian_id'], command.veterinarian_id)
    appointment = Appointment.all_objects.select_for_update().filter(
        pk=command.appointment_id, organization_id=org.pk).first()
    if appointment is None:
        raise MutationRejected('entity_scope')
    if appointment_snapshot(appointment) != command.original:
        raise MutationRejected('appointment_changed')
    if appointment.pet_id != command.pet_id:
        raise MutationRejected('entity_scope')
    owners = _share_rows(Owner, pk=command.owner_id, organization_id=org.pk)
    pets = _share_rows(Pet, pk=command.pet_id, organization_id=org.pk)
    if not pets or not owners or pets[0].owner_id != command.owner_id or pets[0].is_generic:
        raise MutationRejected('entity_scope')
    if not appointment.is_active or not pets[0].is_active or not owners[0].is_active:
        raise MutationRejected('entity_inactive')
    if appointment.status not in ('scheduled', 'confirmed'):
        raise MutationRejected('appointment_not_mutable')
    if command.kind == 'CONFIRM_ATTENDANCE':
        if appointment.status != 'scheduled':
            raise MutationRejected('appointment_not_mutable')
        from apps.medical_records.models import MedicalRecord
        if MedicalRecord.all_objects.filter(appointment_id=appointment.pk).exists():
            raise MutationRejected('appointment_not_mutable')
    original_start, original_end = appointment_interval(org, appointment.date,
        appointment.start_time, appointment.end_time, strict_local=True)
    if ((appointment.start_datetime is not None and appointment.start_datetime != original_start)
            or (appointment.end_datetime is not None and appointment.end_datetime != original_end)
            or (appointment.start_datetime is not None and appointment.timezone_at_creation != org.timezone)):
        raise MutationRejected('appointment_changed')
    if original_start <= timezone.now():
        raise MutationRejected('schedule_elapsed')
    if command.kind == 'CANCEL_APPOINTMENT':
        if sanitize_text(command.cancellation_reason, max_length=100) != command.cancellation_reason:
            raise MutationRejected('precondition_failed')
    elif command.kind == 'RESCHEDULE_APPOINTMENT':
        if not User.objects.filter(pk=command.veterinarian_id, organization_id=org.pk,
                                   is_active=True, role='VET').exists():
            raise MutationRejected('entity_scope')
        start, end = appointment_interval(org, command.date, command.start_time,
                                          command.end_time, strict_local=True)
        if start <= timezone.now():
            raise MutationRejected('schedule_elapsed')
        if not any(a <= command.start_time and command.end_time <= b
                   for a, b in schedule_windows(schedules[0] if schedules else None)):
            raise MutationRejected('schedule_closed')
        slot = SimpleNamespace(organization_id=org.pk, veterinarian_id=command.veterinarian_id,
            date=command.date, start_time=command.start_time, end_time=command.end_time,
            status=appointment.status)
        if slot_conflicts(slot, start, end, exclude_appointment_id=appointment.pk):
            raise MutationRejected('slot_unavailable')
        if (appointment.date, appointment.start_time, appointment.end_time, appointment.veterinarian_id) == (
                command.date, command.start_time, command.end_time, command.veterinarian_id):
            raise MutationRejected('appointment_no_change')
    return appointment, org


def mutate_appointment(command):
    """One LOCAL_ATOMIC effect and immutable proof, using caller's guard transaction."""
    appointment, org = validate_mutation(command)
    try:
        with transaction.atomic():
            status_change = None
            if command.kind == 'CANCEL_APPOINTMENT':
                cancel_locked(appointment, reason=command.cancellation_reason)
            elif command.kind == 'CONFIRM_ATTENDANCE':
                status_change = confirm_locked(appointment)
            else:
                set_schedule_fields(appointment, day=command.date, start=command.start_time,
                    end=command.end_time, veterinarian_id=command.veterinarian_id, org=org,
                    strict_local=True)
                appointment.save(update_fields=['date', 'start_time', 'end_time', 'veterinarian',
                    'start_datetime', 'end_datetime', 'timezone_at_creation'])
            with connection.cursor() as cursor:
                cursor.execute('SELECT statement_timestamp()')
                stamp = cursor.fetchone()[0]
            return AppointmentMutationEffect.objects.create(organization_id=org.pk,
                operation_id=command.operation_key, parameters_digest=command.parameters_digest,
                kind=command.kind, appointment=appointment, before=command.original,
                after=appointment_snapshot(appointment), committed_at=stamp,
                status_change=status_change)
    except NO_OVERLAP_EXCEPTIONS as exc:
        if is_no_overlap_violation(exc):
            raise MutationRejected('slot_unavailable') from exc
        raise
