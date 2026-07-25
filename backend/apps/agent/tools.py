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

from apps.core.datetime_utils import org_now_local, org_today_local

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
    detail: str = ''               # mensaje real del dominio (W1-8), ya legible
    summary: dict = field(default_factory=dict)  # redactado, para auditoría
    # Tier-2 (É-F2): la tool PROPONE una mutación → el planner encola este
    # texto de confirmación y NO ejecuta hasta la afirmativa del cliente.
    needs_confirmation: bool = False
    confirmation_text: str = ''
    # La tool emite una pregunta/plantilla directa y cierra el turno (sin
    # realimentar al LLM) — p.ej. el 1er paso del reto familiar (PR-17b).
    reply_text: str = ''


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
    """LOCAL (sin HTTP): datos de clínica + horario. Fuente única = la config
    nueva (Organization + OrganizationSchedule, ADR p53); AgentSettings.faq_facts
    /business_hours son fallback legacy. G1: sin dato se responde honesto — jamás
    se inventa."""
    from . import clinic_context
    from .models import AgentSettings
    org = conversation.organization
    settings_obj = AgentSettings.objects.filter(organization=org).first()

    # Base legacy (faq_facts) → la config nueva la PISA campo a campo.
    facts = dict((settings_obj.faq_facts or {}) if settings_obj else {})
    facts.update(clinic_context.clinic_facts(org))

    # Horario: OrganizationSchedule primero; si no hay, business_hours legacy.
    horario = clinic_context.humanize_schedule(org)
    if not horario and settings_obj and settings_obj.business_hours:
        horario = _humanize_hours(settings_obj.business_hours)
    if horario:
        facts['horario'] = horario

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


def _scheduling_vets(organization, agent_settings):
    """Veterinarios candidatos para las citas del agente (Q14).

    Decisión de producto (PO, 2026-07-25): a la clínica **le da igual quién**
    atienda. Entonces el sistema usa a quien esté LIBRE, no siempre al primero
    por id: con tres veterinarios la capacidad disponible es la de los tres, no
    la del primero (que además terminaba con toda la agenda del bot encima).

    Si la clínica SÍ fija `default_veterinarian`, se respeta esa elección y solo
    se ofertan sus huecos. Lista vacía = la clínica no tiene veterinarios
    activos → `no_vet` (no hay nada que inventar).
    """
    from apps.users.models import User
    if agent_settings and agent_settings.default_veterinarian_id:
        vet = agent_settings.default_veterinarian
        if vet and vet.is_active:
            return [vet]
    return list(
        User.objects.filter(
            organization=organization, role='VET', is_active=True,
        ).order_by('pk')
    )


def _day_occupancy(org, executor, day, *, tool_name, triggered_by=None,
                   preferred=''):
    """`{vet_pk: {'HH:MM', …}}` del día, en UNA sola llamada a la API.

    Antes se consultaba la agenda de UN veterinario; ahora se traen las citas
    del día y se agrupan. Con la misma llamada se responde la pregunta que de
    verdad importa: *¿queda algún veterinario libre a esta hora?*
    Devuelve None si la API falla.
    """
    date_str = day.isoformat()
    status_code, data = executor.call(
        'GET', '/api/appointments/', tool_name=tool_name,
        params={'date': date_str},
        args_redacted={'date': date_str, 'preferred': preferred},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'occupied': len(d) if isinstance(d, list) else 0},
    )
    if status_code >= 400:
        return None
    rows = data if isinstance(data, list) else data.get('results', [])
    occupancy = {}
    for row in rows:
        if row.get('status') not in ('scheduled', 'confirmed', 'in_progress'):
            continue
        vet_pk = row.get('veterinarian')
        hhmm = (row.get('start_time') or '')[:5]
        if vet_pk is None or not hhmm:
            continue
        occupancy.setdefault(vet_pk, set()).add(hhmm)
    return occupancy


def _any_vet_free(vets, occupancy, hhmm):
    return any(hhmm not in occupancy.get(vet.pk, ()) for vet in vets)


def pick_free_vet(org, executor, date_str, hhmm, vets, *, triggered_by=None,
                  tool_name='create_appointment'):
    """Primer veterinario libre a esa hora, o None si no queda ninguno.

    Si la consulta de agenda falla se devuelve el primer candidato en vez de
    bloquear el agendado: el dominio revalida el solape bajo su propia
    validación y, si está ocupado, responde 400 → el agente re-oferta.
    """
    from datetime import datetime
    try:
        day = datetime.strptime(str(date_str)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    occupancy = _day_occupancy(org, executor, day, tool_name=tool_name,
                               triggered_by=triggered_by)
    if occupancy is None:
        return vets[0] if vets else None
    for vet in vets:
        if hhmm not in occupancy.get(vet.pk, ()):
            return vet
    return None


def _free_slots_for_day(org, executor, day, vets, ranges, *, preferred='',
                        triggered_by=None, tool_name='find_available_slots'):
    """[hhmm…] libres ese día = business_hours (`ranges`) ∩ ocupación real.

    Un hueco se ofrece si **algún** veterinario candidato lo tiene libre (a la
    clínica le da igual quién atienda). None si la API falla. El caller resuelve
    `vets` y `ranges` para mapear sus propios errores. Compartido por la tool de
    slots y la retención al cancelar (UX-11)."""
    from datetime import datetime, timedelta

    occupancy = _day_occupancy(org, executor, day, tool_name=tool_name,
                               triggered_by=triggered_by, preferred=preferred)
    if occupancy is None:
        return None
    # Reloj de la ORGANIZACIÓN, no del proceso (settings.TIME_ZONE='UTC').
    # Con la zona del servidor, a las 10:00 en México se descartaban como
    # "pasados" todos los huecos anteriores a las 16:00 y a la 13:00 no quedaba
    # ninguno: el agente decía "no tengo horarios" con la agenda vacía.
    today = org_today_local(org)
    now_hhmm = org_now_local(org).strftime('%H:%M') if day == today else '00:00'
    slots = []
    for start, end in [(r[0], r[1]) for r in ranges if len(r) == 2]:
        cursor = datetime.strptime(start, '%H:%M')
        limit = datetime.strptime(end, '%H:%M')
        while cursor + timedelta(minutes=SLOT_MINUTES) <= limit:
            hhmm = cursor.strftime('%H:%M')
            if (
                hhmm > now_hhmm
                and _time_bucket_ok(hhmm, preferred)
                and _any_vet_free(vets, occupancy, hhmm)
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

    from . import clinic_context
    from .models import AgentSettings
    org = conversation.organization
    agent_settings = AgentSettings.objects.filter(organization=org).first()
    business_hours = (agent_settings.business_hours or {}) if agent_settings else {}
    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return None, []
    day = org_today_local(org) + timedelta(days=1)
    for _ in range(max_days):
        ranges = clinic_context.weekday_ranges(
            org, day.weekday(), agent_settings=agent_settings,
            legacy_ranges=_weekday_ranges(business_hours, day.weekday()))
        if ranges:
            slots = _free_slots_for_day(
                org, executor, day, vets, ranges,
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

    from . import clinic_context
    from .models import AgentSettings

    date_str = (args.get('date') or '').strip()
    if not date_str:
        return ToolOutcome(ok=False, client_error='need_date')
    try:
        day = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
    except ValueError:
        return ToolOutcome(ok=False, client_error='bad_date')

    org = conversation.organization
    # Día local de la org: con el reloj UTC del proceso, después de las 18:00
    # en México "hoy" ya era ayer y se rechazaba la fecha del día en curso.
    today = org_today_local(org)
    if day < today:
        return ToolOutcome(ok=False, client_error='past_date')

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    business_hours = (agent_settings.business_hours or {}) if agent_settings else {}
    ranges = clinic_context.weekday_ranges(
        org, day.weekday(), agent_settings=agent_settings,
        legacy_ranges=_weekday_ranges(business_hours, day.weekday()))
    if not ranges:
        return ToolOutcome(ok=True, data=[], summary={'slots': 0, 'closed': True})

    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')

    preferred = args.get('preferred_time', '')
    slots = _free_slots_for_day(
        org, executor, day, vets, ranges,
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

_SLOT_TAKEN_LEMMAS = ('ya existe una cita', 'ese horario', 'no disponible')
_PAST_LEMMAS = ('en el pasado',)


def _domain_messages(data):
    """Mensajes legibles de un error DRF ({code, errors:{campo:[msgs]}})."""
    if not isinstance(data, dict):
        return []
    messages = []
    errors = data.get('errors')
    if isinstance(errors, dict):
        for value in errors.values():
            if isinstance(value, (list, tuple)):
                messages.extend(str(v) for v in value)
            else:
                messages.append(str(value))
    elif isinstance(errors, (list, tuple)):
        messages.extend(str(v) for v in errors)
    for key in ('message', 'detail', 'error'):
        value = data.get(key)
        if isinstance(value, str):
            messages.append(value)
    return messages


def map_domain_400(data):
    """Traduce un 400 del dominio a (client_error, detalle legible).

    Antes CUALQUIER 400 se reportaba como `slot_taken` → el agente decía "se
    acaba de ocupar ese horario" ante un motivo vacío, una especie inválida o
    un veterinario mal configurado. Mentía al cliente y escondía errores de
    configuración justo durante el piloto.
    """
    messages = _domain_messages(data)
    blob = _norm(' | '.join(messages))
    if any(lemma in blob for lemma in _SLOT_TAKEN_LEMMAS):
        return 'slot_taken', ''
    if any(lemma in blob for lemma in _PAST_LEMMAS):
        return 'past_date', ''
    return 'invalid_data', (messages[0][:160] if messages else '')


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


def _goal_error(state):
    """Código conversacional a partir del estado del objetivo (W2)."""
    rejected = state.get('rejected') or {}
    for why in rejected.values():
        if why == 'pasado':
            return 'past_date'
        if why == 'fuera de horizonte':
            return 'out_of_horizon'
        if why == 'handle desconocido':
            return 'unknown_handle'
    if rejected:
        return 'invalid_slot'
    if state.get('low_confidence'):
        return 'confirm_slot'
    return 'need_data'


def _goal_gate(conversation, tool_name, args):
    """Abre/retoma el objetivo, ingiere lo que el modelo propuso y decide si
    ya se puede ejecutar (W2).

    Devuelve `(goal, outcome)`: si `outcome` no es None, faltan datos (o hay
    algo por confirmar) y el turno se resuelve preguntando — el objetivo queda
    persistido con lo que sí se pudo validar. Antes esta información se
    calculaba y se tiraba: cada turno empezaba de cero.
    """
    from . import goals
    goal = goals.open_goal(conversation, goals.TOOL_GOALS[tool_name])
    state = goals.capture(goal, args, conversation)
    if state['missing'] or state['low_confidence'] or state['rejected']:
        goals.mark_asked(goal, state['missing'])
        return goal, ToolOutcome(
            ok=False,
            client_error=_goal_error(state),
            data={
                'ya_tengo': goals.values(goal),
                'me_falta': state['missing'],
                'por_confirmar': state['low_confidence'],
                'rechazado': state['rejected'],
            },
        )
    return goal, None


def create_appointment(conversation, executor, args, triggered_by=None):
    from . import confirmations
    from .models import AgentSettings
    org = conversation.organization

    goal, pending_outcome = _goal_gate(conversation, 'create_appointment', args)
    if pending_outcome is not None:
        return pending_outcome
    from . import goals
    slots = goals.values(goal)

    pet_pid = resolve_handle(conversation, slots['pet_handle'])
    if pet_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    date_str = slots['date']
    time_str = slots['time']
    reason = slots['reason']
    # El validador de slot comprueba el DÍA; aquí se comprueba el instante
    # completo (una hora de hoy que ya pasó).
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
    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')
    # Quien esté libre a esa hora: da igual quién atienda (decisión del PO).
    vet = pick_free_vet(org, executor, date_str, time_str, vets,
                        triggered_by=triggered_by)
    if vet is None:
        return ToolOutcome(ok=False, client_error='slot_taken')

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
        client_error, detail = map_domain_400(data)
        return ToolOutcome(ok=False, client_error=client_error, detail=detail)
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
    from .models import ContactIdentity
    org = conversation.organization
    # Acceso restringido (PO): un número vinculado como familiar puede
    # consultar/agendar, pero NO cancelar lo que hizo el titular.
    if conversation.contact.linked_via == ContactIdentity.LINKED_FAMILY:
        return ToolOutcome(ok=False, client_error='family_restricted')
    goal, pending_outcome = _goal_gate(conversation, 'cancel_appointment', args)
    if pending_outcome is not None:
        return pending_outcome
    from . import goals
    appt_pid = resolve_handle(
        conversation, goals.values(goal)['appointment_handle'])
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
    from .models import ContactIdentity
    org = conversation.organization
    if conversation.contact.linked_via == ContactIdentity.LINKED_FAMILY:
        return ToolOutcome(ok=False, client_error='family_restricted')
    goal, pending_outcome = _goal_gate(
        conversation, 'reschedule_appointment', args)
    if pending_outcome is not None:
        return pending_outcome
    from . import goals
    slots = goals.values(goal)
    appt_pid = resolve_handle(conversation, slots['appointment_handle'])
    if appt_pid is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')
    new_date = slots['new_date']
    new_time = slots['new_time']
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
    status_code, data = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/', tool_name='reschedule_appointment',
        json={'date': args['date'], 'start_time': args['start_time'],
              'end_time': args['end_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
    )
    if status_code == 400:
        client_error, detail = map_domain_400(data)
        return ToolOutcome(ok=False, client_error=client_error, detail=detail)
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')
    return ToolOutcome(ok=True, summary={'rescheduled': True}, data={
        'cuando': format_local_wallclock(args['date'], args['start_time']),
    })


_SPECIES_MAP = {
    'perro': 'canino', 'perros': 'canino', 'perrito': 'canino',
    'perrita': 'canino', 'perra': 'canino', 'cachorro': 'canino',
    'canino': 'canino', 'can': 'canino',
    'gato': 'felino', 'gata': 'felino', 'gatito': 'felino',
    'gatita': 'felino', 'minino': 'felino', 'felino': 'felino',
    'caballo': 'equino', 'yegua': 'equino', 'potro': 'equino', 'equino': 'equino',
    'ave': 'ave', 'pajaro': 'ave', 'perico': 'ave', 'loro': 'ave',
    'canario': 'ave', 'gallina': 'ave', 'pollo': 'ave',
    'reptil': 'reptil', 'tortuga': 'reptil', 'iguana': 'reptil',
    'serpiente': 'reptil', 'lagarto': 'reptil',
    'conejo': 'exótico', 'hamster': 'exótico', 'huron': 'exótico',
    'cuyo': 'exótico', 'cobayo': 'exótico', 'exotico': 'exótico',
    'exótico': 'exótico', 'otro': 'otro',
}


def _normalize_species(raw):
    """Mapea lo que dice el cliente (a menudo una RAZA como 'maltés', y a veces
    con typos) a la lista cerrada del dominio. Desconocido → '' (la especie es
    opcional; el backend rechaza valores fuera de SPECIES_CHOICES → evita un 400
    al registrar). Un typo NUNCA rebota: peor caso, especie vacía (pendiente)."""
    from .identity import _levenshtein_le_1
    s = _norm(raw or '')
    if not s:
        return ''
    if s in _SPECIES_MAP:
        return _SPECIES_MAP[s]
    tokens = s.split()
    # frase ("una perrita maltés") → palabra conocida exacta
    for token in tokens:
        if token in _SPECIES_MAP:
            return _SPECIES_MAP[token]
    # tolerancia a typos (distancia ≤1) en palabras ≥4 letras ("prro"→perro)
    for token in tokens:
        if len(token) >= 4:
            for key, value in _SPECIES_MAP.items():
                if len(key) >= 4 and _levenshtein_le_1(token, key):
                    return value
    return ''  # desconocido/raza → sin especie (pendiente), jamás error


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

    goal, pending_outcome = _goal_gate(
        conversation, 'register_new_client_and_pet', args)
    if pending_outcome is not None:
        return pending_outcome
    from . import goals
    slots = goals.values(goal)
    owner_name = slots['owner_name']
    pet_name = slots['pet_name']
    species = slots.get('pet_species') or ''
    date_str = slots['date']
    time_str = slots['time']
    reason = slots['reason']

    phone = _wa_id_to_local10(contact.external_id)
    if phone is None:
        return ToolOutcome(ok=False, client_error='bad_phone')
    err = _future_or_error(org, date_str, time_str)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')
    vet = pick_free_vet(org, executor, date_str, time_str, vets,
                        triggered_by=triggered_by,
                        tool_name='register_new_client_and_pet')
    if vet is None:
        return ToolOutcome(ok=False, client_error='slot_taken')

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
        client_error, detail = map_domain_400(data)
        return ToolOutcome(ok=False, client_error=client_error, detail=detail)
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


def link_family_member(conversation, executor, args, triggered_by=None):
    """Arranca el reto TRIPLE de vinculación familiar (UX-04, PR-17b). NO
    vincula nada: valida candidatos por nombre del titular y pide el 1er factor
    (mascota). El resto del reto lo conduce el Policy Engine, sin LLM."""
    from . import identity
    contact = conversation.contact
    # E-05: un número que YA es de un cliente no se vincula a otro titular.
    if contact.owner_id is not None:
        return ToolOutcome(ok=False, client_error='already_a_client')
    titular = (args.get('titular_name') or '').strip()
    if not titular:
        return ToolOutcome(ok=False, client_error='need_data')

    candidates = identity.find_link_candidates(conversation.organization, titular)
    # Se siembra el reto AUNQUE no haya candidatos → comportamiento uniforme,
    # sin oráculo de existencia (G4): fallará al final como cualquier dato malo.
    conversation.flow['family_challenge'] = {
        'stage': 'pet',
        'candidate_ids': [o.pk for o in candidates],
        'titular': titular,
        'fails': 0,
    }
    conversation.save(update_fields=['flow'])
    executor.record_local(
        tool_name='link_family_member',
        args_redacted={'titular_provided': True},
        policy_decision='auto', triggered_by_message=triggered_by,
        summary={'candidates': len(candidates)})
    question = ("Para proteger los datos del titular necesito validar 3 cosas. "
               "Primero: ¿cómo se llama una de sus mascotas? 🐾")
    return ToolOutcome(ok=True, reply_text=question,
                       summary={'family_challenge': 'started'})


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
    'link_family_member': {
        'handler': link_family_member,
        'tier': '1',
        'min_verification': 'unknown',
        'description': (
            'Inicia la validación para vincular a un FAMILIAR/autorizado de un '
            'cliente existente (p.ej. "soy la esposa de Juan", "hablo por la '
            'mascota de mi mamá"). Pásale el nombre del titular. Inicia un reto '
            'de seguridad de 3 datos; NO vincula nada por sí solo.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'titular_name': {
                'type': 'string',
                'description': 'Nombre del cliente titular que dijo el contacto'}},
            'required': ['titular_name'],
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


_GOAL_TOOL_HINT = (
    " Puedes llamarla con datos PARCIALES: el sistema lleva la cuenta de lo "
    "que ya tiene y te dice qué falta. Acompaña cada dato con "
    "<campo>_confidence (0 a 1) cuando no estés seguro: si es baja, el "
    "sistema te pedirá confirmarlo con el cliente en vez de darlo por bueno."
)


def _with_confidence(parameters):
    """Añade `<slot>_confidence` a cada campo y vacía `required` (W2).

    Vaciar `required` es deliberado: la herramienta debe poder llamarse con
    datos incompletos. Con campos obligatorios el modelo solo tenía dos
    salidas — no llamar (y re-derivar todo el turno siguiente) o **inventar**
    lo que faltaba. Ahora el objetivo persiste lo válido y pide el resto.
    """
    props = dict(parameters.get('properties') or {})
    for slot in list(props):
        if slot.endswith('_confidence'):
            continue
        props[slot + '_confidence'] = {
            'type': 'number',
            'description': 'Qué tan seguro estás de este dato (0 a 1).',
        }
    return {**parameters, 'properties': props, 'required': []}


def as_openai_tools():
    """Specs en el formato de tool calling OpenAI-compatible (llm.py)."""
    from . import goals
    tools_payload = []
    for name, spec in TOOL_SPECS.items():
        description = spec['description']
        parameters = spec['parameters']
        if name in goals.TOOL_GOALS:
            description += _GOAL_TOOL_HINT
            parameters = _with_confidence(parameters)
        tools_payload.append({
            'type': 'function',
            'function': {
                'name': name,
                'description': description,
                'parameters': parameters,
            },
        })
    return tools_payload


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
