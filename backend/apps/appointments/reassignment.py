"""Reasignación en bloque de citas por atender a otro veterinario (ADR p67).

Decisión del PO: se elige UN destino para todas las citas; cada una se mueve si
el horario del destino está libre ese día. Las que no se pueden mover se quedan
como estaban y se devuelven con su motivo para resolverlas a mano. Nada se
desplaza de hora ni de día: solo cambia el veterinario.

Garantías que se conservan (las mismas que una edición individual):

- **INV-A**: cada cita viaja con la tupla `expected_state` que el usuario vio.
  Si la cita cambió (estado, fecha, hora o veterinario), se omite con
  `appointment_changed` — no es un 409 de toda la operación, porque las demás
  citas siguen siendo válidas.
- **INV-D**: se bloquean origen y destino (`lock_veterinarians`, orden por pk)
  antes de leer, así que el pre-chequeo de solape es fiable; la restricción de
  exclusión sigue siendo la garantía y su violación se traduce a `slot_taken`.
- **Ausencias** (ADR p67): no se mueve una cita a un día en que el destino está
  ausente.

Cada cita movida deja su `AppointmentStatusChange` (mismo estado, motivo de
reasignación), como ya hace la asignación de paciente.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import Appointment, AppointmentStatusChange
from .services import (
    ACTIVE_STATUSES,
    NO_OVERLAP_EXCEPTIONS,
    UPCOMING_STATUSES,
    is_no_overlap_violation,
    lock_veterinarians,
    matches_expected_state,
)

logger = logging.getLogger('appointments.events')

MAX_REASSIGN = 100

SKIP_MESSAGES = {
    'not_found': 'La cita no existe en esta clínica.',
    'appointment_changed': 'La cita cambió desde que se mostró; revísala en la agenda.',
    'not_reassignable': 'La cita ya no está por atender.',
    'veterinarian_absent': 'El veterinario destino está ausente ese día.',
    'slot_taken': 'El veterinario destino ya tiene una cita en ese horario.',
}


def _display_name(user):
    return user.get_full_name().strip() or user.username


def _destination_busy(organization_id, target_id, appointment):
    return Appointment.all_objects.filter(
        organization_id=organization_id,
        veterinarian_id=target_id,
        status__in=ACTIVE_STATUSES,
        start_datetime__lt=appointment.end_datetime,
        end_datetime__gt=appointment.start_datetime,
    ).exclude(pk=appointment.pk).exists()


def _skip_code(appointment, expected, *, organization_id, source_id, target_id, now):
    from apps.users.absences import is_absent

    if appointment is None:
        return 'not_found'
    if appointment.veterinarian_id != source_id or not matches_expected_state(appointment, expected):
        return 'appointment_changed'
    if (appointment.status not in UPCOMING_STATUSES or appointment.start_datetime is None
            or appointment.end_datetime is None or appointment.start_datetime < now):
        return 'not_reassignable'
    if is_absent(organization_id, target_id, appointment.date):
        return 'veterinarian_absent'
    if _destination_busy(organization_id, target_id, appointment):
        return 'slot_taken'
    return None


@transaction.atomic
def reassign_appointments(*, actor, organization, source, target, items, request_id=''):
    """Mueve las citas de ``source`` a ``target``.

    ``items``: lista de ``(public_id, expected_state)`` ya normalizados por
    ``parse_expected_state``. ``target`` debe ser un clínico activo de la
    clínica; se vuelve a comprobar con su fila bloqueada. Devuelve
    ``{'moved': [public_id], 'skipped': [{public_id, code, message}]}``.
    """
    from rest_framework.exceptions import ValidationError

    from apps.users.models import StaffAccessEvent, User
    from apps.users.professional import is_clinician
    from apps.users.services import record_staff_event

    lock_veterinarians(organization.pk, source.pk, target.pk)
    target_row = User.objects.get(pk=target.pk)
    if (not target_row.is_active or target_row.organization_id != organization.pk
            or not is_clinician(target_row)):
        raise ValidationError({'target_public_id': [
            'El veterinario destino ya no está activo o no atiende pacientes.']})

    public_ids = [public_id for public_id, _ in items]
    rows = {
        str(row.public_id): row
        for row in Appointment.objects.select_for_update()
        .filter(organization=organization, public_id__in=public_ids)
        .order_by('pk')
    }
    now = timezone.now()
    reason = (f"Veterinario reasignado de '{_display_name(source)}' "
              f"a '{_display_name(target_row)}'")
    moved, skipped = [], []
    for public_id, expected in items:
        appointment = rows.get(str(public_id))
        code = _skip_code(appointment, expected, organization_id=organization.pk,
                          source_id=source.pk, target_id=target_row.pk, now=now)
        if code is None:
            try:
                with transaction.atomic():
                    appointment.veterinarian = target_row
                    appointment.save(update_fields=['veterinarian'])
                    AppointmentStatusChange.objects.create(
                        appointment=appointment,
                        from_status=appointment.status,
                        to_status=appointment.status,
                        changed_by=actor,
                        reason=reason,
                        organization=organization,
                    )
            except NO_OVERLAP_EXCEPTIONS as exc:
                if not is_no_overlap_violation(exc):
                    raise
                appointment.veterinarian_id = source.pk
                code = 'slot_taken'
        if code is None:
            moved.append(str(public_id))
        else:
            skipped.append({'public_id': str(public_id), 'code': code,
                            'message': SKIP_MESSAGES[code]})

    if moved:
        record_staff_event(
            member=source, actor=actor, kind=StaffAccessEvent.KIND_APPOINTMENTS_REASSIGNED,
            changes={'moved': len(moved), 'skipped': len(skipped),
                     'target': str(target_row.public_id)},
            request_id=request_id,
        )
    transaction.on_commit(lambda: logger.info('APPOINTMENTS_REASSIGNED', extra={
        'organization_id': organization.pk, 'actor_id': actor.pk,
        'source_id': source.pk, 'target_id': target_row.pk,
        'moved': len(moved), 'skipped': len(skipped),
    }), robust=True)
    return {'moved': moved, 'skipped': skipped}
