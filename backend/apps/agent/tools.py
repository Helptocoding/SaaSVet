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
import re
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

    # AUTORIDAD CERO (ADR p55 §4). Aquí vivían `reply_text`,
    # `needs_confirmation` y `confirmation_text`: con ellos una herramienta
    # podía **escribirle copy al cliente** y **cerrar el turno**, que son
    # decisiones de conversación tomadas en la capa de menos autoridad.
    # Ordenarlas al final de la jerarquía no bastaba — había que quitarles la
    # capacidad, o la jerarquía era decorativa.
    #
    # Ahora una tool PROPONE un compromiso (lo persiste: `stage_pending` para
    # tier-2, `goals.start_identity` para un reto) y devuelve HECHOS. El
    # planner observa que hubo propuesta y redacta.
    #
    # Lo que esto NO cambia: la barrera tier-2 sigue igual — la afirmativa
    # ejecuta los argumentos STAGED, jamás regenerados (TC-SEC-03).


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
    """LOCAL (sin HTTP): datos de clínica + horario. Fuente única = la
    configuración de clínica (Organization + OrganizationSchedule, ADR p53);
    `faq_facts` solo aporta hechos sin campo propio. G1: sin dato se responde
    honesto — jamás se inventa."""
    from . import clinic_context
    from .models import AgentSettings
    org = conversation.organization
    settings_obj = AgentSettings.objects.filter(organization=org).first()

    # `faq_facts` solo aporta hechos sin campo propio (estacionamiento, aviso
    # de privacidad…): el serializer rechaza las claves que duplican la
    # configuración de clínica, que es la fuente única.
    facts = dict((settings_obj.faq_facts or {}) if settings_obj else {})
    facts.update(clinic_context.clinic_facts(org))

    horario = clinic_context.humanize_schedule(org)
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
    """[hhmm…] libres ese día = horario de la clínica (`ranges`) ∩ ocupación real.

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
    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return None, []
    day = org_today_local(org) + timedelta(days=1)
    for _ in range(max_days):
        ranges = clinic_context.weekday_ranges(org, day.weekday())
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
    (GET /appointments/?date=) ∩ horario de la clínica. ≤3 slots.

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
    ranges = clinic_context.weekday_ranges(org, day.weekday())
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

    # El día consultado ENTRA al objetivo en curso (piloto 2026-07-28, conv 12).
    # Hasta aquí el único acceso a los slots eran los argumentos de una tool de
    # ESCRITURA: si el modelo resolvía la fecha, la usaba para consultar
    # disponibilidad y hasta se la decía al cliente ("el martes 4 está libre")
    # pero no la reenviaba al escribir, el sistema seguía reportando
    # `me_falta: [date]` y el agente la volvía a preguntar — cuatro veces.
    # El cliente ya la dio y el agente ya la dijo: no se vuelve a pedir.
    _capture_slot_from_read(conversation, 'date', date_str)
    # `preferred_time` solo captura si es una hora CONCRETA (HH:MM), no un
    # bucket coloquial ("mañana"/"tarde"). Parcial (Fase 0 §0.6, ver ADR de
    # la auditoría): si el modelo nunca manda `preferred_time` — como en la
    # conv 12, donde la hora dicha en prosa nunca llegó a una tool — esto no
    # captura nada; ese cierre completo es de Fase 3 (CR-7).
    if re.match(r'^\d{1,2}:\d{2}$', (preferred or '').strip()):
        _capture_slot_from_read(conversation, 'time', preferred.strip())

    return ToolOutcome(ok=True, data=projection, summary={'slots': len(projection)})


def _capture_slot_from_read(conversation, slot, value):
    """Alimenta un slot FALTANTE del objetivo en curso desde una tool de
    lectura. Solo rellena huecos: nunca pisa un valor ya capturado (el modelo
    consulta días alternativos y eso no debe borrar lo que el cliente eligió).
    La confirmación tier-2 sigue siendo la barrera real antes de escribir."""
    from . import goals
    goal = goals.get_open_goal(conversation)
    if goal is None or slot not in (goal.missing or []):
        return
    goals.capture(goal, {slot: value}, conversation)


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


# --------------------------------------------------------------------------
# INV-A — la precondición de estado, del lado del agente (ADR p57, §3.2)
#
# El dominio compara `expected_state` contra la fila BLOQUEADA, dentro de la
# transacción que escribe. Aquí solo se captura la tupla en el momento de
# PROPONER y se reenvía al confirmar. El re-parafraseo protege la intención del
# cliente; esto protege el recurso.
# --------------------------------------------------------------------------
EXPECTED_STATE_KEYS = ('expected_status', 'expected_date', 'expected_start_time')


def _expected_state_of(appt):
    """Claves staged con la tupla semántica vigente de la cita leída."""
    return {
        'expected_status': appt.get('status'),
        'expected_date': appt.get('date'),
        'expected_start_time': (appt.get('start_time') or '')[:5],
    }


def _expected_state_body(args):
    """`{'expected_state': {...}}` para el body, o `{}` si el staged es viejo.

    Un `pending_action` staged ANTES de este cambio no trae las claves. Se
    envía sin precondición —comportamiento actual— en vez de inventar una
    tupla: fabricar el estado esperado a partir de la lectura de ahora sería
    exactamente el fail-open que INV-A cierra.
    """
    if any(args.get(k) is None for k in EXPECTED_STATE_KEYS):
        return {}
    return {'expected_state': {
        'status': args['expected_status'],
        'date': args['expected_date'],
        'start_time': args['expected_start_time'],
    }}


# Desenlaces de NEGOCIO declarados de las escrituras de agenda/alta (§5.4).
# Se declaran por llamada, no globalmente: fuera de estas tools los mismos
# códigos serían una anomalía y deben seguir alertando.
BUSINESS_OUTCOMES = (
    'appointment_changed', 'owner_exists', 'owner_ambiguous',
    'slot_taken', 'past_date', 'validation_error',
)


def _precondition_outcome(data, *, already_done_when):
    """Traduce un `409 appointment_changed` a desenlace conversacional.

    Dos lecturas posibles del mismo 409, y confundirlas cuesta caro:

    - **`already_done`** — la cita YA está como el cliente la quería. No es un
      conflicto, es éxito idempotente: cancelar algo ya cancelado no debería
      escalar a una persona (§3.2, exigencia 4).
    - **`appointment_changed`** — cambió a otra cosa. Se le cuenta al cliente
      con el estado REAL y se le deja decidir (R3). **Nunca** se reintenta sin
      precondición: eso es la sobrescritura que INV-A prohíbe (§5.3).
    """
    current = (data or {}).get('current') or {}
    if already_done_when(current):
        return ToolOutcome(ok=False, client_error='already_done',
                           data={'current': current})
    return ToolOutcome(ok=False, client_error='appointment_changed',
                       data={'current': current})


def _cancel_already_done(current):
    """Cancelar: ya está hecho si la cita está cancelada."""
    return current.get('status') == 'canceled'


def _reschedule_already_done(current, args):
    """Reprogramar: ya está hecho si la cita vive en el destino y sigue activa."""
    return (
        current.get('status') in ('scheduled', 'confirmed')
        and current.get('date') == args.get('date')
        and (current.get('start_time') or '')[:5] == (args.get('start_time') or '')[:5]
    )


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


def _goal_gate(conversation, tool_name, args, executor=None,
               triggered_by=None):
    """Abre/retoma el objetivo, ingiere lo que el modelo propuso y decide si
    ya se puede ejecutar (W2).

    Devuelve `(goal, outcome)`: si `outcome` no es None, faltan datos (o hay
    algo por confirmar) y el turno se resuelve preguntando — el objetivo queda
    persistido con lo que sí se pudo validar. Antes esta información se
    calculaba y se tiraba: cada turno empezaba de cero.
    """
    from . import goals
    from . import guards
    goal = goals.open_goal(conversation, goals.TOOL_GOALS[tool_name])
    state = goals.capture(goal, args, conversation)
    if state['missing'] or state['low_confidence'] or state['rejected']:
        # C7 · repetir es defecto del SISTEMA, no del cliente (R10).
        #
        # Un dato pedido ya dos veces sin éxito no se vuelve a pedir igual: se
        # cambia de estrategia. Por eso tampoco se incrementa `asked` — el
        # contador cuenta PREGUNTAS, y a partir de aquí el sistema deja de
        # preguntar de la misma forma.
        #
        # Hasta É-F5 Fase 3 esto solo se registraba: `mark_asked` subía sin
        # tope y el modelo volvía a preguntar lo mismo. En el piloto (conv 12)
        # llegó a `asked={'date': 4, 'time': 4}` y el cliente se fue. La
        # auditoría de rigidez ya lo había escrito —«la repetición debe cambiar
        # la CONDUCTA del sistema, no solo aparecer en un bloque de datos»— y
        # nadie lo implementó.
        gastados = sorted(
            slot for slot in state['missing']
            if (goal.asked or {}).get(slot, 0) >= guards.CHANGE_APPROACH_AFTER
        )
        if not gastados:
            goals.mark_asked(goal, state['missing'])
        # Rastro de la llamada PARCIAL. Antes esta salida temprana no generaba
        # `ToolExecution`, así que 4 intentos de escritura del piloto (conv 12)
        # eran invisibles y la telemetría hacía creer que el modelo casi no
        # llamaba herramientas — estorbó el diagnóstico del propio incidente.
        if executor is not None:
            executor.record_local(
                tool_name=tool_name,
                args_redacted={'me_falta': state['missing'],
                               'capturado': state['advanced']},
                triggered_by_message=triggered_by,
                summary={'objetivo': goal.name, 'resultado': 'need_data'},
            )
        return goal, ToolOutcome(
            ok=False,
            # Preguntar dos veces lo mismo cambia el CÓDIGO, no solo el
            # contador: el modelo recibe otra instrucción (ver
            # `_error_fact`), no la misma repetida.
            client_error=('change_approach' if gastados
                          else _goal_error(state)),
            data={
                'ya_tengo': goals.values(goal),
                'me_falta': state['missing'],
                'ya_preguntado_sin_exito': gastados,
                'por_confirmar': state['low_confidence'],
                'rechazado': state['rejected'],
                # Si esta llamada llenó algo, hubo progreso real. El planner lo
                # usa para distinguir "avanzó el objetivo" de "solo lo tocó" —
                # sin esta señal el detector de estancamiento era ciego al
                # bucle que existe para cazar (piloto conv 12: 4 repreguntas
                # del mismo dato con stall_turns=0).
                'capturado': state['advanced'],
            },
        )
    return goal, None


def create_appointment(conversation, executor, args, triggered_by=None):
    from . import confirmations
    from .models import AgentSettings
    org = conversation.organization

    goal, pending_outcome = _goal_gate(conversation, 'create_appointment', args,
                                       executor=executor,
                                       triggered_by=triggered_by)
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
        # `pet_public_id` es para LEER (el chequeo de release consulta la
        # agenda por identificador público, ADR p18); el PK sigue siendo el
        # del body del POST. Se guarda al PROPONER, no al liberar: al liberar
        # ya no sería "lo que el cliente vio" (§6.1).
        'pet_public_id': pet_pid,
        'date': date_str, 'start_time': time_str,
        'end_time': _appt_end_time(time_str), 'reason': reason,
        'notes': f"Agendada por asistente virtual · conv {conversation.public_id}",
        'idempotency_key': uuid.uuid4().hex,
    }
    confirmations.stage_pending(conversation, tool='create_appointment',
                               args=staged, paraphrase=paraphrase)
    # Propone y devuelve HECHOS: el pending ya quedó staged; que el turno
    # termine esperando el "sí" lo decide el planner (ADR p55 §4).
    return ToolOutcome(ok=True, summary={'proposed': 'create'})


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
    goal, pending_outcome = _goal_gate(conversation, 'cancel_appointment', args,
                                       executor=executor,
                                       triggered_by=triggered_by)
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
        # INV-A: la tupla que el cliente vio parafraseada. Viaja como
        # `expected_state` en el commit para que el dominio compare bajo lock
        # (§6.1). Se captura al PROPONER — calcularla al confirmar sería
        # describir el mundo de después, y la precondición no diría nada.
        **_expected_state_of(appt),
    }
    confirmations.stage_pending(conversation, tool='cancel_appointment',
                               args=staged, paraphrase=paraphrase)
    # Propone y devuelve HECHOS: el pending ya quedó staged; que el turno
    # termine esperando el "sí" lo decide el planner (ADR p55 §4).
    return ToolOutcome(ok=True, summary={'proposed': 'cancel'})


def commit_cancel_appointment(conversation, executor, args, triggered_by=None):
    appt_pid = args['appointment_public_id']
    status_code, data = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/status/',
        tool_name='cancel_appointment',
        json={'status': 'canceled',
              'cancellation_reason': args.get('cancellation_reason', ''),
              **_expected_state_body(args)},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
        business_outcomes=BUSINESS_OUTCOMES,
    )
    if status_code == 409:
        return _precondition_outcome(data, already_done_when=_cancel_already_done)
    if status_code == 400:
        client_error, detail = map_domain_400(data)
        return ToolOutcome(ok=False, client_error=client_error, detail=detail)
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
        conversation, 'reschedule_appointment', args,
        executor=executor, triggered_by=triggered_by)
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
        # INV-A (§0-C): `from_*` deja de ser dato de triage y pasa a ser
        # PRECONDICIÓN — el origen que el cliente vio en el parafraseo.
        **_expected_state_of(appt),
    }
    confirmations.stage_pending(conversation, tool='reschedule_appointment',
                               args=staged, paraphrase=paraphrase)
    # Propone y devuelve HECHOS: el pending ya quedó staged; que el turno
    # termine esperando el "sí" lo decide el planner (ADR p55 §4).
    return ToolOutcome(ok=True, summary={'proposed': 'reschedule'})


def commit_reschedule_appointment(conversation, executor, args, triggered_by=None):
    appt_pid = args['appointment_public_id']
    status_code, data = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/', tool_name='reschedule_appointment',
        json={'date': args['date'], 'start_time': args['start_time'],
              'end_time': args['end_time'], **_expected_state_body(args)},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, domain_object_public_id=appt_pid,
        business_outcomes=BUSINESS_OUTCOMES,
    )
    if status_code == 409:
        return _precondition_outcome(
            data,
            already_done_when=lambda current: _reschedule_already_done(current, args),
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
        conversation, 'register_new_client_and_pet', args,
        executor=executor, triggered_by=triggered_by)
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
    # Propone y devuelve HECHOS: el pending ya quedó staged; que el turno
    # termine esperando el "sí" lo decide el planner (ADR p55 §4).
    return ToolOutcome(ok=True, summary={'proposed': 'register'})


def _contact_if_identity_unchanged(conversation, args):
    """C1–C4 de §4.3: el contacto FRESCO si sigue siendo el que propuso, o `None`.

    Se ejecutan **siempre**, no solo tras un hand-off: INV-B es una regla del
    sistema, y el release solo fue el escenario que la hizo evidente. Entre que
    el cliente vio el parafraseo y contestó «sí» pueden haber pasado minutos —
    o un hand-off entero en el que una persona resolvió la identidad.

    `None` significa que la premisa «cliente nuevo» dejó de ser cierta; NO es un
    error (§4.5): es la buena noticia de que el humano ya lo registró, y la
    conversación sigue por la vía de cliente conocido.

    Devuelve la instancia porque el auto-vínculo posterior **necesita leer
    `auto_rematch_blocked` fresco**: con la instancia cacheada, un reset de
    identidad ocurrido durante el hand-off pasaría inadvertido y el vínculo
    automático lo desharía — exactamente lo que Item 1 cierra.
    """
    from .models import ContactIdentity

    # C1 — re-leer desde la BASE. La instancia cacheada en
    # `conversation.contact` puede ser de hace varios minutos, y justo lo que
    # se comprueba aquí es si cambió mientras tanto.
    contact = ContactIdentity.objects.filter(pk=conversation.contact_id).first()
    if contact is None:
        return None
    # C2/C3 — ya tiene expediente, o el teléfono se volvió ambiguo.
    if contact.owner_id is not None or contact.is_ambiguous:
        return None
    # C4 — el número que propuso es el número que confirma. La comparación usa
    # la MISMA función que armó el staged, así que no puede divergir por
    # formato.
    if _wa_id_to_local10(contact.external_id) != args.get('owner_phone'):
        return None
    return contact


def commit_register_new_client_and_pet(conversation, executor, args, triggered_by=None):
    contact = _contact_if_identity_unchanged(conversation, args)
    if contact is None:
        # Ni siquiera se llama al dominio: no hay nada que escribir y el
        # cliente ya está registrado (§5.2).
        return ToolOutcome(ok=False, client_error='identity_changed')

    body = {k: args[k] for k in (
        'owner_name', 'owner_phone', 'pet_name', 'pet_species',
        'veterinarian', 'date', 'start_time', 'end_time', 'reason', 'notes')}
    # C5 — INV-B en el dominio: el alta del agente SIEMPRE pide expediente
    # nuevo, porque en este flujo la premisa es literalmente «cliente nuevo».
    # Si el teléfono ya tiene expediente, la premisa era falsa y la decisión es
    # de una persona. No se pre-consulta desde aquí a propósito: sería un
    # `icontains` acotado a 20 filas con una ventana TOCTOU hasta el POST.
    body['require_new_owner'] = True
    status_code, data = executor.call(
        'POST', '/api/appointments/create-with-patient/',
        tool_name='register_new_client_and_pet', json=body,
        args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by,
        idempotency_key=args.get('idempotency_key'),
        extract_domain_id=lambda d: d.get('public_id'),
        result_summarizer=lambda d: {'status': d.get('status')},
        business_outcomes=BUSINESS_OUTCOMES)
    if status_code == 409:
        # El teléfono ya tiene expediente (uno: `owner_exists`; varios:
        # `owner_ambiguous`). CERO escrituras — ni Owner, ni Pet, ni cita — y
        # la decisión pasa a una persona con la intención preservada (§5.5).
        code = (data or {}).get('code')
        if code in ('owner_exists', 'owner_ambiguous'):
            return ToolOutcome(ok=False, client_error=code)
        return ToolOutcome(ok=False, client_error='tool_failure')
    if status_code == 400:
        client_error, detail = map_domain_400(data)
        return ToolOutcome(ok=False, client_error=client_error, detail=detail)
    if status_code >= 400:
        return ToolOutcome(ok=False, client_error='tool_failure')

    # Auto-vínculo: el número queda ligado al owner resuelto (probó control
    # del número al escribir + aportó sus datos → confirmed_in_chat).
    #
    # GUARD DE SEGURIDAD (auditoría OCR 2026-08-08, Item 1 del plan): si este
    # contacto fue reseteado (`reset_contact_identity`) y su propio teléfono
    # coincide con un Owner YA EXISTENTE (la razón misma por la que se
    # reseteó), vincularlo aquí desharía el reset por completo, sin ningún
    # reto de identidad — por eso `contact.auto_rematch_blocked` (levantado
    # por el reset) también bloquea esta ruta, no solo
    # `services._rematch_owner`. El contacto queda sin vincular (la
    # cita/mascota igual se crea vía el endpoint compartido; solo se suprime
    # el auto-enlace de LA IDENTIDAD).
    #
    # Desde F2 es la SEGUNDA defensa, y ahora independiente de la primera
    # (§4.4): con `require_new_owner=True` el dominio ya rechaza el alta
    # contra un expediente existente (409), así que `owner_pid` solo puede
    # apuntar a un `Owner` recién creado. Que `link_self_registered` sea
    # seguro deja de ser un supuesto y pasa a ser una garantía verificada
    # dentro de la transacción — pero el guard se queda: una garantía con una
    # sola capa es una garantía que nadie vuelve a comprobar.
    owner_pid = data.get('owner_public_id')
    # `contact` viene de C1 (lectura FRESCA), no de `conversation.contact`: el
    # guard de abajo depende de `auto_rematch_blocked`, y leerlo de una
    # instancia cacheada antes del hand-off sería no leerlo.
    if owner_pid and contact.owner_id is None and not contact.auto_rematch_blocked:
        from apps.patients.models import Owner
        owner = Owner.objects.filter(
            organization=conversation.organization, public_id=owner_pid).first()
        if owner is not None:
            # Elevar el nivel de verificación ocurre ÚNICAMENTE en
            # `identity.py` (ADR p56 inv. 5): es el único módulo que cotea
            # contra la base, y la regla no admite excepciones o deja de ser
            # una frontera.
            from . import identity
            identity.link_self_registered(contact, owner)

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
# `link_family_member` vivía aquí (retirada en É-F5 Fase 2). Sembraba el reto
# triple y devolvía; su propio docstring decía «el resto del reto lo conduce el
# Policy Engine, sin LLM» — ese conductor ya no existe, así que la tool
# proponía algo que nadie terminaba. `identify_client` cubre el mismo caso en
# una sola llamada, y quien pide lo que falta es el modelo.


# ---------------------------------------------------------------------------
# Identidad como HERRAMIENTA, no como máquina de estados (ADR p56 §5, É-F5 F1)
# ---------------------------------------------------------------------------
# Etiquetas de FACTOR en voz de negocio. Se devuelven al modelo en vez de los
# valores: el modelo tiene que poder decir «me falta el nombre del titular»
# sin poder decir «¿eres Ana Cruz?» — G4, el cliente aporta y el sistema
# verifica, jamás al revés.
_FACTOR_LABELS = {
    'owner_name': 'el nombre del titular del registro',
    'pet_name': 'el nombre de una de sus mascotas',
    'phone_digits': 'los últimos 4 dígitos del teléfono registrado',
}


def identify_client(conversation, executor, args, triggered_by=None):
    """Registra y VERIFICA lo que el cliente aportó sobre su identidad.

    El modelo aporta el candidato; **el código dictamina** contra la base
    (ADR p56 §5, invariante 5). `verification_level` lo siguen escribiendo
    solo `identity._promote` y `identity.link_family`; esta herramienta no lo
    toca por su cuenta.

    Tres invariantes de privacidad, y los tres son de seguridad:

    - **Nunca devuelve nombres ni conteos de candidatos.** El modelo no puede
      enumerar lo que no sabe. Por eso `ya_tengo`/`falta` son ETIQUETAS de
      factor, no valores.
    - **Comportamiento uniforme exista o no el registro.** Pedir los 4 dígitos
      no puede significar «encontré a alguien con ese nombre», o la
      herramienta se vuelve un oráculo de existencia. `falta` se calcula de lo
      que el cliente NO aportó, jamás de lo que hay en la base.
    - **El vínculo familiar exige los tres factores contra UN solo owner.** Dos
      homónimos que pasen mascota y dígitos ⇒ no se vincula nada.

    Alcance de Fase 1 (aditivo, la FSM de identidad sigue corriendo): esta
    herramienta **no crea ni destruye compromisos** — solo marca factores
    satisfechos en el que ya exista, así que no puede interferir con el reto
    que `policy.evaluate` esté conduciendo. Lo aportado sin compromiso vivo
    aterriza en `flow['aportado']`, que es scratchpad (filosofía ADR p50) y que
    **ninguna función de decisión lee**.
    """
    from . import goals, identity
    from .models import ConversationGoal

    contact = conversation.contact
    org = conversation.organization
    aportado = {
        key: str(args.get(key) or '').strip()
        for key in ('owner_name', 'pet_name', 'phone_digits')
        if str(args.get(key) or '').strip()
    }

    # 1 · GUARDAR lo que llegó, se lo hayamos pedido o no (C2, modo push).
    flow_store = dict(conversation.flow.get('aportado') or {})
    if aportado:
        flow_store.update(aportado)
        conversation.flow['aportado'] = flow_store
        conversation.save(update_fields=['flow'])
    # Lo REUNIDO en toda la conversación, no solo en esta llamada. El cliente
    # aporta a su ritmo y en el orden que quiere; exigir que los factores
    # lleguen juntos sería volver al modo pull con otro nombre.
    reunido = flow_store

    commitment = goals.get_identity_commitment(conversation)
    if commitment is not None:
        for key in aportado:
            factor = {'owner_name': 'titular', 'pet_name': 'pet',
                      'phone_digits': 'digits'}.get(key)
            # Los nombres sí se guardan (el embudo los necesita); de los
            # dígitos se guarda SATISFACCIÓN, nunca el secreto.
            if factor == 'digits':
                goals.satisfy(commitment, factor)
            elif factor:
                goals.satisfy(commitment, factor, aportado[key])

    # 2 · VERIFICAR contra la base. Deterministo, y es quien dictamina.
    verified = False
    if contact.owner_id is not None:
        # Número ya asociado a un titular: basta con un factor correcto.
        if reunido.get('pet_name'):
            verified = identity.try_verify_by_pet_answer(
                contact, reunido['pet_name'])
        if not verified and reunido.get('owner_name'):
            verified = identity.try_verify_by_owner_name(
                contact, reunido['owner_name'])
    elif len(reunido) == 3:
        # Número desconocido actuando por un titular: los TRES factores contra
        # un mismo owner, o no se vincula nada (reto triple, UX-04).
        #
        # Se verifica contra lo REUNIDO en la conversación, no contra lo que
        # llegó en ESTA llamada. Es la corrección del defecto que encontró el
        # eval multi-turno (É-F5): la tool acumulaba en `flow['aportado']` y
        # luego exigía los tres juntos en un solo `args`, así que un familiar
        # legítimo que daba nombre, mascota y dígitos en tres turnos —que es
        # como se comporta un modelo real— NUNCA quedaba vinculado.
        #
        # La suite no lo vio porque su guion pasa los tres a la vez: el test
        # pasaba porque yo escribí la llamada, no porque el flujo funcionara.
        survivors = [
            owner for owner in identity.find_link_candidates(
                org, reunido['owner_name'])
            if identity.owner_has_pet(owner, reunido['pet_name'])
            and identity.owner_digits_match(owner, reunido['phone_digits'])
        ]
        if len(survivors) == 1:
            identity.link_family(contact, survivors[0])
            verified = True

    # Verificado con un reto en curso: el reto existía para esto, así que se
    # cierra y la tarea suspendida vuelve al frente. No se deja colgando.
    if verified and commitment is not None:
        goals.finish_identity(conversation, commitment,
                              ConversationGoal.STATUS_COMPLETED, 'identified')

    # 3 · DEVOLVER HECHOS. Sin nombres, sin conteos, sin oráculo.
    if contact.owner_id is not None and not verified:
        pendientes = ['pet_name', 'owner_name']
    else:
        pendientes = ['owner_name', 'pet_name', 'phone_digits']
    falta = [_FACTOR_LABELS[key] for key in pendientes if key not in reunido]

    executor.record_local(
        tool_name='identify_client',
        args_redacted={'aporto': sorted(aportado)},   # claves, jamás valores
        summary={'verificado': verified},
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(ok=True, summary={'verificado': verified}, data={
        'verificado': verified,
        'ya_tengo': [_FACTOR_LABELS[key] for key in sorted(reunido)],
        'falta': [] if verified else falta,
    })


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
    'identify_client': {
        'handler': identify_client,
        'tier': '1',
        # `unknown` a propósito: es la herramienta que EXISTE para los
        # contactos sin verificar. Exigir verificación para poder verificarse
        # sería circular.
        'min_verification': 'unknown',
        'description': (
            'Registra y verifica lo que el cliente te haya dicho sobre quién '
            'es. Llámala EN CUANTO te diga cualquiera de estos datos, aunque '
            'sea uno solo y aunque no se lo hayas pedido: su nombre, el '
            'nombre de su mascota, o los últimos 4 dígitos del teléfono con '
            'el que está registrado. Te responde si ya quedó identificado y '
            'qué falta. NO te devuelve datos del expediente: tú nunca le dices '
            'un nombre al cliente para que lo confirme, es él quien los aporta.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'owner_name': {
                    'type': 'string',
                    'description': 'Nombre del titular, tal como lo dijo'},
                'pet_name': {
                    'type': 'string',
                    'description': 'Nombre de una mascota, tal como lo dijo'},
                'phone_digits': {
                    'type': 'string',
                    'description': 'Últimos 4 dígitos del teléfono registrado'},
            },
            # Vacío a propósito (mismo criterio que las tools de objetivo,
            # ADR p54): tiene que poder llamarse con UN solo dato. Exigir el
            # juego completo obligaría al modelo a esperar, y esperar es
            # justamente lo que hace que el dato se pierda.
            'required': [],
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
