"""Ausencias de integrantes por días completos (ADR p67).

Fuente única de «¿está ausente este integrante este día?». La consultan la
agenda humana (alta, edición, reactivación, atención sin cita), los comandos
del agente y la reasignación de citas.

Serialización: registrar una ausencia bloquea la fila ``User`` del integrante,
la misma que ``appointments.services.lock_veterinarians`` toma antes de crear o
mover una cita. Una cita y una ausencia concurrentes sobre el mismo integrante
se ordenan: la que llega segunda ve a la primera ya confirmada. Los bloqueos de
``User`` son siempre por ``pk`` ascendente, así que no hay ciclos.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.core.datetime_utils import org_today_local

logger = logging.getLogger('users.events')

ABSENCE_MANAGE_PERMISSION = 'staff.manage_absences'
MAX_ABSENCE_DAYS = 366


class AbsenceOverlap(APIException):
    """409: el integrante ya tiene una ausencia vigente que se cruza."""
    status_code = 409
    default_detail = 'Ya hay una ausencia registrada que se cruza con esas fechas.'
    default_code = 'absence_overlap'


def active_absences(organization_id):
    from apps.users.models import StaffAbsence
    return StaffAbsence.objects.filter(organization_id=organization_id, cancelled_at__isnull=True)


def absent_member_ids(organization_id, day, member_ids=None) -> set:
    """PKs de los integrantes con ausencia vigente ese día local."""
    if day is None:
        return set()
    qs = active_absences(organization_id).filter(start_date__lte=day, end_date__gte=day)
    if member_ids is not None:
        qs = qs.filter(member_id__in=list(member_ids))
    return set(qs.values_list('member_id', flat=True))


def is_absent(organization_id, member_id, day) -> bool:
    if not member_id or day is None:
        return False
    return active_absences(organization_id).filter(
        member_id=member_id, start_date__lte=day, end_date__gte=day,
    ).exists()


def validate_absence_dates(organization, start_date, end_date):
    """Fechas válidas para registrar: orden, no terminada y como máximo un año."""
    errors = {}
    if end_date < start_date:
        errors['end_date'] = ['La fecha final no puede ser anterior a la inicial.']
    elif end_date < org_today_local(organization):
        errors['end_date'] = ['La ausencia ya terminó; registra fechas de hoy en adelante.']
    elif (end_date - start_date) >= timedelta(days=MAX_ABSENCE_DAYS):
        errors['end_date'] = [f'Una ausencia dura como máximo {MAX_ABSENCE_DAYS} días.']
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def create_absence(*, actor, member, start_date, end_date, kind, request_id=''):
    """Registra una ausencia vigente de ``member``. No toca sus citas: quien la
    registra recibe la lista de las afectadas y decide si reasignarlas."""
    from apps.core.permissions import user_has_permission
    from apps.users.models import StaffAbsence, StaffAccessEvent
    from apps.users.services import ActorInactive, _lock_users, record_staff_event

    locked = _lock_users(pks=(actor.pk, member.pk))
    actor_row = locked.get(actor.pk)
    member_row = locked.get(member.pk)
    if actor_row is None or not actor_row.is_active:
        raise ActorInactive()
    if not user_has_permission(actor_row, ABSENCE_MANAGE_PERMISSION):
        raise PermissionDenied('No tienes permiso para registrar ausencias.')
    if (member_row is None or not member_row.is_active
            or member_row.organization_id != actor_row.organization_id):
        raise NotFound()

    organization = actor_row.organization
    validate_absence_dates(organization, start_date, end_date)
    if active_absences(organization.pk).filter(
            member_id=member_row.pk, start_date__lte=end_date, end_date__gte=start_date).exists():
        raise AbsenceOverlap()

    absence = StaffAbsence.objects.create(
        organization=organization, member=member_row, start_date=start_date,
        end_date=end_date, kind=kind, created_by=actor_row,
    )
    record_staff_event(
        member=member_row, actor=actor_row, kind=StaffAccessEvent.KIND_ABSENCE_ADDED,
        changes={'start_date': start_date.isoformat(), 'end_date': end_date.isoformat(),
                 'kind': kind},
        request_id=request_id,
    )
    transaction.on_commit(lambda: logger.info('STAFF_ABSENCE_ADDED', extra={
        'organization_id': organization.pk, 'member_id': member_row.pk,
        'actor_id': actor_row.pk, 'absence': str(absence.public_id),
        'days': (end_date - start_date).days + 1,
    }), robust=True)
    return absence


@transaction.atomic
def cancel_absence(*, actor, absence, request_id=''):
    """Cancela una ausencia vigente. Repetirlo no cambia nada."""
    from apps.users.models import StaffAbsence, StaffAccessEvent
    from apps.users.services import record_staff_event

    row = StaffAbsence.objects.select_for_update().select_related('member').get(pk=absence.pk)
    if row.cancelled_at is not None:
        return row
    row.cancelled_at = timezone.now()
    row.cancelled_by = actor
    row.save(update_fields=['cancelled_at', 'cancelled_by'])
    record_staff_event(
        member=row.member, actor=actor, kind=StaffAccessEvent.KIND_ABSENCE_CANCELLED,
        changes={'start_date': row.start_date.isoformat(), 'end_date': row.end_date.isoformat(),
                 'kind': row.kind},
        request_id=request_id,
    )
    transaction.on_commit(lambda: logger.info('STAFF_ABSENCE_CANCELLED', extra={
        'organization_id': row.organization_id, 'member_id': row.member_id,
        'actor_id': actor.pk, 'absence': str(row.public_id),
    }), robust=True)
    return row
