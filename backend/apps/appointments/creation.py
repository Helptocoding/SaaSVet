"""Shared scheduled-appointment domain. Human serializer and B8B converge here.

INV-D remains PostgreSQL's existing exclusion constraint plus ordered vet locks.
Reception retains its existing hours policy; restricted autonomous commands must
also prove the clinic window. No HTTP, LLM, reservation table or default vet.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone as dt_timezone
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.core.datetime_utils import get_context_timezone, local_date_time_to_utc
from apps.core.sanitize import sanitize_text
from apps.organizations.models import Organization, OrganizationSchedule
from apps.patients.models import Owner, Pet
from apps.users.models import User
from .models import Appointment
from .services import (
    ACTIVE_STATUSES, VETERINARIAN_ABSENT_MESSAGE, lock_veterinarians, is_no_overlap_violation,
    NO_OVERLAP_EXCEPTIONS,
)


@dataclass(frozen=True)
class AppointmentCommand:
    organization_id: int
    pet_id: int
    veterinarian_id: int | None
    date: date
    start_time: time
    end_time: time
    reason: str
    category: str = 'general_consultation'
    notes: str = ''
    status: str = 'scheduled'
    cancellation_reason: str = ''
    idempotency_key: str | None = None
    source_operation_key: UUID | None = None
    source_parameters_digest: str | None = None


class CreationRejected(APIException):
    status_code = 400
    default_code = 'validation_error'

    def __init__(self, reason):
        self.reason = reason
        messages = {
            'slot_unavailable': 'Ya existe una cita para este veterinario en ese horario',
            'schedule_closed': 'El intervalo no está dentro del horario de atención vigente.',
            'schedule_elapsed': 'No se pueden agendar citas en el pasado.',
            'invalid_local_time': 'La hora local es inexistente o ambigua; requiere otra propuesta.',
            'entity_scope': 'Las entidades de la cita ya no son válidas.',
            'entity_inactive': 'La mascota o el profesional ya no está activo.',
            'precondition_failed': 'La definición de la cita requiere una nueva propuesta.',
            'veterinarian_absent': VETERINARIAN_ABSENT_MESSAGE,
        }
        code = 'slot_taken' if reason == 'slot_unavailable' else reason
        super().__init__(messages[reason], code=code)
        self.default_code = code
        self.error_payload = {'errors': {'error': [str(self.detail)]}}


def schedule_windows(row):
    """Exact local windows, shared with READ; absent configuration is closed."""
    if row is None or row.is_closed or not (row.opens_at and row.closes_at):
        return ()
    if row.opens_at >= row.closes_at:
        return ()
    if row.has_break:
        if not (row.break_start and row.break_end
                and row.opens_at < row.break_start < row.break_end < row.closes_at):
            return ()
        return ((row.opens_at, row.break_start), (row.break_end, row.closes_at))
    return ((row.opens_at, row.closes_at),)


def _share_rows(model, **filters):
    """PostgreSQL shared row lock: concurrent readers, config/identity writers wait.

    Stable org/config/entity rows, never a clinic-wide exclusive mutex. All
    filters here are trusted exact integer IDs; ORM compiles and binds SQL.
    """
    if not connection.in_atomic_block or connection.vendor != 'postgresql':
        raise RuntimeError('Appointment creation requires atomic PostgreSQL')
    query = model._base_manager.filter(**filters).order_by('pk')
    sql, params = query.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute(sql + ' FOR SHARE', params)
        cursor.fetchall()
    return list(query)


def appointment_interval(org, day, start, end, *, strict_local=False):
    if (type(day) is not date or type(start) is not time or type(end) is not time
            or start.tzinfo is not None or end.tzinfo is not None or end <= start):
        raise CreationRejected('precondition_failed')
    zone = get_context_timezone(org)
    if strict_local:
        for wall_time in (start, end):
            wall = datetime.combine(day, wall_time)
            instants = set()
            for fold in (0, 1):
                candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(dt_timezone.utc)
                if candidate.astimezone(zone).replace(tzinfo=None) == wall:
                    instants.add(candidate)
            if len(instants) != 1:
                raise CreationRejected('invalid_local_time')
    start_utc = local_date_time_to_utc(org, day, start)
    end_utc = local_date_time_to_utc(org, day, end)
    if end_utc <= start_utc:
        raise CreationRejected('invalid_local_time')
    return start_utc, end_utc


def slot_conflicts(command, start_utc, end_utc, *, exclude_appointment_id=None):
    if command.veterinarian_id is None or command.status not in ACTIVE_STATUSES:
        return False
    # all_objects matches GiST: is_active is deliberately NOT its predicate.
    # Also reject overlapping legacy rows without UTC anchors conservatively.
    return Appointment.all_objects.filter(organization_id=command.organization_id,
        veterinarian_id=command.veterinarian_id, status__in=ACTIVE_STATUSES).filter(
            Q(start_datetime__lt=end_utc, end_datetime__gt=start_utc)
            | (Q(start_datetime__isnull=True) | Q(end_datetime__isnull=True))
            & Q(date=command.date, start_time__lt=command.end_time, end_time__gt=command.start_time)
        ).exclude(pk=exclude_appointment_id).exists()


def validate_creation(command, *, require_schedule=False, expected_timezone=None, owner_id=None):
    """Hold all domain locks until outer LOCAL_ATOMIC commit; re-read entities."""
    organizations = _share_rows(Organization, pk=command.organization_id)
    if not organizations:
        raise CreationRejected('entity_scope')
    org = organizations[0]
    if not org.is_active:
        raise CreationRejected('entity_inactive')
    if expected_timezone is not None and org.timezone != expected_timezone:
        raise CreationRejected('precondition_failed')
    schedules = _share_rows(OrganizationSchedule, organization_id=org.pk,
                           weekday=command.date.isoweekday()) if require_schedule else []
    lock_veterinarians(org.pk, command.veterinarian_id)
    # Owner before pet, using the exact operation owner when restricted.
    if owner_id is None:
        owner_id = Pet.all_objects.filter(pk=command.pet_id, organization_id=org.pk).values_list(
            'owner_id', flat=True).first()
    owners = _share_rows(Owner, pk=owner_id, organization_id=org.pk)
    pets = _share_rows(Pet, pk=command.pet_id, organization_id=org.pk)
    if not pets or not owners or pets[0].owner_id != owner_id:
        raise CreationRejected('entity_scope')
    if not pets[0].is_active or not owners[0].is_active:
        raise CreationRejected('entity_inactive')
    if require_schedule and pets[0].is_generic:
        raise CreationRejected('entity_scope')
    if command.veterinarian_id:
        vet = User.objects.filter(pk=command.veterinarian_id, organization_id=org.pk).first()
        if not vet or not vet.is_active:
            raise CreationRejected('entity_inactive')
        # ADR p66: atiende quien es VET o ADMIN que atiende (predicado único).
        from apps.users.professional import is_clinician
        if require_schedule and not is_clinician(vet):
            raise CreationRejected('entity_scope')
        # ADR p67: una ausencia vigente bloquea la cita, con la fila del
        # veterinario ya bloqueada arriba (la ausencia toma la misma fila).
        from apps.users.absences import is_absent
        if command.status in ACTIVE_STATUSES and is_absent(org.pk, vet.pk, command.date):
            raise CreationRejected('veterinarian_absent')
    start_utc, end_utc = appointment_interval(org, command.date, command.start_time,
                                             command.end_time, strict_local=require_schedule)
    if start_utc < timezone.now():
        raise CreationRejected('schedule_elapsed')
    if require_schedule:
        if sanitize_text(command.reason, max_length=255) != command.reason:
            raise CreationRejected('precondition_failed')
        windows = schedule_windows(schedules[0] if schedules else None)
        if not any(start <= command.start_time and command.end_time <= end for start, end in windows):
            raise CreationRejected('schedule_closed')
    if slot_conflicts(command, start_utc, end_utc):
        raise CreationRejected('slot_unavailable')
    return org, start_utc, end_utc


@transaction.atomic
def create_appointment(command: AppointmentCommand, *, require_schedule=False,
                       expected_timezone=None, owner_id=None):
    org, start_utc, end_utc = validate_creation(command, require_schedule=require_schedule,
        expected_timezone=expected_timezone, owner_id=owner_id)
    try:
        with transaction.atomic():
            return Appointment.objects.create(organization=org, pet_id=command.pet_id,
                veterinarian_id=command.veterinarian_id, date=command.date,
                start_time=command.start_time, end_time=command.end_time,
                start_datetime=start_utc, end_datetime=end_utc, timezone_at_creation=org.timezone,
                reason=command.reason, category=command.category, notes=command.notes,
                status=command.status, cancellation_reason=command.cancellation_reason,
                idempotency_key=command.idempotency_key,
                source_operation_id=command.source_operation_key,
                source_parameters_digest=command.source_parameters_digest)
    except NO_OVERLAP_EXCEPTIONS as exc:
        if is_no_overlap_violation(exc):
            raise CreationRejected('slot_unavailable') from exc
        raise
