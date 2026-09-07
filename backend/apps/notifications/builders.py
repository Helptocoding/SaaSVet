from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone

from apps.core.permissions import user_has_permission
from .models import NotificationReceipt
from .policies import APPOINTMENT_DELAYED_MINUTES, APPOINTMENT_UPCOMING_MINUTES


def _utc_iso(dt):
    return dt.astimezone(dt_timezone.utc).isoformat()


def _can_see_appointment(user, appointment):
    if getattr(appointment, 'veterinarian_id', None) == getattr(user, 'pk', None):
        return True
    return user_has_permission(user, 'appointment.list')


def _receipt_map(org, user, keys):
    if not keys:
        return {}
    qs = NotificationReceipt.objects.for_organization(org).filter(
        user=user, notification_key__in=list(keys),
    )
    return {r.notification_key: r for r in qs}


def build_appointment_derived(org, user, now=None):
    now = now or timezone.now()
    upcoming_before = now + timedelta(minutes=APPOINTMENT_UPCOMING_MINUTES)
    delayed_after = now - timedelta(minutes=APPOINTMENT_DELAYED_MINUTES)
    from apps.appointments.models import Appointment
    qs = (
        Appointment.objects.for_organization(org)
        .filter(status__in=('scheduled', 'confirmed'))
        .filter(start_datetime__isnull=False)
        .filter(start_datetime__lte=upcoming_before)
        .select_related('pet', 'veterinarian')
        .order_by('start_datetime')[:100]
    )
    items = []
    for appt in qs:
        start = appt.start_datetime
        if start is None:
            continue
        if not _can_see_appointment(user, appt):
            continue
        if start > now:
            if start > upcoming_before:
                continue
            ntype = 'appointment_upcoming'
        else:
            if start > delayed_after:
                continue
            if start < now - timedelta(hours=24):
                continue
            ntype = 'appointment_delayed'
        key = f"appt:{appt.public_id}:{ntype.split('_')[1]}:{_utc_iso(start)}"
        pet_name = getattr(getattr(appt, 'pet', None), 'name', None)
        vet = getattr(appt, 'veterinarian', None)
        vet_name = None
        if vet is not None:
            vet_name = f"{getattr(vet, 'first_name', '')} {getattr(vet, 'last_name', '')}".strip() or getattr(vet, 'username', None)
        if ntype == 'appointment_upcoming':
            title = f"{pet_name or 'Mascota'} tiene cita en {APPOINTMENT_UPCOMING_MINUTES} minutos"
        else:
            title = f"La cita de {pet_name or 'mascota'} lleva retraso"
        items.append({
            'key': key,
            'source': 'derived',
            'type': ntype,
            'title': title,
            'body': f"{pet_name or ''} · {vet_name or 'Sin asignar'} · {start.astimezone(dt_timezone.utc).strftime('%H:%M UTC')}".strip(' ·'),
            'occurred_at': start,
            'entity': {'type': 'appointment', 'public_id': str(appt.public_id)},
            'priority': 'attention' if ntype == 'appointment_upcoming' else 'important',
            'active': True,
        })
    seen = _receipt_map(org, user, [i['key'] for i in items])
    for item in items:
        receipt = seen.get(item['key'])
        item['seen'] = receipt.seen_at is not None if receipt else False
    return [i for i in items if not i['seen'] or True]
