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

from .executor import format_local_datetime
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
