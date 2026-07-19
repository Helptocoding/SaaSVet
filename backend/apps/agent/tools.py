"""
agent/tools.py — Registry y tools de lectura F1 (É-F1 PR-10; spec §9).

Reglas vinculantes:
- Una responsabilidad por tool; proyecciones MÍNIMAS (R4: al LLM viaja lo
  que el cliente necesita oír, jamás el registro completo).
- El LLM refiere entidades por HANDLES efímeros (`mascota_1`, `cita_2`)
  registrados en `Conversation.flow['refs']`; el resolver traduce y valida
  server-side — un handle desconocido es denegación dura (R3/R7).
- `min_verification` es metadata para el Policy Engine (PR-11): la tool
  además re-verifica su propio piso (defensa en profundidad).
- Cifras de stock, costos y PII financiera: PROHIBIDOS en proyecciones (G7).
"""
import unicodedata
from dataclasses import dataclass, field

from django.utils import timezone

from .executor import format_local_datetime, format_local_wallclock
from .models import ContactIdentity, Conversation, HumanHandoff

MAX_ITEMS = 5
MAX_PETS = 10

_MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
           'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')

_APPT_STATE_LABEL = {
    'scheduled': 'programada',
    'confirmed': 'confirmada',
    'in_progress': 'en consulta',
}

_VACCINE_STATE_LABEL = {
    'current': 'al día',
    'overdue': 'refuerzo vencido',
    'no_scheduled': 'sin refuerzo programado',
}


@dataclass
class ToolOutcome:
    ok: bool
    data: object = None            # proyección para el LLM
    client_error: str = ''         # guía conversacional si falló (spec §2.5)
    summary: dict = field(default_factory=dict)  # redactado, para auditoría
    # Tier-2 (É-F2): la tool PROPONE una mutación → el planner encola este
    # texto de confirmación y NO ejecuta hasta la afirmativa del cliente.
    needs_confirmation: bool = False
    confirmation_text: str = ''


def _norm(text):
    text = unicodedata.normalize('NFD', (text or '').lower())
    return ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')


def _format_date(iso_date):
    if not iso_date:
        return None
    try:
        year, month, day = str(iso_date)[:10].split('-')
        return f"{int(day)} de {_MONTHS[int(month) - 1]} de {year}"
    except (ValueError, IndexError):
        return str(iso_date)


# ---------------------------------------------------------------------------
# Handles (refs) — viven en Conversation.flow['refs']
# ---------------------------------------------------------------------------

def _refs(conversation):
    return conversation.flow.setdefault('refs', {})


def _add_ref(conversation, prefix, public_id):
    """Handle estable dentro de la conversación (reusa si ya existe)."""
    refs = _refs(conversation)
    public_id = str(public_id)
    for handle, value in refs.items():
        if value == public_id and handle.startswith(prefix):
            return handle
    handle = f"{prefix}_{sum(1 for h in refs if h.startswith(prefix)) + 1}"
    refs[handle] = public_id
    return handle


def resolve_handle(conversation, handle):
    """public_id del handle, o None (None = denegación dura del caller)."""
    return _refs(conversation).get(str(handle))


def _save_refs(conversation):
    conversation.save(update_fields=['flow'])


def _verification_ok(conversation, minimum):
    order = ['unknown', 'phone_match', 'confirmed_in_chat', 'staff_verified']
    contact = conversation.contact
    if minimum == 'unknown':
        return True
    if contact.owner_id is None:
        return False
    return order.index(contact.verification_level) >= order.index(minimum)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def list_my_pets(conversation, executor, args, triggered_by=None):
    owner = conversation.contact.owner
    status, data = executor.call(
        'GET', '/api/pets/', tool_name='list_my_pets',
        params={'owner': str(owner.public_id)},
        args_redacted={},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'pets': len(d) if isinstance(d, list) else 0},
    )
    if status >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    pets = data if isinstance(data, list) else data.get('results', [])
    projection = []
    for pet in pets[:MAX_PETS]:
        handle = _add_ref(conversation, 'mascota', pet['public_id'])
        projection.append({
            'handle': handle,
            'nombre': pet.get('name', ''),
            'especie': pet.get('species', '') or 'sin especie',
        })
    _save_refs(conversation)
    return ToolOutcome(ok=True, data=projection,
                       summary={'pets': len(projection)})


def get_vaccine_status(conversation, executor, args, triggered_by=None):
    public_id = resolve_handle(conversation, args.get('pet_handle'))
    if public_id is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')

    status, data = executor.call(
        'GET', '/api/vaccines/', tool_name='get_vaccine_status',
        params={'pet': public_id},
        args_redacted={'pet_handle': args.get('pet_handle')},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'vaccines': len(d) if isinstance(d, list) else 0},
    )
    if status >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    vaccines = data if isinstance(data, list) else data.get('results', [])
    projection = [{
        'vacuna': v.get('vaccine_name', ''),
        'aplicada': _format_date(v.get('application_date')),
        'proximo_refuerzo': _format_date(v.get('next_due_date')),
        'estado': _VACCINE_STATE_LABEL.get(v.get('status'), v.get('status', '')),
    } for v in vaccines[:MAX_ITEMS * 2]]
    return ToolOutcome(ok=True, data=projection,
                       summary={'vaccines': len(projection)})


def get_clinic_info(conversation, executor, args, triggered_by=None):
    """LOCAL (sin HTTP): AgentSettings.faq_facts + horario. G1: sin dato
    configurado se responde honesto — jamás se inventa."""
    from .models import AgentSettings
    settings_obj = AgentSettings.objects.filter(
        organization=conversation.organization,
    ).first()
    facts = dict((settings_obj.faq_facts or {}) if settings_obj else {})
    if settings_obj and settings_obj.business_hours:
        facts.setdefault('horario', _humanize_hours(settings_obj.business_hours))

    topic = _norm(args.get('topic', ''))
    if topic:
        matched = {
            key: value for key, value in facts.items()
            if topic in _norm(key) or _norm(key) in topic
        }
        facts = matched or {'_sin_dato': True}

    executor.record_local(
        tool_name='get_clinic_info',
        args_redacted={'topic': args.get('topic', '')},
        summary={'facts': len([k for k in facts if k != '_sin_dato'])},
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(ok=True, data=facts, summary={'facts': len(facts)})


_DAY_LABEL = {'mon': 'lun', 'tue': 'mar', 'wed': 'mié', 'thu': 'jue',
              'fri': 'vie', 'sat': 'sáb', 'sun': 'dom'}


def _humanize_hours(business_hours):
    parts = []
    for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'):
        ranges = business_hours.get(day)
        if ranges:
            spans = ' y '.join(f"{a} a {b}" for a, b in ranges)
            parts.append(f"{_DAY_LABEL[day]} {spans}")
    return '; '.join(parts)


def get_service_catalog(conversation, executor, args, triggered_by=None):
    status, data = executor.call(
        'GET', '/api/billing/services/', tool_name='get_service_catalog',
        args_redacted={'query': args.get('query', '')},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'services': len(d) if isinstance(d, list) else 0},
    )
    if status >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    services = data if isinstance(data, list) else data.get('results', [])
    query = _norm(args.get('query', ''))
    if query:
        services = [s for s in services if query in _norm(s.get('name', ''))]

    projection = []
    for service in services[:MAX_ITEMS]:
        # ServiceSerializer expone `base_price` (billing/serializers.py:52).
        price = service.get('base_price')
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            price_value = 0.0
        projection.append({
            'servicio': service.get('name', ''),
            # Precio nulo/0 → None: el planner responde "lo cotiza el
            # equipo", jamás "$0" (spec INT-11).
            'precio': f"${price_value:,.2f}" if price_value > 0 else None,
        })
    return ToolOutcome(ok=True, data=projection,
                       summary={'matches': len(projection)})


def check_product_availability(conversation, executor, args, triggered_by=None):
    status, data = executor.call(
        'GET', '/api/inventory/products/',
        tool_name='check_product_availability',
        args_redacted={'query': args.get('query', '')},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'products': len(d) if isinstance(d, list) else 0},
    )
    if status >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    products = data if isinstance(data, list) else data.get('results', [])
    query = _norm(args.get('query', ''))
    matches = [p for p in products if query and query in _norm(p.get('name', ''))]

    projection = []
    for product in matches[:MAX_ITEMS]:
        projection.append({
            'producto': product.get('name', ''),
            # SOLO sí/no (G7): jamás cantidades ni costos.
            'disponible': _product_available(product),
            'requiere_receta': bool(product.get('requires_prescription')),
        })
    return ToolOutcome(ok=True, data=projection,
                       summary={'matches': len(projection)})


def _product_available(product):
    try:
        if float(product.get('stock_quantity') or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    for presentation in product.get('presentations') or []:
        try:
            if float(presentation.get('stock') or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def list_upcoming_appointments(conversation, executor, args, triggered_by=None):
    pet_handle = args.get('pet_handle')
    if pet_handle:
        public_id = resolve_handle(conversation, pet_handle)
        if public_id is None:
            return ToolOutcome(ok=False, client_error='unknown_handle')
        pet_ids = [public_id]
    else:
        pets_outcome = list_my_pets(conversation, executor, {},
                                    triggered_by=triggered_by)
        if not pets_outcome.ok:
            return pets_outcome
        pet_ids = [resolve_handle(conversation, p['handle'])
                   for p in pets_outcome.data]

    now = timezone.now()
    upcoming = []
    for pet_id in pet_ids:
        status, data = executor.call(
            'GET', '/api/appointments/', tool_name='list_upcoming_appointments',
            params={'pet': pet_id},
            args_redacted={'pet_handle': pet_handle or '(todas)'},
            triggered_by_message=triggered_by,
            result_summarizer=lambda d: {'appointments': len(d) if isinstance(d, list) else 0},
        )
        if status >= 400:
            return ToolOutcome(ok=False, client_error='tool_failure')
        rows = data if isinstance(data, list) else data.get('results', [])
        for appointment in rows:
            if appointment.get('status') not in ('scheduled', 'confirmed'):
                continue
            start = appointment.get('start_datetime') or (
                f"{appointment.get('date')}T{appointment.get('start_time')}"
            )
            try:
                from datetime import datetime
                from datetime import timezone as dt_timezone
                start_dt = datetime.fromisoformat(
                    str(start).replace('Z', '+00:00')
                )
                if timezone.is_naive(start_dt):
                    start_dt = timezone.make_aware(start_dt, dt_timezone.utc)
            except ValueError:
                continue
            if start_dt < now:
                continue
            upcoming.append((start_dt, appointment))

    upcoming.sort(key=lambda pair: pair[0])
    projection = []
    for start_dt, appointment in upcoming[:MAX_ITEMS]:
        handle = _add_ref(conversation, 'cita', appointment['public_id'])
        projection.append({
            'handle': handle,
            'mascota': appointment.get('pet_name', ''),
            'cuando': format_local_datetime(start_dt, conversation.organization),
            'estado': _APPT_STATE_LABEL.get(
                appointment.get('status'), appointment.get('status', ''),
            ),
        })
    _save_refs(conversation)
    return ToolOutcome(ok=True, data=projection,
                       summary={'upcoming': len(projection)})


SLOT_MINUTES = 30  # duración de cita estándar (misma que el walk-in del dominio)


def _weekday_ranges(business_hours, weekday_index):
    key = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[weekday_index]
    ranges = business_hours.get(key, []) if isinstance(business_hours, dict) else []
    return ranges if isinstance(ranges, list) else []


def _time_bucket_ok(hhmm, preferred):
    """Filtro por franja coloquial (UX-07): mañana/tarde/noche o 'HH:MM'±1h."""
    if not preferred:
        return True
    p = _norm(preferred)
    hour = int(hhmm[:2])
    if 'manana' in p or 'temprano' in p:
        return 6 <= hour < 12
    if 'tarde' in p:
        return 12 <= hour < 18
    if 'noche' in p:
        return hour >= 18
    # "tipo 4", "a las 4", "4 pm" → hora ± ventana
    digits = ''.join(c for c in p if c.isdigit())
    if digits:
        target = int(digits[:2]) if len(digits) >= 2 else int(digits)
        if 'pm' in p or 'tarde' in p:
            target = target + 12 if target < 12 else target
        return abs(hour - target) <= 1
    return True


def _resolve_scheduling_vet(organization, agent_settings):
    """Vet objetivo para ofertar/agendar (Q14). fixed_vet → default; si no hay,
    el primer VET activo de la org (fallback determinista)."""
    from apps.users.models import User
    if agent_settings and agent_settings.default_veterinarian_id:
        vet = agent_settings.default_veterinarian
        if vet and vet.is_active:
            return vet
    return (
        User.objects.filter(organization=organization, role='VET', is_active=True)
        .order_by('pk').first()
    )


def _free_slots_for_day(org, executor, day, vet, ranges, *, preferred='',
                        triggered_by=None, tool_name='find_available_slots'):
    """[hhmm…] libres ese día = business_hours (`ranges`) ∩ ocupación real del
    `vet` (GET /appointments/). None si la API falla. El caller resuelve vet y
    ranges (para mapear sus propios errores). Compartido por la tool de slots y
    la retención al cancelar (UX-11)."""
    from datetime import datetime, timedelta

    date_str = day.isoformat()
    status_code, data = executor.call(
        'GET', '/api/appointments/', tool_name=tool_name,
        params={'date': date_str, 'veterinarian': str(vet.public_id)},
        args_redacted={'date': date_str, 'preferred': preferred},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'occupied': len(d) if isinstance(d, list) else 0},
    )
    if status_code >= 400:
        return None
    appts = data if isinstance(data, list) else data.get('results', [])
    occupied = {
        (a.get('start_time') or '')[:5]
        for a in appts
        if a.get('status') in ('scheduled', 'confirmed', 'in_progress')
    }
    today = timezone.localdate()
    now_hhmm = timezone.localtime().strftime('%H:%M') if day == today else '00:00'
    slots = []
    for start, end in [(r[0], r[1]) for r in ranges if len(r) == 2]:
        cursor = datetime.strptime(start, '%H:%M')
        limit = datetime.strptime(end, '%H:%M')
        while cursor + timedelta(minutes=SLOT_MINUTES) <= limit:
            hhmm = cursor.strftime('%H:%M')
            if (
                hhmm not in occupied
                and hhmm > now_hhmm
                and _time_bucket_ok(hhmm, preferred)
            ):
                slots.append(hhmm)
                if len(slots) >= MAX_ITEMS:
                    break
            cursor += timedelta(minutes=SLOT_MINUTES)
        if len(slots) >= MAX_ITEMS:
            break
    return slots


def suggest_retention_slots(conversation, executor, *, max_days=7):
    """UX-11: (fecha_label, [hora_labels≤2]) del PRÓXIMO día con hueco desde
    mañana, o (None, []). Se usa al cancelar para ofrecer reagendar con
    horarios concretos. Tolerante a errores (salta el día que falle)."""
    from datetime import timedelta

    from .models import AgentSettings
    org = conversation.organization
    agent_settings = AgentSettings.objects.filter(organization=org).first()
    business_hours = (agent_settings.business_hours or {}) if agent_settings else {}
    vet = _resolve_scheduling_vet(org, agent_settings)
    if vet is None:
        return None, []
    day = timezone.localdate() + timedelta(days=1)
    for _ in range(max_days):
        ranges = _weekday_ranges(business_hours, day.weekday())
        if ranges:
            slots = _free_slots_for_day(
                org, executor, day, vet, ranges,
                tool_name='suggest_retention_slots')
            if slots:
                fecha = format_local_wallclock(
                    day.isoformat(), slots[0]).rsplit(',', 1)[0]
                return fecha, [_hhmm_label(h) for h in slots[:2]]
        day += timedelta(days=1)
    return None, []


def find_available_slots(conversation, executor, args, triggered_by=None):
    """Horarios libres de UN día (spec T9, UX-06). Compone la ocupación real
    (GET /appointments/?date=&veterinarian=) ∩ business_hours. ≤3 slots.

    Una responsabilidad = un día, un vet, una llamada a la API. Si el día
    está lleno → lista vacía y el planner ofrece otro día."""
    from datetime import datetime

    from .models import AgentSettings

    date_str = (args.get('date') or '').strip()
    if not date_str:
        return ToolOutcome(ok=False, client_error='need_date')
    try:
        day = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except ValueError:
        return ToolOutcome(ok=False, client_error='bad_date')

    org = conversation.organization
    today = timezone.localdate()
    if day < today:
        return ToolOutcome(ok=False, client_error='past_date')

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    business_hours = (agent_settings.business_hours or {}) if agent_settings else {}
    ranges = _weekday_ranges(business_hours, day.weekday())
    if not ranges:
        return ToolOutcome(ok=True, data=[], summary={'slots': 0, 'closed': True})

    vet = _resolve_scheduling_vet(org, agent_settings)
    if vet is None:
        return ToolOutcome(ok=False, client_error='no_vet')

    preferred = args.get('preferred_time', '')
    slots = _free_slots_for_day(
        org, executor, day, vet, ranges,
        preferred=preferred, triggered_by=triggered_by)
    if slots is None:
        return ToolOutcome(ok=False, client_error='tool_failure')

    projection = [{
        'fecha': format_local_wallclock(
            date_str, hhmm,
        ).rsplit(',', 1)[0],  # "martes 21 de julio" (la hora va aparte)
        'hora': _hhmm_label(hhmm),
        'iso_date': date_str,
        'iso_time': hhmm,
    } for hhmm in slots[:3]]
    return ToolOutcome(ok=True, data=projection, summary={'slots': len(projection)})


def _hhmm_label(hhmm):
    hour, minute = int(hhmm[:2]), int(hhmm[3:5])
    ampm = 'a.m.' if hour < 12 else 'p.m.'
    h12 = hour % 12 or 12
    return f"{h12}:{minute:02d} {ampm}"


# ---------------------------------------------------------------------------
# Escritura de agenda (É-F2). Las tier-2 PROPONEN (stage + parafraseo); el
# planner ejecuta el commit tras la afirmativa del cliente (spec §2.4).
# ---------------------------------------------------------------------------

def _appt_end_time(time_str, minutes=SLOT_MINUTES):
    from datetime import datetime, timedelta
    t = datetime.strptime(time_str[:5], '%H:%M')
    return (t + timedelta(minutes=minutes)).strftime('%H:%M')


def _future_or_error(org, date_str, time_str):
    """'' si la fecha/hora es futura; 'bad_date' o 'past_date' si no."""
    from datetime import datetime

    from apps.core.datetime_utils import local_date_time_to_utc
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        t = datetime.strptime(time_str[:5], '%H:%M').time()
    except ValueError:
        return 'bad_date'
    if local_date_time_to_utc(org, d, t) < timezone.now():
        return 'past_date'
    return ''


def _appt_when_label(appt, org):
    # El anchor UTC (start_datetime) es la fuente correcta; si faltara, cae al
    # wall-clock local (date+start_time) SIN conversión (no double-shift).
    anchor = appt.get('start_datetime')
    if anchor:
        return format_local_datetime(anchor, org)
    return format_local_wallclock(appt.get('date'), appt.get('start_time'))


def create_appointment(conversation, executor, args, triggered_by=None):
    from . import confirmations
    from .models import AgentSettings
    org = conversation.organization

    pet_pid = resolve_handle(conversation, args.get('pet_handle'))
    if pet_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    date_str = (args.get('date') or '')[:10]
    time_str = (args.get('time') or '')[:5]
    reason = (args.get('reason') or '').strip()
    if not (date_str and time_str and reason):
        return ToolOutcome(ok=False, client_error='need_data')
    err = _future_or_error(org, date_str, time_str)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    status_code, pet = executor.call(
        'GET', f'/api/pets/{pet_pid}/', tool_name='create_appointment',
        args_redacted={'pet_handle': args.get('pet_handle')},
        triggered_by_message=triggered_by,
    )
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    vet = _resolve_scheduling_vet(org, agent_settings)
    if vet is None:
        return ToolOutcome(ok=False, client_error='no_vet')

    import uuid
    fecha = format_local_wallclock(date_str, time_str)
    paraphrase = confirmations.CONFIRM_CREATE.format(
        pet=pet.get('name', ''), fecha=fecha, reason=reason,
    )
    staged = {
        'pet': pet.get('id'), 'veterinarian': vet.pk,
        'date': date_str, 'start_time': time_str,
        'end_time': _appt_end_time(time_str), 'reason': reason,
        'notes': f"Agendada por asistente virtual · conv {conversation.public_id}",
        'idempotency_key': uuid.uuid4().hex,
    }
    confirmations.stage_pending(conversation, tool='create_appointment',
                               args=staged, paraphrase=paraphrase)
    return ToolOutcome(ok=True, needs_confirmation=True,
                       confirmation_text=paraphrase, summary={'proposed': 'create'})


def commit_create_appointment(conversation, executor, args, triggered_by=None):
    body = {k: args[k] for k in
            ('pet', 'veterinarian', 'date', 'start_time', 'end_time', 'reason', 'notes')}
    status_code, data = executor.call(
        'POST', '/api/appointments/', tool_name='create_appointment',
        json=body, args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by,
        idempotency_key=args.get('idempotency_key'),
        extract_domain_id=lambda d: d.get('public_id'),
        result_summarizer=lambda d: {'status': d.get('status')},
    )
    if status_code == 400:
        return ToolOutcome(ok=False, client_error='slot_taken')
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    _add_ref(conversation, 'cita', data.get('public_id'))
    _save_refs(conversation)
    return ToolOutcome(ok=True, summary={'created': True}, data={
        'cuando': format_local_wallclock(args['date'], args['start_time']),
    })


def confirm_appointment(conversation, executor, args, triggered_by=None):
    """Tier-1 (INT-22): scheduled→confirmed, sin parafraseo (benigno)."""
    appt_pid = resolve_handle(conversation, args.get('appointment_handle'))
    if appt_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    status_code, data = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/status/',
        tool_name='confirm_appointment', json={'status': 'confirmed'},
        policy_tier='1', args_redacted={'appointment_handle': args.get('appointment_handle')},
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
        result_summarizer=lambda d: {'status': d.get('status')},
    )
    if status_code == 400:
        return ToolOutcome(ok=True, data={'already_or_invalid': True}, summary={'noop': True})
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    return ToolOutcome(ok=True, data={'confirmed': True}, summary={'confirmed': True})


def cancel_appointment(conversation, executor, args, triggered_by=None):
    from . import confirmations
    org = conversation.organization
    appt_pid = resolve_handle(conversation, args.get('appointment_handle'))
    if appt_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    status_code, appt = executor.call(
        'GET', f'/api/appointments/{appt_pid}/', tool_name='cancel_appointment',
        args_redacted={'appointment_handle': args.get('appointment_handle')},
        triggered_by_message=triggered_by,
    )
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    if appt.get('status') not in ('scheduled', 'confirmed'):
        return ToolOutcome(ok=False, client_error='not_cancelable')

    paraphrase = confirmations.CONFIRM_CANCEL.format(
        pet=appt.get('pet_name', ''), fecha=_appt_when_label(appt, org),
    )
    reason = (args.get('reason') or '').strip()
    annotation = f"asistente virtual · conv {conversation.public_id}"
    staged = {
        'appointment_public_id': appt_pid,
        'cancellation_reason': (f"{reason} · {annotation}" if reason else annotation)[:100],
    }
    confirmations.stage_pending(conversation, tool='cancel_appointment',
                               args=staged, paraphrase=paraphrase)
    return ToolOutcome(ok=True, needs_confirmation=True,
                       confirmation_text=paraphrase, summary={'proposed': 'cancel'})


def commit_cancel_appointment(conversation, executor, args, triggered_by=None):
    appt_pid = args['appointment_public_id']
    status_code, _ = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/status/',
        tool_name='cancel_appointment',
        json={'status': 'canceled', 'cancellation_reason': args.get('cancellation_reason', '')},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
    )
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    return ToolOutcome(ok=True, data={'canceled': True}, summary={'canceled': True})


def reschedule_appointment(conversation, executor, args, triggered_by=None):
    from . import confirmations
    org = conversation.organization
    appt_pid = resolve_handle(conversation, args.get('appointment_handle'))
    if appt_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    new_date = (args.get('new_date') or '')[:10]
    new_time = (args.get('new_time') or '')[:5]
    if not (new_date and new_time):
        return ToolOutcome(ok=False, client_error='need_data')
    err = _future_or_error(org, new_date, new_time)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    status_code, appt = executor.call(
        'GET', f'/api/appointments/{appt_pid}/', tool_name='reschedule_appointment',
        args_redacted={'appointment_handle': args.get('appointment_handle')},
        triggered_by_message=triggered_by,
    )
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    if appt.get('status') not in ('scheduled', 'confirmed'):
        return ToolOutcome(ok=False, client_error='not_reschedulable')

    paraphrase = confirmations.CONFIRM_RESCHEDULE.format(
        pet=appt.get('pet_name', ''),
        vieja=_appt_when_label(appt, org),
        nueva=format_local_wallclock(new_date, new_time),
    )
    staged = {
        'appointment_public_id': appt_pid, 'date': new_date,
        'start_time': new_time, 'end_time': _appt_end_time(new_time),
    }
    confirmations.stage_pending(conversation, tool='reschedule_appointment',
                               args=staged, paraphrase=paraphrase)
    return ToolOutcome(ok=True, needs_confirmation=True,
                       confirmation_text=paraphrase, summary={'proposed': 'reschedule'})


def commit_reschedule_appointment(conversation, executor, args, triggered_by=None):
    appt_pid = args['appointment_public_id']
    status_code, _ = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/', tool_name='reschedule_appointment',
        json={'date': args['date'], 'start_time': args['start_time'],
              'end_time': args['end_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
    )
    if status_code == 400:
        return ToolOutcome(ok=False, client_error='slot_taken')
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    return ToolOutcome(ok=True, summary={'rescheduled': True}, data={
        'cuando': format_local_wallclock(args['date'], args['start_time']),
    })


def _wa_id_to_local10(wa_id):
    """10 dígitos nacionales MX desde el wa_id (E.164 sin '+'); None si no
    alcanza. Los últimos 10 sirven con o sin el '1' legacy mexicano
    (5219371651868 y 529371651868 → 9371651868)."""
    digits = ''.join(c for c in str(wa_id or '') if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else None


def register_new_client_and_pet(conversation, executor, args, triggered_by=None):
    """Alta atómica de cliente NUEVO + 1ª mascota + 1ª cita (T11, tier-2).
    Llama al endpoint compuesto `create-with-patient` (Owner+Pet+Cita en una
    transacción, sin huérfanos) — el agente no orquesta la atomicidad."""
    from . import confirmations
    from .models import AgentSettings, ContactIdentity  # noqa: F401
    org = conversation.organization
    contact = conversation.contact

    # E-05 (parcial en 17a): si el número YA es de un cliente o es ambiguo,
    # nunca se auto-registra (la vinculación permanente es de PR-17b/humano).
    if contact.owner_id is not None:
        return ToolOutcome(ok=False, client_error='already_client')
    if contact.is_ambiguous:
        return ToolOutcome(ok=False, client_error='ambiguous_identity')

    owner_name = (args.get('owner_name') or '').strip()
    pet_name = (args.get('pet_name') or '').strip()
    species = (args.get('pet_species') or '').strip()
    date_str = (args.get('date') or '')[:10]
    time_str = (args.get('time') or '')[:5]
    reason = (args.get('reason') or '').strip()
    if not (owner_name and pet_name and date_str and time_str and reason):
        return ToolOutcome(ok=False, client_error='need_data')

    phone = _wa_id_to_local10(contact.external_id)
    if phone is None:
        return ToolOutcome(ok=False, client_error='bad_phone')
    err = _future_or_error(org, date_str, time_str)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    vet = _resolve_scheduling_vet(org, agent_settings)
    if vet is None:
        return ToolOutcome(ok=False, client_error='no_vet')

    import uuid
    fecha = format_local_wallclock(date_str, time_str)
    paraphrase = confirmations.CONFIRM_CREATE_NEW_CLIENT.format(
        owner=owner_name, pet=pet_name, especie=species or 'sin especificar',
        fecha=fecha, reason=reason)
    staged = {
        'owner_name': owner_name, 'owner_phone': phone,
        'pet_name': pet_name, 'pet_species': species,
        'veterinarian': vet.pk, 'date': date_str, 'start_time': time_str,
        'end_time': _appt_end_time(time_str), 'reason': reason,
        'notes': f"Alta por asistente virtual · conv {conversation.public_id}",
        'idempotency_key': uuid.uuid4().hex,
    }
    confirmations.stage_pending(conversation, tool='register_new_client_and_pet',
                               args=staged, paraphrase=paraphrase)
    return ToolOutcome(ok=True, needs_confirmation=True,
                       confirmation_text=paraphrase, summary={'proposed': 'register'})


def commit_register_new_client_and_pet(conversation, executor, args, triggered_by=None):
    from .models import ContactIdentity
    body = {k: args[k] for k in (
        'owner_name', 'owner_phone', 'pet_name', 'pet_species',
        'veterinarian', 'date', 'start_time', 'end_time', 'reason', 'notes')}
    status_code, data = executor.call(
        'POST', '/api/appointments/create-with-patient/',
        tool_name='register_new_client_and_pet', json=body,
        args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by,
        idempotency_key=args.get('idempotency_key'),
        extract_domain_id=lambda d: d.get('public_id'),
        result_summarizer=lambda d: {'status': d.get('status')})
    if status_code == 400:
        return ToolOutcome(ok=False, client_error='slot_taken')
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    # Auto-vínculo: el número queda ligado al owner recién creado (probó
    # control del número al escribir + aportó sus datos → confirmed_in_chat).
    owner_pid = data.get('owner_public_id')
    contact = conversation.contact
    if owner_pid and contact.owner_id is None:
        from apps.patients.models import Owner
        owner = Owner.objects.filter(
            organization=conversation.organization, public_id=owner_pid).first()
        if owner is not None:
            contact.owner = owner
            contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
            contact.verified_at = timezone.now()
            contact.linked_via = ContactIdentity.LINKED_SELF_REGISTER
            contact.save(update_fields=[
                'owner', 'verification_level', 'verified_at', 'linked_via'])

    _add_ref(conversation, 'cita', data.get('public_id'))
    _save_refs(conversation)
    return ToolOutcome(ok=True, summary={'registered': True}, data={
        'cuando': format_local_wallclock(args['date'], args['start_time'])})


# Ejecutores del pending_action confirmado (el planner los invoca).
COMMIT_HANDLERS = {
    'create_appointment': commit_create_appointment,
    'cancel_appointment': commit_cancel_appointment,
    'reschedule_appointment': commit_reschedule_appointment,
    'register_new_client_and_pet': commit_register_new_client_and_pet,
}


def request_human(conversation, executor, args, triggered_by=None):
    """LOCAL: crea el handoff y silencia al agente (E-02; disponible SIEMPRE)."""
    handoff = HumanHandoff(
        organization=conversation.organization,
        conversation=conversation,
        reason_code=HumanHandoff.REASON_EXPLICIT,
        reason_detail=str(args.get('reason', ''))[:200],
    )
    handoff.save()
    conversation.state = Conversation.STATE_HANDOFF_PENDING
    conversation.save(update_fields=['state'])
    executor.record_local(
        tool_name='request_human',
        args_redacted={},
        summary={'reason_code': HumanHandoff.REASON_EXPLICIT},
        policy_decision='escalated',
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(ok=True, data={'handoff': True},
                       summary={'handoff_id': handoff.pk})


# ---------------------------------------------------------------------------
# Registry (la spec §9 es el contrato; tiers en §11)
# ---------------------------------------------------------------------------

TOOL_SPECS = {
    'list_my_pets': {
        'handler': list_my_pets,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': 'Lista las mascotas registradas del cliente verificado.',
        'parameters': {'type': 'object', 'properties': {}, 'required': []},
    },
    'get_vaccine_status': {
        'handler': get_vaccine_status,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': 'Estado vacunal y próximas fechas de UNA mascota (por handle).',
        'parameters': {
            'type': 'object',
            'properties': {'pet_handle': {'type': 'string'}},
            'required': ['pet_handle'],
        },
    },
    'get_clinic_info': {
        'handler': get_clinic_info,
        'tier': '1',
        'min_verification': 'unknown',
        'description': 'Datos de la clínica: horario, dirección, indicaciones.',
        'parameters': {
            'type': 'object',
            'properties': {'topic': {'type': 'string'}},
            'required': [],
        },
    },
    'get_service_catalog': {
        'handler': get_service_catalog,
        'tier': '1',
        'min_verification': 'unknown',
        'description': 'Servicios de la clínica y su precio exacto.',
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string'}},
            'required': [],
        },
    },
    'check_product_availability': {
        'handler': check_product_availability,
        'tier': '1',
        'min_verification': 'unknown',
        'description': 'Si un producto se maneja y hay disponible (sí/no).',
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string'}},
            'required': ['query'],
        },
    },
    'list_upcoming_appointments': {
        'handler': list_upcoming_appointments,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': 'Próximas citas del cliente verificado (todas o por mascota).',
        'parameters': {
            'type': 'object',
            'properties': {'pet_handle': {'type': 'string'}},
            'required': [],
        },
    },
    'find_available_slots': {
        'handler': find_available_slots,
        'tier': '1',
        'min_verification': 'unknown',
        'description': (
            'Horarios libres de la clínica para UN día concreto (formato '
            'YYYY-MM-DD). Úsalo para proponer horarios antes de agendar. '
            'preferred_time opcional: "mañana"/"tarde"/"noche" o una hora.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'date': {'type': 'string',
                         'description': 'Día en formato YYYY-MM-DD'},
                'preferred_time': {'type': 'string'},
            },
            'required': ['date'],
        },
    },
    'create_appointment': {
        'handler': create_appointment,
        'tier': '2',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Agenda una cita para UNA mascota del cliente verificado. NO la '
            'crea de inmediato: PROPONE y espera el "sí" del cliente. Usa '
            'find_available_slots antes para ofrecer un horario libre. Fecha '
            'YYYY-MM-DD, hora HH:MM (24h).'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'pet_handle': {'type': 'string'},
                'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time': {'type': 'string', 'description': 'HH:MM (24h)'},
                'reason': {'type': 'string',
                           'description': 'Motivo de la cita'},
            },
            'required': ['pet_handle', 'date', 'time', 'reason'],
        },
    },
    'confirm_appointment': {
        'handler': confirm_appointment,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Marca como CONFIRMADA una cita ya agendada del cliente (cuando '
            'avisa que sí asistirá). Acción benigna, sin parafraseo.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'appointment_handle': {'type': 'string'}},
            'required': ['appointment_handle'],
        },
    },
    'cancel_appointment': {
        'handler': cancel_appointment,
        'tier': '2',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Cancela una cita del cliente verificado. PROPONE y espera el '
            '"sí" antes de cancelar.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'appointment_handle': {'type': 'string'},
                'reason': {'type': 'string'},
            },
            'required': ['appointment_handle'],
        },
    },
    'reschedule_appointment': {
        'handler': reschedule_appointment,
        'tier': '2',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Mueve una cita del cliente a otra fecha/hora. PROPONE y espera '
            'el "sí". new_date YYYY-MM-DD, new_time HH:MM.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'appointment_handle': {'type': 'string'},
                'new_date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'new_time': {'type': 'string', 'description': 'HH:MM (24h)'},
            },
            'required': ['appointment_handle', 'new_date', 'new_time'],
        },
    },
    'register_new_client_and_pet': {
        'handler': register_new_client_and_pet,
        'tier': '2',
        'min_verification': 'unknown',
        'description': (
            'Registra a un cliente NUEVO (que aún no está en el sistema) junto '
            'con su primera mascota y agenda su primera cita, en un solo paso. '
            'Úsalo SOLO cuando el contacto no es un cliente existente. PROPONE '
            'y espera el "sí". El teléfono se toma del propio WhatsApp — NO lo '
            'pidas. Fecha YYYY-MM-DD, hora HH:MM.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'owner_name': {'type': 'string',
                               'description': 'Nombre del cliente'},
                'pet_name': {'type': 'string'},
                'pet_species': {'type': 'string',
                                'description': 'perro/gato/… (opcional)'},
                'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time': {'type': 'string', 'description': 'HH:MM (24h)'},
                'reason': {'type': 'string'},
            },
            'required': ['owner_name', 'pet_name', 'date', 'time', 'reason'],
        },
    },
    'request_human': {
        'handler': request_human,
        'tier': '0',
        'min_verification': 'unknown',
        'description': 'Transfiere la conversación a una persona del equipo.',
        'parameters': {
            'type': 'object',
            'properties': {'reason': {'type': 'string'}},
            'required': [],
        },
    },
}


def as_openai_tools():
    """Specs en el formato de tool calling OpenAI-compatible (llm.py)."""
    return [{
        'type': 'function',
        'function': {
            'name': name,
            'description': spec['description'],
            'parameters': spec['parameters'],
        },
    } for name, spec in TOOL_SPECS.items()]


def run_tool(name, args, *, conversation, executor, triggered_by=None):
    """Punto único de ejecución. El Policy Engine (PR-11) valida tier y
    verificación ANTES; aquí queda la defensa en profundidad."""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return ToolOutcome(ok=False, client_error='unknown_tool')
    if not _verification_ok(conversation, spec['min_verification']):
        return ToolOutcome(ok=False, client_error='verification_required')
    return spec['handler'](conversation, executor, args or {},
                           triggered_by=triggered_by)
