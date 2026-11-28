"""Escrituras de la configuración de la clínica (ADR p70).

Toda escritura de Configuración pasa por aquí (y el catálogo de servicios por
`billing.catalog_services`): cada servicio compara contra lo persistido y
bloqueado, guarda solo lo que cambió y registra un `OrganizationConfigEvent` en
la misma transacción (D9). Las vistas y los serializers solo validan y delegan.
"""
from datetime import time as time_type, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.core.request_context import get_request_id

from .models import (
    Organization, OrganizationClosure, OrganizationConfigEvent, OrganizationSchedule,
    OrganizationSettings,
)
from .timezones import TIMEZONE_CODES


def _require_transaction(name):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(f'{name}() requiere una transacción abierta.')


def config_value(value):
    """Valor guardable en ``changes``: JSON plano, sin tipos de Python."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, time_type):
        return value.strftime('%H:%M')
    return value


def record_config_event(*, organization, actor, kind, changes=None, subject=None):
    """Único escritor de `OrganizationConfigEvent` (gate estático).

    Corre dentro de la transacción del cambio: un rollback no deja evento.
    """
    _require_transaction('record_config_event')
    return OrganizationConfigEvent.objects.create(
        organization_id=getattr(organization, 'pk', organization),
        actor=actor if actor is not None and getattr(actor, 'is_authenticated', False) else None,
        kind=kind,
        changes=changes or {},
        subject=subject or {},
        request_id=(get_request_id() or '')[:64],
    )


def config_diff(current, data):
    """``{campo: [antes, después]}`` de los campos de ``data`` que cambian."""
    return {
        field: [config_value(getattr(current, field)), config_value(value)]
        for field, value in data.items()
        if getattr(current, field) != value
    }


TIMEZONE_NOT_SUPPORTED_MESSAGE = 'Elige una de las zonas horarias de México de la lista.'


class TimezoneChangeBlocked(APIException):
    """409 — hay citas por atender, así que la zona no se cambia (ADR p70 D1).

    No es un error técnico: las citas guardan fecha y hora local junto a su
    instante, y cambiar la zona desalinearía las dos. El cuerpo lleva el conteo
    para que la pantalla diga cuántas son.
    """
    status_code = 409
    default_code = 'timezone_change_blocked'

    def __init__(self, count):
        noun = 'cita por atender' if count == 1 else 'citas por atender'
        super().__init__(
            f'No se puede cambiar la zona horaria: hay {count} {noun}. '
            'Cambia la zona cuando no queden citas futuras.'
        )
        self.error_payload = {'future_appointments': count}


def change_organization_timezone(*, actor, organization, timezone_name):
    """Cambia la zona de la clínica, o no escribe nada (ADR p70 D1).

    1. Bloquea la fila de la organización (`FOR NO KEY UPDATE`): toda operación
       que deriva un instante de la zona toma antes esa fila con `FOR SHARE`
       (`appointments.creation.share_lock_organization`), así que espera a este
       cambio o este cambio la espera a ella. Nunca se calcula con una zona a
       medio cambiar.
    2. Con la fila tomada cuenta las citas futuras activas. Si hay, 409.
    3. Guarda la zona y su registro en la misma transacción.

    Devuelve True si cambió. Debe correr dentro de una transacción.
    """
    _require_transaction('change_organization_timezone')
    locked = Organization.objects.select_for_update(no_key=True).get(pk=organization.pk)
    if locked.timezone == timezone_name:
        return False
    if timezone_name not in TIMEZONE_CODES:
        raise ValidationError({'timezone': [TIMEZONE_NOT_SUPPORTED_MESSAGE]})

    from apps.appointments.services import future_active_appointments_count
    count = future_active_appointments_count(locked.pk, timezone.now())
    if count:
        raise TimezoneChangeBlocked(count)

    old_timezone = locked.timezone
    locked.timezone = timezone_name
    locked.timezone_updated_at = timezone.now()
    locked.save(update_fields=['timezone', 'timezone_updated_at'])
    record_config_event(
        organization=locked, actor=actor, kind=OrganizationConfigEvent.KIND_TIMEZONE_CHANGED,
        changes={'timezone': [old_timezone, timezone_name]},
    )
    organization.timezone = locked.timezone
    organization.timezone_updated_at = locked.timezone_updated_at
    return True


def update_clinic_profile(*, actor, organization, data):
    """Datos de la clínica (`PATCH /organizations/me/`).

    La zona va primero y por su propio servicio (bloqueo, citas, evento
    `timezone_changed`). Lo demás se compara contra la fila bloqueada y se
    guarda solo lo que cambió (`update_fields`): un `save()` completo podría
    deshacer un cambio de zona hecho mientras tanto. `Organization.save` sigue
    aplicando INV-L sobre el teléfono.
    """
    data = dict(data)
    timezone_name = data.pop('timezone', None)
    with transaction.atomic():
        if timezone_name is not None:
            change_organization_timezone(
                actor=actor, organization=organization, timezone_name=timezone_name,
            )
        locked = Organization.objects.select_for_update(no_key=True).get(pk=organization.pk)
        changes = config_diff(locked, data)
        if changes:
            for field in changes:
                setattr(locked, field, data[field])
            locked.save(update_fields=list(changes))
            record_config_event(
                organization=locked, actor=actor,
                kind=OrganizationConfigEvent.KIND_CLINIC_UPDATED, changes=changes,
            )
    organization.refresh_from_db()
    return organization


def update_operating_rules(*, actor, organization, data):
    """Reglas de operación (`PATCH /organizations/settings/`)."""
    with transaction.atomic():
        OrganizationSettings.objects.get_or_create(organization=organization)
        locked = OrganizationSettings.objects.select_for_update().get(organization=organization)
        changes = config_diff(locked, data)
        if changes:
            for field in changes:
                setattr(locked, field, data[field])
            locked.save(update_fields=list(changes))
            record_config_event(
                organization=organization, actor=actor,
                kind=OrganizationConfigEvent.KIND_RULES_UPDATED, changes=changes,
            )
    return locked


SCHEDULE_FIELDS = ('is_closed', 'opens_at', 'closes_at', 'has_break', 'break_start', 'break_end')


def schedule_snapshot(row):
    """Un día del horario, ya normalizado por `OrganizationSchedule.clean`."""
    if row is None:
        return None
    return {field: config_value(getattr(row, field)) for field in SCHEDULE_FIELDS}


def replace_schedule(*, actor, organization, days):
    """Reemplaza la semana completa (`PUT /organizations/schedule/`), atómico.

    Compara cada día ya normalizado (un día cerrado pierde sus horas) contra el
    guardado bajo bloqueo y solo escribe los que cambian. El evento lleva
    ``{"weekday_N": [antes, después]}`` de esos días.
    """
    changes = {}
    with transaction.atomic():
        existing = {
            row.weekday: row for row in
            OrganizationSchedule.objects.filter(organization=organization).select_for_update()
        }
        for item in days:
            weekday = item['weekday']
            row = existing.get(weekday)
            before = schedule_snapshot(row)
            if row is None:
                row = OrganizationSchedule(organization=organization, weekday=weekday)
            for field in SCHEDULE_FIELDS:
                if field in item:
                    setattr(row, field, item[field])
            row.full_clean()
            after = schedule_snapshot(row)
            if before != after:
                row.save()
                changes[f'weekday_{weekday}'] = [before, after]
        if changes:
            record_config_event(
                organization=organization, actor=actor,
                kind=OrganizationConfigEvent.KIND_SCHEDULE_REPLACED, changes=changes,
            )
    return OrganizationSchedule.objects.filter(organization=organization).order_by('weekday')


# ---------------------------------------------------------------------------
# Cierres excepcionales (ADR p70 D6, plan F2.1)
# ---------------------------------------------------------------------------

MAX_CLOSURE_DAYS = 366
CLOSURE_REASON_MAX = 120


class ClosureOverlap(APIException):
    """409: ya hay un cierre vigente que se cruza con esas fechas."""
    status_code = 409
    default_detail = 'Ya hay un cierre registrado que se cruza con esas fechas.'
    default_code = 'closure_overlap'


def active_closures(organization_id):
    """Cierres vigentes de la clínica. Único punto de entrada: siempre por organización."""
    return OrganizationClosure.objects.filter(
        organization_id=organization_id, cancelled_at__isnull=True)


def is_closed_on(organization_id, day):
    """¿Hay un cierre vigente ese día local? Fuente única para el agente y la agenda."""
    if day is None:
        return False
    return active_closures(organization_id).filter(
        start_date__lte=day, end_date__gte=day).exists()


def _closure_weekdays(start_date, end_date):
    if (end_date - start_date).days >= 6:
        return list(range(1, 8))
    return sorted({(start_date + timedelta(days=n)).isoweekday()
                   for n in range((end_date - start_date).days + 1)})


def _lock_schedule_days(organization_id, start_date, end_date):
    """`FOR UPDATE` sobre las filas del horario de esos días de la semana, en
    orden de `weekday`. El agente toma la del día con `FOR SHARE` antes de
    agendar (`appointments.creation.validate_creation`): un cierre y una cita
    del agente en ese día se serializan."""
    return list(
        OrganizationSchedule.objects.select_for_update()
        .filter(organization_id=organization_id,
                weekday__in=_closure_weekdays(start_date, end_date))
        .order_by('weekday')
    )


def _clean_closure(organization, start_date, end_date, reason):
    from apps.core.datetime_utils import org_today_local
    from apps.core.sanitize import sanitize_text
    errors = {}
    if end_date < start_date:
        errors['end_date'] = ['La fecha final no puede ser anterior a la inicial.']
    elif end_date < org_today_local(organization):
        errors['end_date'] = ['Ese cierre ya pasó; registra fechas de hoy en adelante.']
    elif (end_date - start_date) >= timedelta(days=MAX_CLOSURE_DAYS):
        errors['end_date'] = [f'Un cierre dura como máximo {MAX_CLOSURE_DAYS} días.']
    clean_reason = sanitize_text(reason or '', max_length=CLOSURE_REASON_MAX).strip()
    if not clean_reason:
        errors['reason'] = ['Escribe el motivo del cierre (por ejemplo, «Día festivo»).']
    if errors:
        raise ValidationError(errors)
    return clean_reason


def appointments_in_range(organization_id, start_date, end_date):
    """Citas por atender en esos días: el cierre no las mueve (D6 a), se avisan."""
    from apps.appointments.services import ACTIVE_STATUSES
    from apps.appointments.models import Appointment
    return Appointment.all_objects.filter(
        organization_id=organization_id, status__in=ACTIVE_STATUSES,
        date__gte=start_date, date__lte=end_date,
    ).count()


def _closure_subject(closure):
    return {'type': 'closure', 'public_id': str(closure.public_id),
            'start_date': closure.start_date.isoformat(),
            'end_date': closure.end_date.isoformat()}


def create_closure(*, actor, organization, start_date, end_date, reason):
    """Registra un cierre vigente. No toca las citas: devuelve cuántas hay esos
    días para que el personal decida (el agente ya no agendará ahí)."""
    with transaction.atomic():
        _lock_schedule_days(organization.pk, start_date, end_date)
        clean_reason = _clean_closure(organization, start_date, end_date, reason)
        if active_closures(organization.pk).filter(
                start_date__lte=end_date, end_date__gte=start_date).exists():
            raise ClosureOverlap()
        closure = OrganizationClosure.objects.create(
            organization=organization, start_date=start_date, end_date=end_date,
            reason=clean_reason, created_by=actor,
        )
        record_config_event(
            organization=organization, actor=actor,
            kind=OrganizationConfigEvent.KIND_CLOSURE_ADDED,
            changes={'start_date': [None, start_date.isoformat()],
                     'end_date': [None, end_date.isoformat()],
                     'reason': [None, clean_reason]},
            subject=_closure_subject(closure),
        )
        affected = appointments_in_range(organization.pk, start_date, end_date)
    return closure, affected


def cancel_closure(*, actor, closure):
    """Cancela un cierre vigente y reabre esos días. Repetirlo no cambia nada."""
    with transaction.atomic():
        _lock_schedule_days(closure.organization_id, closure.start_date, closure.end_date)
        row = OrganizationClosure.objects.select_for_update().get(pk=closure.pk)
        if row.cancelled_at is not None:
            return row
        row.cancelled_at = timezone.now()
        row.cancelled_by = actor
        row.save(update_fields=['cancelled_at', 'cancelled_by'])
        record_config_event(
            organization=row.organization_id, actor=actor,
            kind=OrganizationConfigEvent.KIND_CLOSURE_CANCELLED,
            changes={'cancelled': [False, True]},
            subject={**_closure_subject(row), 'reason': row.reason},
        )
    return row
