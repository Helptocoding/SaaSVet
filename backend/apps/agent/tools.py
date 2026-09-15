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
- Precio y stock solo pueden proyectarse para productos con existencia positiva (G7).
"""
import re
import unicodedata
from dataclasses import dataclass, field

from django.utils import timezone

from apps.channels.models import Message
from apps.core.datetime_utils import org_now_local, org_today_local
from apps.organizations.utils import get_org_setting

from . import endpoint_contracts as contracts
from . import identity, identity_evidence, intake
from .capabilities import EFFECTS, READ_PUBLIC, READ_PERSONAL, WRITE_BUSINESS, CONTROL
from .executor import format_local_datetime, format_local_wallclock
from .models import ContactIdentity, Conversation, HumanHandoff

MAX_ITEMS = 5
MAX_PETS = 10

_MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
           'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')

# Los SEIS estados, no solo los que el filtro viejo dejaba pasar. Que faltaran
# `done`/`canceled`/`no_show` era el mismo defecto por otra vía: el mapa cubría
# exactamente lo que la tool había decidido de antemano que el cliente podía
# preguntar, así que una cita perdida ni siquiera tenía nombre que enseñarle al
# modelo.
_APPT_STATE_LABEL = {
    'scheduled': 'programada',
    'confirmed': 'confirmada',
    'in_progress': 'en consulta',
    'done': 'atendida',
    'canceled': 'cancelada',
    'no_show': 'no asistió',
}

_VACCINE_STATE_LABEL = {
    'current': 'al día',
    'overdue': 'refuerzo vencido',
    'no_scheduled': 'sin refuerzo programado',
}


@dataclass(init=False)
class ToolOutcome:
    """C3: READ/EFFECT/ERROR, in memory. `ok` is derived compatibility.

    Legacy `ok=` adapts preparation/control handlers only; it does not
    establish validated evidence. New consumers require kind and scope.
    """
    kind: str
    data: object = field(repr=False)
    client_error: str
    detail: str = field(repr=False)
    summary: dict
    scope: dict = field(repr=False)
    completeness: str
    observed_at: object
    has_more: bool | None
    cursor: str | None
    error_kind: str | None
    origin: str | None
    retryable: bool | None
    validated: bool
    effects: tuple = field(repr=False)
    partial_effects: tuple = field(repr=False)
    operation_key: str | None = field(repr=False)

    def __init__(self, ok=None, data=None, client_error='', detail='', summary=None,
                 *, kind=None, scope=None, completeness='unknown', observed_at=None,
                 has_more=None, cursor=None, error_kind=None, origin=None,
                 retryable=None, validated=False, effects=(), partial_effects=(), operation_key=None):
        self.kind = kind or ('READ' if ok else 'ERROR')
        if self.kind not in ('READ', 'EFFECT', 'ERROR'):
            raise ValueError('Invalid ToolOutcome kind')
        if completeness not in ('complete', 'truncated', 'unknown'):
            raise ValueError('Invalid completeness')
        if error_kind is None and self.kind == 'ERROR':
            error_kind = ('forbidden' if client_error in (
                'verification_required', 'autonomous_writes_paused',
                'family_restricted', 'operation_authorization_required',
                'intake_required', 'intake_path_conflict') else 'validation_error')
        if error_kind not in (None, 'forbidden', 'not_found', 'validation_error',
                              'conflict', 'transport_error', 'malformed_response',
                              'provider_error', 'uncertain'):
            raise ValueError('Invalid error kind')
        self.data, self.client_error, self.detail = data, client_error, detail
        self.summary, self.scope = summary or {}, scope or {}
        self.completeness, self.observed_at = completeness, observed_at
        self.has_more, self.cursor = has_more, cursor
        self.error_kind, self.origin, self.retryable = error_kind, origin, retryable
        self.validated = validated
        self.effects, self.partial_effects = tuple(effects), tuple(partial_effects)
        self.operation_key = operation_key

    @property
    def ok(self):
        return self.kind == 'READ' or (
            self.kind == 'EFFECT' and self.validated and bool(self.effects))

    @property
    def empty(self):
        return (self.kind == 'READ' and self.validated
                and self.completeness == 'complete'
                and isinstance(self.data, (list, tuple)) and not self.data)

    def project(self, data, *, total=None, summary=None):
        completeness = self.completeness
        if total is not None and len(data) < total:
            completeness = 'truncated'
        return ToolOutcome(
            kind=self.kind, data=data, scope=self.scope,
            completeness=completeness, observed_at=self.observed_at,
            has_more=self.has_more, cursor=self.cursor, validated=self.validated,
            summary=summary, error_kind=self.error_kind,
        )

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


REPLY_TOOL_NAME = 'respond_to_client'
REPLY_PURPOSES = ('answer', 'ask_for_data')

# Una operación cerrada revoca la capacidad que la produjo. Abrir otra no es
# una consecuencia del recibo ni de que el modelo aún recuerde los slots: es
# una decisión tipada, atribuible al nuevo mensaje entrante que la solicita.
#
# Esto no clasifica frases. El modelo sigue resolviendo semánticamente qué
# pidió la persona; el servidor únicamente le exige declarar esa decisión antes
# de volver a exponer herramientas de agenda.
BEGIN_OPERATION_TOOL = 'begin_operation'
OPERATION_KINDS = {
    'new_appointment': 'schedule_appointment',
    'first_visit': 'register_and_schedule',
    'new_pet_with_appointment': 'add_pet_and_schedule',
    'new_pet_only': 'add_pet_only',
    'cancel_appointment': 'cancel_appointment',
    'reschedule_appointment': 'reschedule_appointment',
}
SCHEDULING_PREPARATION_TOOLS = frozenset({
    'find_available_slots',
    'check_appointment_slot',
})


def _norm(text):
    text = unicodedata.normalize('NFD', (text or '').lower())
    return ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')


_PRODUCT_CATEGORY_ALIASES = {
    'food': frozenset({
        'alimento', 'alimentos', 'comida', 'comidas', 'croqueta', 'croquetas',
        'pienso', 'piensos',
    }),
    'medication': frozenset({
        'medicamento', 'medicamentos', 'medicina', 'medicinas', 'farmaco',
        'farmacos',
    }),
    'accessory': frozenset({
        'accesorio', 'accesorios', 'collar', 'collares', 'correa', 'correas',
        'juguete', 'juguetes',
    }),
}
_PRODUCT_QUERY_STOP_WORDS = frozenset({
    'a', 'al', 'con', 'de', 'el', 'en', 'la', 'las', 'los', 'para', 'por', 'un',
    'una', 'unos', 'unas', 'y',
})


def _normalized_tokens(value):
    return tuple(token for token in re.findall(r'\w+', _norm(value))
                 if token not in _PRODUCT_QUERY_STOP_WORDS)


def _product_category_from_query(query):
    normalized = _norm(query).strip()
    for category, aliases in _PRODUCT_CATEGORY_ALIASES.items():
        if normalized in aliases:
            return category
    return None


def _token_matches_catalog(token, text):
    """Match tolerante a plural para una palabra significativa del catálogo."""
    if token in text:
        return True
    if token.endswith('es') and token[:-2] in text:
        return True
    return token.endswith('s') and token[:-1] in text


def _product_text_score(product, query):
    """Puntúa nombre > descripción > fabricante; `None` significa sin match."""
    query = _norm(query).strip()
    name = _norm(product.get('name', ''))
    description = _norm(product.get('description', ''))
    manufacturer = _norm(product.get('manufacturer', ''))
    tokens = _normalized_tokens(query)
    if not query or not tokens:
        return None
    haystack = ' '.join((name, description, manufacturer))
    if not all(_token_matches_catalog(token, haystack) for token in tokens):
        return None
    if name == query:
        return 400
    if query in name:
        return 300
    if query in manufacturer:
        return 200
    if all(_token_matches_catalog(token, name) for token in tokens):
        return 150
    return 100


def _available_product_details(product, currency=None):
    """Datos comerciales permitidos exclusivamente cuando hay existencia."""
    details = {'stock': product.get('stock_quantity', 0)}
    presentations = product.get('presentations') or []
    exhausted = []
    for presentation in presentations:
        exhausted.append({
            'presentacion': presentation.get('name') or product.get('name', ''),
            'precio': presentation.get('sale_price'),
            'amount': contracts.decimal_field(presentation.get('sale_price'), nullable=True),
            'currency': currency,
            'stock': presentation.get('stock', 0),
        })
    if len(exhausted) == 1:
        details.update(exhausted[0])
    elif exhausted:
        details['presentaciones'] = exhausted
    return details


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
    if minimum in ('confirmed_in_chat', 'staff_verified'):
        if not identity.is_verification_current(contact):
            return False
    return order.index(contact.verification_level) >= order.index(minimum)


def _last_operation_receipt(conversation):
    """Último recibo que el cliente realmente pudo recibir, si existe.

    El recibo es un hecho de dominio conversacional: al existir, la operación
    que lo originó ya terminó y ninguna herramienta puede asumir que la
    siguiente interacción continúa esa intención.
    """
    return (Message.objects.filter(
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
    ).exclude(
        status__in=(Message.STATUS_DISCARDED, Message.STATUS_FAILED),
    ).order_by('-created_at', '-id').first())


def _has_completed_operation(conversation):
    return _last_operation_receipt(conversation) is not None


def _goal_for_tool(tool_name):
    from . import goals
    return goals.TOOL_GOALS.get(tool_name)


def _active_goal_authorizes(conversation, tool_name):
    """Si la capacidad del objetivo vigente cubre esta herramienta."""
    from . import goals

    goal = goals.get_open_goal(conversation)
    if goal is None:
        return False
    if tool_name in SCHEDULING_PREPARATION_TOOLS:
        return goal.name in {
            goals.SCHEDULE, goals.REGISTER, goals.ADD_PET,
            goals.CANCEL, goals.RESCHEDULE,
        }
    expected = _goal_for_tool(tool_name)
    return bool(expected and goal.name == expected)


def _is_operation_scoped_tool(tool_name):
    return bool(_goal_for_tool(tool_name)) or tool_name in SCHEDULING_PREPARATION_TOOLS


def operation_tool_allowed(conversation, tool_name):
    """Capacidad de agenda después de una operación completada.

    Antes del primer recibo se conserva el flujo de alta inicial existente. A
    partir de un commit, en cambio, el catálogo deja de inferir continuidad:
    una tool de agenda requiere el objetivo explícitamente autorizado que está
    en el frente. Esta misma función se invoca al construir el catálogo y al
    ejecutar, para que un output viejo o una llamada directa no salte la regla.
    """
    if EFFECTS.get(tool_name) in (READ_PUBLIC, READ_PERSONAL) or tool_name == 'request_human':
        return True
    if not _is_operation_scoped_tool(tool_name):
        return True
    if not _has_completed_operation(conversation):
        return True
    return _active_goal_authorizes(conversation, tool_name)


def can_begin_operation(conversation):
    """La puerta semántica solo aparece después de un recibo real."""
    return _has_completed_operation(conversation)


def _operation_kind_allowed_for_intake(conversation, goal_name):
    path = intake.current_path(conversation)
    if path == intake.PATH_NEW:
        return goal_name == OPERATION_KINDS['first_visit']
    if path == intake.PATH_EXISTING:
        return goal_name != OPERATION_KINDS['first_visit']
    return False


def begin_operation(conversation, executor, args, triggered_by=None):
    """Autoriza un nuevo objetivo DESPUÉS de un recibo previo.

    No agenda, no consulta disponibilidad y no redacta una confirmación. Su
    único efecto es abrir el compromiso tipado y conservar el mensaje entrante
    que lo causó. Las herramientas operativas aparecen recién después de esta
    autorización.
    """
    from . import goals

    goal_name = OPERATION_KINDS.get((args or {}).get('operation'))
    receipt = _last_operation_receipt(conversation)
    valid_origin = (
        triggered_by is not None
        and triggered_by.pk is not None
        and triggered_by.conversation_id == conversation.pk
        and triggered_by.direction == Message.DIRECTION_IN
        and receipt is not None
        and triggered_by.created_at > receipt.created_at
    )
    if (goal_name is None or not valid_origin
            or not _operation_kind_allowed_for_intake(conversation, goal_name)):
        executor.record_local(
            tool_name=BEGIN_OPERATION_TOOL,
            args_redacted={'operation': (args or {}).get('operation', '')},
            policy_decision='denied',
            summary={'reason': 'operation_authorization_required'},
            triggered_by_message=triggered_by,
        )
        return ToolOutcome(ok=False,
                           client_error='operation_authorization_required')

    goal = goals.open_goal(
        conversation, goal_name, authorization_message=triggered_by)
    executor.record_local(
        tool_name=BEGIN_OPERATION_TOOL,
        args_redacted={'operation': (args or {}).get('operation', '')},
        summary={'goal': goal.name, 'authorization_message_id': triggered_by.pk},
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(ok=True, data={'operation_started': True},
                       summary={'goal': goal.name})


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _scope(conversation, **filters):
    return {'organization_id': conversation.organization_id,
            'conversation_id': conversation.pk,
            'contact_id': conversation.contact_id, **filters}


def _response_error(response, scope):
    return ToolOutcome(
        kind='ERROR', error_kind=response.error_kind, scope=scope,
        client_error='tool_failure', origin=('transport' if response.transport_error else 'endpoint'),
        # Retrying reads after a transport failure is safe; B2 never retries
        # ambiguous writes or infers their final state.
        retryable=(False if response.uncertain else None),
        summary={'contract_version': 1, 'http_status': response.status_code,
                 'error_kind': response.error_kind, 'timeout': response.timeout},
    )


def _malformed(scope):
    return ToolOutcome(kind='ERROR', error_kind='malformed_response',
                       client_error='tool_failure', origin='endpoint', scope=scope)


def _read_endpoint(conversation, executor, path, *, schema, scope=None, **kwargs):
    scope = scope or _scope(conversation)
    if (executor.conversation.pk != conversation.pk
            or executor.agent_user.organization_id != conversation.organization_id):
        return ToolOutcome(kind='ERROR', error_kind='forbidden',
                           client_error='verification_required', scope=scope)
    response = executor.call('GET', path, **kwargs)
    if response.error_kind:
        return _response_error(response, scope)
    try:
        # These endpoint list implementations have no pagination by default.
        rows, completeness, has_more, cursor = contracts.collection(
            response.data, schema, scope, flat_complete=True)
    except contracts.InvalidResponse:
        outcome = _malformed(scope)
    else:
        outcome = ToolOutcome(kind='READ', data=rows, validated=True, scope=scope,
                              completeness=completeness, has_more=has_more, cursor=cursor)
    executor.record_outcome(kwargs['tool_name'], outcome)
    return outcome


def _effect_response(conversation, response, *, action, schema='appointment',
                     scope=None, expected=None, result='success'):
    """Only a validated entity with matching requested state proves an effect."""
    scope = scope or _scope(conversation)
    if response.error_kind:
        outcome = _response_error(response, scope)
        if response.status_code == 409:
            code = response.data.get('code') if isinstance(response.data, dict) else None
            outcome.client_error = code if code in BUSINESS_OUTCOMES else 'tool_failure'
        elif response.status_code == 400:
            # Known domain codes only. Never relay the server's personal body.
            code = response.data.get('code') if isinstance(response.data, dict) else None
            outcome.client_error = code if code in ('slot_taken', 'past_appointment') else 'invalid_data'
        return outcome
    try:
        contracts.validate_row(response.data, schema, scope)
        for key, value in (expected or {}).items():
            actual = response.data.get(key)
            if key in ('start_time', 'end_time'):
                contracts.require(contracts.iso_time(actual) == contracts.iso_time(value))
            else:
                contracts.require(actual == value)
    except contracts.InvalidResponse:
        return _malformed(scope)
    row = response.data
    effect = {'entity': schema, 'reference': row['public_id'], 'action': action,
              'state': row.get('status', 'registered'), 'result': result}
    data = ({'cuando': format_local_wallclock(row['date'], row['start_time'])}
            if schema == 'appointment' else {'nombre': row['name']})
    return ToolOutcome(kind='EFFECT', validated=True, scope=scope,
                       data=data, effects=(effect,), summary={'contract_version': 1, 'effect': result})


def _appointment_effect(conversation, executor, response, *, action, args,
                        triggered_by=None):
    scope = _scope(conversation)
    if conversation.contact.owner_id:
        scope['owner'] = str(conversation.contact.owner.public_id)
    if args.get('appointment_public_id'):
        scope['appointment'] = args['appointment_public_id']
    expected = {}
    if action in ('cancel_appointment', 'confirm_appointment'):
        expected['status'] = 'canceled' if action == 'cancel_appointment' else 'confirmed'
    else:
        expected.update({k: args[k] for k in ('date', 'start_time', 'end_time', 'pet', 'veterinarian') if k in args})
        if args.get('pet_name'):
            expected['pet_name'] = args['pet_name']
        if action in ('create_appointment', 'register_new_client_and_pet', 'register_pet_and_schedule'):
            expected['status'] = 'scheduled'
    # A conflict itself is never success. A fresh scoped GET may demonstrate
    # that the exact target already holds, without attributing it to this turn.
    if response.status_code == 409 and scope.get('appointment'):
        current = executor.call('GET', f"/api/appointments/{scope['appointment']}/",
                                tool_name=action, triggered_by_message=triggered_by)
        checked = _effect_response(conversation, current, action=action,
                                   scope=scope, expected=expected, result='already_done')
        if checked.kind == 'EFFECT':
            checked.data['current'] = {k: current.data[k] for k in ('status', 'date', 'start_time')}
            return checked
        conflict = _effect_response(conversation, response, action=action, scope=scope)
        # Existing state-change UX consumes a minimal current state, only if
        # the fresh response itself passed the appointment schema and scope.
        try:
            contracts.validate_row(current.data, 'appointment', scope)
            if not current.error_kind:
                conflict.data = {'current': {k: current.data[k] for k in ('status', 'date', 'start_time')}}
        except (contracts.InvalidResponse, KeyError, TypeError):
            pass
        return conflict
    outcome = _effect_response(conversation, response, action=action, scope=scope, expected=expected)
    if outcome.kind == 'EFFECT':
        outcome.operation_key = args.get('idempotency_key')
    # p52's 200 replay is already_done only with the same server idempotency
    # key and a fully compatible returned entity, never from status alone.
    if (outcome.kind == 'EFFECT' and response.status_code == 200
            and action in ('create_appointment', 'register_new_client_and_pet')
            and args.get('idempotency_key')):
        outcome.effects[0]['result'] = 'already_done'
    return outcome


def _personal_pet_reference(conversation, handle):
    from apps.patients.models import Pet
    if not _verification_ok(conversation, 'confirmed_in_chat'):
        return None
    public_id = resolve_handle(conversation, handle)
    if contracts.public_id(public_id) and Pet.objects.filter(
            organization_id=conversation.organization_id,
            owner_id=conversation.contact.owner_id, public_id=public_id).exists():
        return public_id
    return None


def list_my_pets(conversation, executor, args, triggered_by=None):
    if not _verification_ok(conversation, 'confirmed_in_chat'):
        return ToolOutcome(kind='ERROR', client_error='verification_required')
    owner = conversation.contact.owner
    source = _read_endpoint(
        conversation, executor, '/api/pets/', schema='pet',
        scope=_scope(conversation, owner=str(owner.public_id)), tool_name='list_my_pets',
        params={'owner': str(owner.public_id)},
        args_redacted={},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'pets': len(d) if isinstance(d, list) else 0},
    )
    if source.kind == 'ERROR':
        return source
    pets = source.data
    projection = []
    for pet in pets[:MAX_PETS]:
        handle = _add_ref(conversation, 'mascota', pet['public_id'])
        projection.append({
            'handle': handle,
            'nombre': pet.get('name', ''),
            'especie': pet.get('species', '') or 'sin especie',
        })
    _save_refs(conversation)
    return source.project(projection, total=len(pets), summary={'pets': len(projection)})


def get_vaccine_status(conversation, executor, args, triggered_by=None):
    public_id = _personal_pet_reference(conversation, args.get('pet_handle'))
    if public_id is None:
        return ToolOutcome(ok=False, client_error='unknown_handle')

    source = _read_endpoint(
        conversation, executor, '/api/vaccines/', schema='vaccine',
        scope=_scope(conversation, pet=public_id), tool_name='get_vaccine_status',
        params={'pet': public_id},
        args_redacted={'pet_handle': args.get('pet_handle')},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'vaccines': len(d) if isinstance(d, list) else 0},
    )
    if source.kind == 'ERROR':
        return source
    vaccines = source.data
    projection = [{
        'vacuna': v.get('vaccine_name', ''),
        'aplicada': _format_date(v.get('application_date')),
        'proximo_refuerzo': _format_date(v.get('next_due_date')),
        'estado': _VACCINE_STATE_LABEL.get(v.get('status'), v.get('status', '')),
    } for v in vaccines[:MAX_ITEMS * 2]]
    return source.project(projection, total=len(vaccines),
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
        args_redacted={},
        summary={'facts': len([k for k in facts if k != '_sin_dato'])},
        triggered_by_message=triggered_by,
    )
    # FAQ values are staff supplied text, not structured price/effect evidence.
    if not all(isinstance(k, str) and isinstance(v, (str, bool))
               for k, v in facts.items()):
        return _malformed(_scope(conversation))
    return ToolOutcome(kind='READ', data=facts, validated=True,
                       scope=_scope(conversation, topic=topic), completeness='unknown',
                       summary={'facts': len(facts)})


def get_service_catalog(conversation, executor, args, triggered_by=None):
    currency = get_org_setting(conversation.organization, 'currency_code')
    source = _read_endpoint(
        conversation, executor, '/api/billing/services/', schema='service',
        scope=_scope(conversation, currency=currency), tool_name='get_service_catalog',
        args_redacted={},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'services': len(d) if isinstance(d, list) else 0},
    )
    if source.kind == 'ERROR':
        return source
    services = [s for s in source.data if s['is_active']]
    query = _norm(args.get('query', ''))
    if query:
        services = [s for s in services if query in _norm(s.get('name', ''))]

    projection = []
    for service in services[:MAX_ITEMS]:
        # ServiceSerializer expone `base_price` (billing/serializers.py:52).
        price_value = contracts.decimal_field(service['base_price'], nullable=True)
        projection.append({
            'servicio': service.get('name', ''),
            # Precio nulo/0 → None: el planner responde "lo cotiza el
            # equipo", jamás "$0" (spec INT-11).
            'precio': f"${price_value:,.2f}" if price_value and price_value > 0 else None,
            'amount': price_value if price_value and price_value > 0 else None,
            'currency': currency, 'service_id': service['public_id'],
        })
    source.scope['local_filters'] = {'name_contains': query, 'is_active': True}
    return source.project(projection, total=len(services), summary={'matches': len(projection)})


_SPECIALTY_IGNORED_TOKENS = frozenset({
    'consulta', 'consultas', 'general', 'servicio', 'servicios', 'veterinaria',
    'veterinario', 'veterinarios',
})
_SPECIALTY_TOKEN_ALIASES = {
    'cirujano': 'cirugia', 'cirujana': 'cirugia',
    'dermatologo': 'dermatologia', 'dermatologa': 'dermatologia',
    'oftalmologo': 'oftalmologia', 'oftalmologa': 'oftalmologia',
    'cardiologo': 'cardiologia', 'cardiologa': 'cardiologia',
}


def _specialty_tokens(value):
    return frozenset(
        _SPECIALTY_TOKEN_ALIASES.get(token, token)
        for token in _normalized_tokens(value)
        if token not in _SPECIALTY_IGNORED_TOKENS
    )


def get_offered_specialties(conversation, executor, args, triggered_by=None):
    """Especialidades que tienen servicio activo Y personal activo asignable.

    Se consulta el dominio directamente para no publicar nombres de personal,
    correos ni otros datos internos que no necesita el cliente.
    """
    from apps.billing.models import Service
    from apps.users.models import User

    organization = conversation.organization
    services = list(Service.objects.filter(
        organization=organization, is_active=True,
    ).values_list('name', flat=True))
    staff_specialties = list(User.objects.filter(
        organization=organization, is_active=True,
    ).exclude(specialty='').values_list('specialty', flat=True))
    service_keys = {_specialty_tokens(name) for name in services}
    query_tokens = _specialty_tokens(args.get('query', ''))
    offered = []
    for specialty in staff_specialties:
        key = _specialty_tokens(specialty)
        if not key or key not in service_keys:
            continue
        if query_tokens and not query_tokens.issubset(key):
            continue
        offered.append(specialty.strip())

    projection = [{'especialidad': specialty}
                  for specialty in sorted(set(offered), key=_norm)[:MAX_ITEMS]]
    executor.record_local(
        tool_name='get_offered_specialties', args_redacted={},
        summary={'matches': len(projection)}, triggered_by_message=triggered_by,
    )
    return ToolOutcome(kind='READ', data=projection, validated=True,
                       scope=_scope(conversation, local_filters={'query': args.get('query', '')}),
                       completeness=('truncated' if len(set(offered)) > MAX_ITEMS else 'complete'),
                       summary={'matches': len(projection)})


def check_product_availability(conversation, executor, args, triggered_by=None):
    query = args.get('query', '')
    category = _product_category_from_query(query)
    params = {'active': 'true'}
    if category:
        params['category'] = category
    source = _read_endpoint(
        conversation, executor, '/api/inventory/products/', schema='product',
        scope=_scope(conversation, currency=get_org_setting(conversation.organization, 'currency_code'), **params),
        tool_name='check_product_availability',
        params=params,
        args_redacted={},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'products': len(d) if isinstance(d, list) else 0},
    )
    if source.kind == 'ERROR':
        return source
    products = source.data
    products = [p for p in products if p.get('is_active', True)]
    if category:
        matches = [p for p in products if p.get('category') == category]
    else:
        scored = [(_product_text_score(product, query), product)
                  for product in products]
        matches = [product for score, product in sorted(
            (item for item in scored if item[0] is not None),
            key=lambda item: (-item[0], _norm(item[1].get('name', '')), str(item[1].get('public_id', ''))),
        )]

    projection = []
    for product in matches[:MAX_ITEMS]:
        available = _product_available(product)
        entry = {
            'producto': product.get('name', ''),
            'disponible': available,
            'requiere_receta': bool(product.get('requires_prescription')),
        }
        if available:
            entry.update(_available_product_details(product, get_org_setting(conversation.organization, 'currency_code')))
        else:
            entry['agotado'] = True
        projection.append(entry)

    # Memoria de producto (plan de continuidad, F4): fila PROPIA con el producto
    # RESUELTO, no el texto del cliente.
    #
    # Dos motivos, y el segundo pesa más. (1) `executor.call` persiste su fila
    # ANTES de que esto exista, así que la proyección no quedaba en ninguna
    # parte. (2) `args_redacted` guarda la consulta literal
    # (`{'query': <lo que escribió el cliente>}`) pese a que el contrato del
    # modelo la declara «proyecciones SIN PII cruda — los cuerpos viven solo en
    # Message, regla R15». Construir memoria permanente sobre esa violación la
    # cementaría; se registra aparte lo que sí es un hecho: qué producto se
    # resolvió.
    #
    # `tool_name` propio y no `check_product_availability`: dos filas con el
    # mismo nombre contarían DOS ejecuciones por una sola búsqueda y falsearían
    # las métricas por tool.
    for entry in projection:
        executor.record_local(
            tool_name='product_query_resolved',
            args_redacted={},
            summary={'producto': entry['producto'],
                     'disponible': entry['disponible']},
            triggered_by_message=triggered_by,
        )
    source.scope['local_filters'] = {'query': query, 'search_mode': 'category' if category else 'text'}
    return source.project(projection, total=len(matches),
                          summary={'matches': len(projection),
                                   'search_mode': 'category' if category else 'text'})


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


def get_appointments(conversation, executor, args, triggered_by=None):
    """TODAS las citas del cliente, etiquetadas — el modelo elige cuáles aplican.

    Reemplaza a `list_upcoming_appointments` y `get_past_visits`, que eran el
    mismo código con el filtro invertido y **cada una una pregunta congelada**:
    una asumía que el cliente pregunta por el futuro, la otra que pregunta por
    visitas cerradas. Entre las dos dejaban un hueco del tamaño del caso más
    común de una clínica.

    Lo que pasó en el piloto (conv 21, 2026-08-17): el cliente abrió con «no
    pude acudir a mi cita». Su cita existía —hoy 09:00, `scheduled`— y él la
    estaba viendo en el sistema. La API la devolvía en cada llamada
    (`{"appointments": 1}`, diez veces en `ToolExecution`), y estos dos filtros
    la tiraban:

        list_upcoming_appointments:  if start_dt < now: continue
        get_past_visits:             if status != 'done': continue

    Una cita perdida es pasada Y no `done`: caía por los dos. El modelo recibía
    `0` y decía `0`, honestamente, mientras el cliente insistía «deberías buscar
    bien». Y como los handles de cita solo los emitía la primera, reagendarla
    era imposible por construcción — con «no pude acudir» siendo probablemente
    la razón número uno por la que alguien le escribe a su veterinario.

    De ahí el contrato: **esta tool no decide qué es relevante**. Devuelve cada
    cita con su estado y con `ya_paso` ya resuelto contra el reloj de la
    clínica, y quien eligió qué responder es quien leyó la conversación. El
    único recorte es el volumen (`MAX_ITEMS`), y se hace por CERCANÍA a ahora
    para que sobrevivan a la vez la que se perdió esta mañana y la próxima.
    """
    if not _verification_ok(conversation, 'confirmed_in_chat'):
        return ToolOutcome(kind='ERROR', client_error='verification_required')
    pet_handle = args.get('pet_handle')
    coverage = 'complete'
    if pet_handle:
        public_id = _personal_pet_reference(conversation, pet_handle)
        if public_id is None:
            return ToolOutcome(ok=False, client_error='unknown_handle')
        pet_ids = [public_id]
    else:
        pets_outcome = list_my_pets(conversation, executor, {},
                                    triggered_by=triggered_by)
        if pets_outcome.kind == 'ERROR':
            return pets_outcome
        coverage = pets_outcome.completeness
        pet_ids = [resolve_handle(conversation, p['handle'])
                   for p in pets_outcome.data]

    now = timezone.now()
    found = []
    for pet_id in pet_ids:
        source = _read_endpoint(
            conversation, executor, '/api/appointments/', schema='appointment',
            scope=_scope(conversation, pet=pet_id,
                         owner=str(conversation.contact.owner.public_id)),
            tool_name='get_appointments',
            params={'pet': pet_id},
            args_redacted={'pet_handle': pet_handle or '(todas)'},
            triggered_by_message=triggered_by,
            result_summarizer=lambda d: {
                'appointments': len(d) if isinstance(d, list) else 0},
        )
        if source.kind == 'ERROR':
            return source
        if source.completeness != 'complete':
            coverage = ('truncated' if 'truncated' in (coverage, source.completeness) else 'unknown')
        rows = source.data
        for appointment in rows:
            start_dt = _appointment_start(appointment)
            if start_dt is None:
                # Fecha ilegible: se descarta porque no se puede situar en el
                # tiempo, no porque su estado no nos guste.
                return _malformed(source.scope)
            found.append((start_dt, appointment))

    # El recorte por volumen elige por CERCANÍA (|start - ahora|) y luego se
    # emite en orden cronológico: ordenar y cortar por fecha dejaría fuera lo
    # que el cliente tiene delante en cuanto haya varias citas al otro lado.
    found.sort(key=lambda pair: abs((pair[0] - now).total_seconds()))
    visible = sorted(found[:MAX_ITEMS], key=lambda pair: pair[0])

    projection = []
    for start_dt, appointment in visible:
        # Handle para TODAS, no solo las futuras: es lo que permite cancelar o
        # reagendar la que se perdió.
        handle = _add_ref(conversation, 'cita', appointment['public_id'])
        raw_status = appointment.get('status', '')
        projection.append({
            'handle': handle,
            'mascota': appointment.get('pet_name', ''),
            'cuando': format_local_datetime(start_dt, conversation.organization),
            'estado': _APPT_STATE_LABEL.get(raw_status, raw_status),
            'ya_paso': start_dt < now,
            'motivo': (appointment.get('reason') or '')[:120],
        })
    _save_refs(conversation)
    return ToolOutcome(kind='READ', data=projection, validated=True,
                       scope=_scope(conversation, pets=tuple(pet_ids),
                                    owner=str(conversation.contact.owner.public_id)),
                       completeness=('truncated' if len(found) > MAX_ITEMS else coverage),
                       summary={'citas': len(projection)})


def _appointment_start(appointment):
    """Instante aware de inicio, o `None` si el dato no es interpretable."""
    from datetime import datetime
    from datetime import timezone as dt_timezone
    raw = appointment.get('start_datetime') or (
        f"{appointment.get('date')}T{appointment.get('start_time')}"
    )
    try:
        start_dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return None
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, dt_timezone.utc)
    return start_dt


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
    """READ de intervalos ocupados por veterinario, o ERROR explícito.

    Antes se consultaba la agenda de UN veterinario; ahora se traen las citas
    del día y se agrupan. Con la misma llamada se responde la pregunta que de
    verdad importa: *¿queda algún veterinario libre a esta hora?*
    Sin cobertura completa no se puede demostrar que un horario esté libre.
    """
    date_str = day.isoformat()
    source = _read_endpoint(
        executor.conversation, executor, '/api/appointments/', schema='appointment',
        scope=_scope(executor.conversation, date=date_str), tool_name=tool_name,
        params={'date': date_str},
        args_redacted={'date': date_str, 'preferred': preferred},
        triggered_by_message=triggered_by,
        result_summarizer=lambda d: {'occupied': len(d) if isinstance(d, list) else 0},
    )
    if source.kind == 'ERROR':
        return source
    if source.completeness != 'complete':
        return ToolOutcome(kind='ERROR', error_kind='uncertain',
                           client_error='tool_failure', scope=source.scope, origin='endpoint')
    rows = source.data
    occupancy = {}
    for row in rows:
        if row.get('status') not in ('scheduled', 'confirmed', 'in_progress'):
            continue
        vet_pk = row.get('veterinarian')
        if vet_pk is None:
            return _malformed(source.scope)
        occupancy.setdefault(vet_pk, []).append((row['start_time'], row['end_time']))
    return source.project(occupancy)


def _own_appointment_at(org, executor, day, pet_public_id, hhmm, *,
                        tool_name, triggered_by=None):
    """La cita ACTIVA de ESA misma mascota a esa hora, o `None`.

    Se consulta **solo cuando no queda veterinario libre**, es decir justo
    antes de decir «se ocupó ese horario». Sin esto el agente le dijo a un
    cliente que las 11:00 se acababan de ocupar cuando quien las ocupaba era
    **su propia cita**, creada un minuto antes (conv 18 del piloto): una
    respuesta que además de falsa lo empujaba a agendar dos veces.

    El coste vive en el camino de error, no en el feliz: si hay hueco, esta
    llamada no ocurre.
    """
    date_str = day.isoformat()
    status_code, data = executor.call(
        'GET', '/api/appointments/', tool_name=tool_name,
        params={'date': date_str},
        args_redacted={'date': date_str},
        triggered_by_message=triggered_by,
    )
    if status_code >= 400:
        return None
    rows = data if isinstance(data, list) else (data or {}).get('results', [])
    for row in rows:
        if row.get('status') not in ('scheduled', 'confirmed', 'in_progress'):
            continue
        if str(row.get('pet_public_id') or '') != str(pet_public_id):
            continue
        if (row.get('start_time') or '')[:5] == hhmm:
            return row
    return None


def _slot_taken_or_already_scheduled(org, executor, date_str, hhmm,
                                     pet_public_id, *, tool_name,
                                     triggered_by=None):
    """Desenlace honesto cuando no queda veterinario libre.

    `slot_taken` es verdad solo si el hueco lo ocupa **otro**. Si lo ocupa la
    cita de este mismo paciente, lo que hay que decir es que ya la tiene — no
    inventarle una carrera que no existió.
    """
    from datetime import datetime
    try:
        day = datetime.strptime(str(date_str)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return ToolOutcome(ok=False, client_error='slot_taken')
    own = _own_appointment_at(org, executor, day, pet_public_id, hhmm,
                              tool_name=tool_name, triggered_by=triggered_by)
    if own is None:
        return ToolOutcome(ok=False, client_error='slot_taken')
    return ToolOutcome(ok=False, client_error='already_scheduled', data={
        'cuando': format_local_wallclock(date_str, hhmm),
    })


def _any_vet_free(vets, occupancy, hhmm):
    return any(_vet_free(vet.pk, occupancy, hhmm) for vet in vets)


def _vet_free(vet_pk, occupancy, hhmm):
    start = contracts.iso_time(hhmm)
    end = contracts.iso_time(_appt_end_time(hhmm))
    return not any(start < contracts.iso_time(b) and end > contracts.iso_time(a)
                   for a, b in occupancy.get(vet_pk, ()))


def pick_free_vet(org, executor, date_str, hhmm, vets, *, triggered_by=None,
                  tool_name='create_appointment'):
    """Primer veterinario libre a esa hora, o None si no queda ninguno.

    Si la consulta falla no se elige un candidato por defecto. Las escrituras
    siguen contenidas y las pruebas supervisadas conservan la validación API.
    """
    from datetime import datetime
    try:
        day = datetime.strptime(str(date_str)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None
    occupancy = _day_occupancy(org, executor, day, tool_name=tool_name,
                               triggered_by=triggered_by)
    if occupancy.kind == 'ERROR':
        return None
    for vet in vets:
        if _vet_free(vet.pk, occupancy.data, hhmm):
            return vet
    return None


def _free_slots_for_day(org, executor, day, vets, ranges, *, preferred='',
                        triggered_by=None, tool_name='find_available_slots'):
    """[hhmm…] libres ese día = horario de la clínica (`ranges`) ∩ ocupación real.

    Un hueco se ofrece si **algún** veterinario candidato lo tiene libre (a la
    clínica le da igual quién atienda). ERROR si la API falla. El caller resuelve
    `vets` y `ranges` para mapear sus propios errores. Compartido por la tool de
    slots y la retención al cancelar (UX-11)."""
    from datetime import datetime, timedelta

    occupancy = _day_occupancy(org, executor, day, tool_name=tool_name,
                               triggered_by=triggered_by, preferred=preferred)
    if occupancy.kind == 'ERROR':
        return occupancy
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
                and _any_vet_free(vets, occupancy.data, hhmm)
            ):
                slots.append(hhmm)
                if len(slots) > MAX_ITEMS:
                    break
            cursor += timedelta(minutes=SLOT_MINUTES)
        if len(slots) > MAX_ITEMS:
            break
    return occupancy.project(slots[:MAX_ITEMS], total=len(slots))


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
            if slots.kind == 'READ' and slots.data:
                fecha = format_local_wallclock(
                    day.isoformat(), slots.data[0]).rsplit(',', 1)[0]
                return fecha, [_hhmm_label(h) for h in slots.data[:2]]
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
        return ToolOutcome(kind='READ', data=[], validated=True, completeness='complete',
                           scope=_scope(conversation, date=date_str),
                           summary={'slots': 0, 'closed': True})

    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')

    preferred = args.get('preferred_time', '')
    slots = _free_slots_for_day(
        org, executor, day, vets, ranges,
        preferred=preferred, triggered_by=triggered_by)
    if slots.kind == 'ERROR':
        return slots

    projection = [{
        'fecha': format_local_wallclock(
            date_str, hhmm,
        ).rsplit(',', 1)[0],  # "martes 21 de julio" (la hora va aparte)
        'hora': _hhmm_label(hhmm),
        'iso_date': date_str,
        'iso_time': hhmm,
        'iso_end_time': _appt_end_time(hhmm),
    } for hhmm in slots.data[:3]]

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

    slots.scope['local_filters'] = {'preferred_time': preferred, 'duration_minutes': SLOT_MINUTES}
    return slots.project(projection, total=len(slots.data), summary={'slots': len(projection)})


def _exact_slot_status(org, executor, date_str, time_str, vets, *,
                       tool_name, triggered_by=None):
    """Estado exacto de una hora: no confunde ausencia en sugerencias con ocupación."""
    from datetime import datetime

    from . import clinic_context
    try:
        day = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        hhmm = datetime.strptime(time_str[:5], '%H:%M').strftime('%H:%M')
    except (TypeError, ValueError):
        return 'bad_date', None
    if day < org_today_local(org):
        return 'past_date', None
    if day == org_today_local(org) and hhmm <= org_now_local(org).strftime('%H:%M'):
        return 'past_date', None

    ranges = clinic_context.weekday_ranges(org, day.weekday())
    end_time = _appt_end_time(hhmm)
    if not ranges:
        return 'closed', None
    if not any(len(item) == 2 and item[0] <= hhmm and end_time <= item[1]
               for item in ranges):
        return 'outside_hours', None

    occupancy = _day_occupancy(
        org, executor, day, tool_name=tool_name, triggered_by=triggered_by,
        preferred=hhmm,
    )
    if occupancy.kind == 'ERROR':
        return 'tool_failure', occupancy
    for vet in vets:
        if _vet_free(vet.pk, occupancy.data, hhmm):
            return 'available', vet
    return 'slot_taken', None


def check_appointment_slot(conversation, executor, args, triggered_by=None):
    """Comprueba UNA hora concreta; las alternativas son responsabilidad de T9."""
    from .models import AgentSettings

    date_str = (args.get('date') or '').strip()
    time_str = (args.get('time') or '').strip()
    if not date_str or not time_str:
        return ToolOutcome(ok=False, client_error='need_date')
    org = conversation.organization
    settings = AgentSettings.objects.filter(organization=org).first()
    vets = _scheduling_vets(org, settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')
    state, _vet = _exact_slot_status(
        org, executor, date_str, time_str, vets,
        tool_name='check_appointment_slot', triggered_by=triggered_by,
    )
    if state == 'tool_failure' and isinstance(_vet, ToolOutcome):
        return _vet
    if state in ('bad_date', 'past_date', 'tool_failure'):
        return ToolOutcome(ok=False, client_error=state)
    available = state == 'available'
    return ToolOutcome(
        kind='READ', validated=True, completeness='complete',
        scope=_scope(conversation, date=date_str, time=time_str[:5]),
        data={'date': date_str, 'time': time_str[:5], 'available': available,
              'end_time': _appt_end_time(time_str[:5]),
              'reason': '' if available else state},
        summary={'available': available, 'reason': '' if available else state},
    )


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
    if isinstance(data, dict) and data.get('code') == 'past_appointment':
        return 'past_appointment', ''
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
    envía sin precondición en vez de inventar una tupla: fabricar el estado
    esperado a partir de la lectura de ahora sería exactamente el fail-open
    que INV-A cierra.

    Desde la Fase 3 esa llamada sin precondición ya no pasa: el dominio
    responde `400 precondition_required` y el agente le dice al cliente que
    vuelva a pedirlo. Es el desenlace correcto para una propuesta staged al
    otro lado de un deploy — se perdió la foto de cómo estaba la cita, y sin
    ella nadie está autorizado a escribirla. Afecta solo a las propuestas en
    vuelo durante el despliegue; las nuevas nacen con las claves.
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
    'slot_taken', 'past_date', 'past_appointment', 'validation_error',
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
    # Propuesta y sugerencias consumen el mismo veredicto exacto.
    slot_state, vet = _exact_slot_status(
        org, executor, date_str, time_str, vets,
        tool_name='create_appointment', triggered_by=triggered_by,
    )
    if slot_state == 'slot_taken':
        return _slot_taken_or_already_scheduled(
            org, executor, date_str, time_str, pet_pid,
            tool_name='create_appointment', triggered_by=triggered_by)
    if slot_state != 'available':
        return ToolOutcome(ok=False, client_error=slot_state)

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
    response = executor.call(
        'POST', '/api/appointments/', tool_name='create_appointment',
        json=body, args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, idempotency_key=args.get('idempotency_key'))
    outcome = _appointment_effect(conversation, executor, response,
                                  action='create_appointment', args=args, triggered_by=triggered_by)
    if outcome.kind == 'EFFECT':
        _add_ref(conversation, 'cita', response.data['public_id'])
        _save_refs(conversation)
    return outcome


def confirm_appointment(conversation, executor, args, triggered_by=None):
    """WRITE only. State queries use get_appointments; containment still wins."""
    appt_pid = resolve_handle(conversation, args.get('appointment_handle'))
    if appt_pid is None:
        return ToolOutcome(kind='ERROR', client_error='unknown_handle')
    scope = _scope(conversation, appointment=appt_pid,
                   owner=str(conversation.contact.owner.public_id))
    read = executor.call('GET', f'/api/appointments/{appt_pid}/',
                         tool_name='confirm_appointment', triggered_by_message=triggered_by)
    if read.error_kind:
        return _response_error(read, scope)
    try:
        contracts.validate_row(read.data, 'appointment', scope)
    except contracts.InvalidResponse:
        return _malformed(scope)
    if read.data['status'] == 'confirmed':
        return _effect_response(conversation, read, action='confirm_appointment', scope=scope,
                                expected={'status': 'confirmed'}, result='already_done')
    response = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/status/', tool_name='confirm_appointment',
        json={'status': 'confirmed', **_expected_state_body(_expected_state_of(read.data))},
        policy_tier='1', triggered_by_message=triggered_by, business_outcomes=BUSINESS_OUTCOMES)
    return _appointment_effect(conversation, executor, response, action='confirm_appointment',
                               args={'appointment_public_id': appt_pid}, triggered_by=triggered_by)


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
    appointment_time_error = _future_or_error(
        org, appt.get('date', ''), appt.get('start_time', ''),
    )
    if appointment_time_error == 'past_date':
        return ToolOutcome(ok=False, client_error='past_appointment')
    if appointment_time_error:
        return ToolOutcome(ok=False, client_error='tool_failure')

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
    response = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/status/', tool_name='cancel_appointment',
        json={'status': 'canceled', 'cancellation_reason': args.get('cancellation_reason', ''),
              **_expected_state_body(args)}, policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, business_outcomes=BUSINESS_OUTCOMES)
    return _appointment_effect(conversation, executor, response, action='cancel_appointment',
                               args=args, triggered_by=triggered_by)


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

    from .models import AgentSettings
    agent_settings = AgentSettings.objects.filter(organization=org).first()
    vets = _scheduling_vets(org, agent_settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')
    slot_state, vet = _exact_slot_status(
        org, executor, new_date, new_time, vets,
        tool_name='reschedule_appointment', triggered_by=triggered_by,
    )
    if slot_state != 'available':
        return ToolOutcome(ok=False, client_error=slot_state)


    paraphrase = confirmations.CONFIRM_RESCHEDULE.format(
        pet=appt.get('pet_name', ''),
        vieja=_appt_when_label(appt, org),
        nueva=format_local_wallclock(new_date, new_time),
    )
    staged = {
        'appointment_public_id': appt_pid, 'date': new_date,
        'start_time': new_time, 'end_time': _appt_end_time(new_time),
        # La clínica puede atender con cualquier veterinario libre; se fija el
        # elegido al proponer para que la confirmación no cambie de recurso.
        'veterinarian': vet.pk,
        # Si alguien cancela esta cita antes del commit, estos datos permiten
        # convertir la intención en un ALTA nueva, nunca resucitar la vieja.
        'replacement_pet': appt.get('pet'),
        'replacement_pet_public_id': str(appt.get('pet_public_id') or ''),
        'replacement_reason': appt.get('reason') or 'consulta',
        'replacement_from_appointment': appt_pid,
        'replacement_pet_name': appt.get('pet_name', ''),
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
    body = {'date': args['date'], 'start_time': args['start_time'],
            'end_time': args['end_time'], **_expected_state_body(args)}
    if args.get('veterinarian') is not None:
        body['veterinarian'] = args['veterinarian']
    response = executor.call(
        'PATCH', f'/api/appointments/{appt_pid}/', tool_name='reschedule_appointment',
        json=body, policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, business_outcomes=BUSINESS_OUTCOMES)
    return _appointment_effect(conversation, executor, response, action='reschedule_appointment',
                               args=args, triggered_by=triggered_by)


def stage_replacement_from_canceled_reschedule(conversation, executor, pending,
                                               current, *, triggered_by=None):
    """Convierte un reagendado invalidado por cancelación en alta nueva.

    La cita original jamás se toca de nuevo. Solo se prepara una creación con
    los datos que el cliente ya aprobó, y la siguiente afirmativa confirma esa
    nueva operación real.
    """
    from . import confirmations
    from .models import AgentSettings

    if (current or {}).get('status') != 'canceled':
        return ToolOutcome(ok=False, client_error='not_reschedulable')
    source = (pending or {}).get('args') or {}
    pet_pk = source.get('replacement_pet')
    pet_public_id = source.get('replacement_pet_public_id')
    if not pet_pk or not pet_public_id:
        return ToolOutcome(ok=False, client_error='invalid_data')
    date_str = source.get('date', '')
    time_str = source.get('start_time', '')
    err = _future_or_error(conversation.organization, date_str, time_str)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    settings = AgentSettings.objects.filter(
        organization=conversation.organization).first()
    vets = _scheduling_vets(conversation.organization, settings)
    if not vets:
        return ToolOutcome(ok=False, client_error='no_vet')
    state, vet = _exact_slot_status(
        conversation.organization, executor, date_str, time_str, vets,
        tool_name='prepare_replacement_appointment',
        triggered_by=triggered_by,
    )
    if state != 'available':
        return ToolOutcome(ok=False, client_error=state)

    import uuid
    reason = source.get('replacement_reason') or 'consulta'
    staged = {
        'pet': pet_pk,
        'pet_public_id': pet_public_id,
        'veterinarian': vet.pk,
        'date': date_str,
        'start_time': time_str,
        'end_time': _appt_end_time(time_str),
        'reason': reason,
        'notes': (
            'Reemplazo de cita cancelada por asistente virtual · conv '
            f'{conversation.public_id} · origen {source.get("replacement_from_appointment", "")}'
        )[:250],
        'idempotency_key': uuid.uuid4().hex,
    }
    paraphrase = confirmations.CONFIRM_REPLACEMENT_CREATE.format(
        pet=source.get('replacement_pet_name') or 'tu mascota',
        fecha=format_local_wallclock(date_str, time_str),
        reason=reason,
    )
    confirmations.stage_pending(
        conversation, tool='create_appointment', args=staged,
        paraphrase=paraphrase,
    )
    return ToolOutcome(ok=True, summary={'proposed': 'replacement_create'})


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
    birth_date = slots.get('pet_birth_date') or ''
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
    if birth_date:
        staged['pet_birth_date'] = birth_date
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
    if args.get('pet_birth_date'):
        body['pet_birth_date'] = args['pet_birth_date']
    # C5 — INV-B en el dominio: el alta del agente SIEMPRE pide expediente
    # nuevo, porque en este flujo la premisa es literalmente «cliente nuevo».
    # Si el teléfono ya tiene expediente, la premisa era falsa y la decisión es
    # de una persona. No se pre-consulta desde aquí a propósito: sería un
    # `icontains` acotado a 20 filas con una ventana TOCTOU hasta el POST.
    body['require_new_owner'] = True
    response = executor.call(
        'POST', '/api/appointments/create-with-patient/',
        tool_name='register_new_client_and_pet', json=body,
        args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by,
        idempotency_key=args.get('idempotency_key'),
        extract_domain_id=lambda d: d.get('public_id'),
        result_summarizer=lambda d: {'status': d.get('status')},
        business_outcomes=BUSINESS_OUTCOMES)
    outcome = _appointment_effect(conversation, executor, response,
                                  action='register_new_client_and_pet', args=args,
                                  triggered_by=triggered_by)
    if outcome.kind != 'EFFECT':
        return outcome
    data = response.data

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
    return outcome



# ---------------------------------------------------------------------------
# Mascota nueva de un cliente YA identificado
#
# El hueco que cerró esto: `register_new_client_and_pet` se niega en cuanto el
# contacto tiene expediente (`already_client`) y `create_appointment` exige un
# `pet_handle` que solo sale de `list_my_pets`. Un cliente conocido que llega
# con OTRA mascota no tenía ningún camino — el modelo prometía registrarla, no
# encontraba qué llamar, repetía preguntas y el guardián de estancamiento
# acababa mandando el caso a una persona (conv 17 del piloto).
#
# INV-B, que es lo que gobierna este flujo: el expediente sale de
# `contact.owner_id` —el vínculo que YA existe y superó verificación—, jamás de
# resolver el teléfono en el momento. Que un número coincida no autoriza a
# escribir en el historial de nadie.
# ---------------------------------------------------------------------------

def _writable_owner(conversation):
    """`(owner, None)` si el agente puede escribir en ese expediente.

    Dos negativas, por motivos distintos:

    - `not_a_client`: no hay vínculo. El camino es
      `register_new_client_and_pet`, no éste.
    - `family_restricted`: el vínculo es familiar (secundario). Un familiar
      puede consultar y mover citas, pero **no abrir expedientes nuevos** en la
      ficha del titular. Mismo criterio que `reschedule_appointment`.
    """
    from .models import ContactIdentity
    contact = conversation.contact
    if contact.owner_id is None:
        return None, 'not_a_client'
    if contact.linked_via == ContactIdentity.LINKED_FAMILY:
        return None, 'family_restricted'
    return contact.owner, None


def _existing_pet_named(conversation, executor, owner, pet_name,
                        tool_name, triggered_by=None):
    """Handle de una mascota activa del cliente con ese nombre, o `None`.

    Evita el duplicado del cliente que repite («Koler», «koler»). Devuelve el
    handle para que el modelo pueda ofrecer agendarle a ESA en vez de crear
    una segunda: negarse sin alternativa sería otro callejón.
    """
    from apps.patients.services import normalize_owner_name
    status_code, data = executor.call(
        'GET', '/api/pets/', tool_name=tool_name,
        params={'owner': str(owner.public_id)}, args_redacted={},
        triggered_by_message=triggered_by,
    )
    if status_code >= 400:
        return None
    pets = data if isinstance(data, list) else (data or {}).get('results', [])
    target = normalize_owner_name(pet_name)
    for pet in pets:
        if normalize_owner_name(pet.get('name', '')) == target:
            return _add_ref(conversation, 'mascota', pet['public_id'])
    return None


def _stage_add_pet(conversation, executor, args, *, with_appointment,
                   triggered_by=None):
    """Tronco común de las dos altas: valida, arma el staged y propone.

    Las dos herramientas son el MISMO acto con distinto alcance; separarlas en
    el registro es lo que hace explícito «se quedó sin cita», pero duplicar
    aquí la validación sería pedir que diverjan.
    """
    from . import confirmations, goals
    from .models import AgentSettings
    org = conversation.organization

    owner, err = _writable_owner(conversation)
    if err:
        return ToolOutcome(ok=False, client_error=err)

    tool_name = ('register_pet_and_schedule' if with_appointment
                 else 'register_pet_only')
    goal, pending_outcome = _goal_gate(conversation, tool_name, args,
                                       executor=executor,
                                       triggered_by=triggered_by)
    if pending_outcome is not None:
        return pending_outcome
    slots = goals.values(goal)
    pet_name = slots['pet_name']
    species = slots.get('pet_species') or ''
    birth_date = slots.get('pet_birth_date') or ''

    duplicate = _existing_pet_named(conversation, executor, owner, pet_name,
                                    tool_name, triggered_by=triggered_by)
    if duplicate is not None:
        _save_refs(conversation)
        # No es un fallo: el cliente ya la tiene registrada. Se devuelve el
        # handle para que el modelo siga por la vía normal de agendar.
        return ToolOutcome(ok=False, client_error='pet_exists',
                           data={'mascota_handle': duplicate,
                                 'nombre': pet_name})

    staged = {
        'owner_public_id': str(owner.public_id),
        'pet_name': pet_name, 'pet_species': species,
    }
    if birth_date:
        staged['pet_birth_date'] = birth_date
    if with_appointment:
        date_str, time_str, reason = slots['date'], slots['time'], slots['reason']
        err = _future_or_error(org, date_str, time_str)
        if err:
            return ToolOutcome(ok=False, client_error=err)
        agent_settings = AgentSettings.objects.filter(organization=org).first()
        vets = _scheduling_vets(org, agent_settings)
        if not vets:
            return ToolOutcome(ok=False, client_error='no_vet')
        vet = pick_free_vet(org, executor, date_str, time_str, vets,
                            triggered_by=triggered_by, tool_name=tool_name)
        if vet is None:
            # Aquí `slot_taken` SÍ es verdad: la mascota es nueva (el caso del
            # nombre repetido ya salió arriba por `pet_exists`), así que el
            # hueco no puede ser suyo. La comprobación de dueño vive en
            # `create_appointment`, que es donde se reagenda sobre una mascota
            # que ya existe.
            return ToolOutcome(ok=False, client_error='slot_taken')
        staged.update({
            'veterinarian': vet.pk, 'date': date_str, 'start_time': time_str,
            'end_time': _appt_end_time(time_str), 'reason': reason,
            'notes': f"Agendada por asistente virtual · conv {conversation.public_id}",
        })
        paraphrase = confirmations.CONFIRM_ADD_PET.format(
            pet=pet_name, especie=species or 'sin especificar',
            fecha=format_local_wallclock(date_str, time_str), reason=reason)
    else:
        paraphrase = confirmations.CONFIRM_ADD_PET_ONLY.format(
            pet=pet_name, especie=species or 'sin especificar')

    import uuid
    staged['idempotency_key'] = uuid.uuid4().hex
    confirmations.stage_pending(conversation, tool=tool_name, args=staged,
                                paraphrase=paraphrase)
    return ToolOutcome(ok=True, summary={'proposed': tool_name})


def register_pet_and_schedule(conversation, executor, args, triggered_by=None):
    """Mascota nueva de un cliente identificado + su primera cita (tier-2)."""
    return _stage_add_pet(conversation, executor, args,
                          with_appointment=True, triggered_by=triggered_by)


def register_pet_only(conversation, executor, args, triggered_by=None):
    """Alta sin cita. NO se ofrece: solo para el cliente que ya la rechazó."""
    return _stage_add_pet(conversation, executor, args,
                          with_appointment=False, triggered_by=triggered_by)


def _commit_add_pet(conversation, executor, args, *, with_appointment,
                    triggered_by=None):
    """Existing supervised compound path: preserve each proven effect."""
    tool_name = 'register_pet_and_schedule' if with_appointment else 'register_pet_only'
    pet_body = {'owner_public_id': args['owner_public_id'], 'name': args['pet_name']}
    for key, dest in (('pet_species', 'species'), ('pet_birth_date', 'birth_date')):
        if args.get(key):
            pet_body[dest] = args[key]
    response = executor.call(
        'POST', '/api/pets/', tool_name=tool_name, json=pet_body,
        args_redacted={}, policy_tier='2', policy_decision='confirmed',
        triggered_by_message=triggered_by, idempotency_key=args.get('idempotency_key'),
        business_outcomes=BUSINESS_OUTCOMES)
    pet_effect = _effect_response(
        conversation, response, action=tool_name, schema='pet',
        scope=_scope(conversation, owner=args['owner_public_id']),
        expected={'name': args['pet_name']})
    if pet_effect.kind != 'EFFECT':
        return pet_effect
    pet = response.data
    pet_handle = _add_ref(conversation, 'mascota', pet['public_id'])
    _save_refs(conversation)
    pet_effect.data['mascota_handle'] = pet_handle
    if not with_appointment:
        return pet_effect
    appt_body = {k: args[k] for k in ('veterinarian', 'date', 'start_time', 'end_time', 'reason', 'notes')}
    appt_body['pet'] = pet['id']
    response = executor.call(
        'POST', '/api/appointments/', tool_name=tool_name, json=appt_body,
        args_redacted={'date': args['date'], 'time': args['start_time']},
        policy_tier='2', policy_decision='confirmed', triggered_by_message=triggered_by,
        business_outcomes=BUSINESS_OUTCOMES)
    outcome = _appointment_effect(conversation, executor, response,
                                  action=tool_name, args=appt_body, triggered_by=triggered_by)
    if outcome.kind != 'EFFECT':
        outcome.partial_effects = pet_effect.effects
        outcome.validated = True
        outcome.client_error = 'pet_saved_appointment_failed'
        outcome.data = pet_effect.data
        return outcome
    _add_ref(conversation, 'cita', response.data['public_id'])
    _save_refs(conversation)
    outcome.effects = pet_effect.effects + outcome.effects
    outcome.data['mascota_handle'] = pet_handle
    return outcome



def commit_register_pet_and_schedule(conversation, executor, args,
                                     triggered_by=None):
    return _commit_add_pet(conversation, executor, args,
                           with_appointment=True, triggered_by=triggered_by)


def commit_register_pet_only(conversation, executor, args, triggered_by=None):
    return _commit_add_pet(conversation, executor, args,
                           with_appointment=False, triggered_by=triggered_by)


# Ejecutores del pending_action confirmado (el planner los invoca).
COMMIT_HANDLERS = {
    'create_appointment': commit_create_appointment,
    'cancel_appointment': commit_cancel_appointment,
    'reschedule_appointment': commit_reschedule_appointment,
    'register_new_client_and_pet': commit_register_new_client_and_pet,
    'register_pet_and_schedule': commit_register_pet_and_schedule,
    'register_pet_only': commit_register_pet_only,
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
    aterriza en `flow['aportado']`, el scratchpad de la ruta de identidad. La
    frontera de intake garantiza que solo se llena después de clasificar al
    contacto como cliente existente.
    """
    from . import goals, identity
    from .models import ConversationGoal

    # La herramienta no decide si una persona es nueva o existente. Esa
    # clasificación es semántica y se persiste antes de exponerla; sin ella,
    # acumular un nombre de mascota aquí convierte una primera visita en un
    # falso reto de identidad.
    if intake.current_path(conversation) != intake.PATH_EXISTING:
        return ToolOutcome(ok=False, client_error='intake_path_conflict')

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
    echo_rejected = None
    if identity.is_verification_current(contact):
        # Ya está verificado —típicamente por la ruta pasiva, en el turno en que
        # nombró a su mascota— y la evidencia se sella al capturarla, no se
        # re-presenta. Sin esta rama la tool contestaría `verificado: False` a
        # alguien ya identificado y el modelo volvería a pedirle el nombre: el
        # bucle que este trabajo existe para cerrar.
        verified = True
    elif contact.owner_id is not None:
        # Número ya asociado a un titular: el ÚNICO factor de autoservicio es el
        # nombre de una mascota (plan de continuidad, D4b). `owner_name` se
        # retiró —el sistema lo conoce y se lo enseña al staff en la bandeja, así
        # que no prueba nada sobre quien escribe— y los 4 dígitos son circulares
        # para quien escribe desde su propio número.
        #
        # Y la verificación pasa por el SERVICIO ÚNICO. El modelo propone la
        # LECTURA —«el cliente acaba de decirme que su mascota es Koler»— y el
        # servidor la comprueba contra el texto real: procedencia (qué mensaje
        # DEL CLIENTE lo contiene), anti-eco y TTL (ADR p59). Puede equivocarse
        # interpretando; no puede inventar el aporte.
        #
        # Ésta es la ÚNICA vía desde p59. La pasiva de `policy` se retiró: sin la
        # gramática cerrada, un escaneo sin propuesta del modelo promovía con
        # cualquier coincidencia de token.
        resolution = identity_evidence.resolve_pet_evidence(
            conversation, reunido.get('pet_name', ''))
        if isinstance(resolution, identity_evidence.EchoRejected):
            echo_rejected = resolution
        elif isinstance(resolution, identity_evidence.SealedPetEvidence):
            result = identity_evidence.verify_pet_evidence(
                conversation, resolution)
            conversation.contact = result.contact_identity
            conversation.flow = result.conversation_flow
            contact = result.contact_identity
            verified = True
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

    # El reto lo cierra `verify_pet_evidence` DENTRO de su commit (D32); en la
    # vía familiar, que no pasa por él, se cierra aquí.
    if verified and commitment is not None and contact.owner_id is not None:
        commitment.refresh_from_db()
        if commitment.status in ConversationGoal.FOREGROUND_STATUSES:
            goals.finish_identity(conversation, commitment,
                                  ConversationGoal.STATUS_COMPLETED,
                                  'identified')

    if echo_rejected is not None:
        # D33 · las DOS rutas terminan igual: sin promoción, sin factor, sin
        # slot, hand-off de identidad y ejecución detenida. Repetir el dato no
        # sirve —seguiría siendo eco hasta que caduque la ventana— así que no se
        # le pide otra vez.
        from . import policy
        identity_evidence.log_echo_rejected(conversation, echo_rejected)
        policy.escalate_to_human(
            conversation, reason_code=HumanHandoff.REASON_IDENTITY,
            detail=identity_evidence.ECHO_HANDOFF_DETAIL,
        )
        executor.record_local(
            tool_name='identify_client',
            args_redacted={'aporto': sorted(aportado), 'eco': True},
            summary={'verificado': False, 'eco': True},
            triggered_by_message=triggered_by,
        )
        return ToolOutcome(ok=False, client_error='identity_echo')

    # 3 · DEVOLVER HECHOS. Sin nombres, sin conteos, sin oráculo.
    if contact.owner_id is not None and not verified:
        # Solo `pet_name`: pedirle el nombre del titular ya no sirve de nada
        # (D4b) y pedirle sus propios 4 dígitos es circular.
        pendientes = ['pet_name']
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


# ---------------------------------------------------------------------------
# Memoria estructurada (plan de continuidad, F4)
# ---------------------------------------------------------------------------
# Un hilo continuo no es memoria: la ventana sigue siendo 12 turnos / 40
# mensajes, así que lo que se habló hace tres semanas se pierde igual. Estas
# tools le dan al modelo el equivalente a subir a leer, pero acotado a HECHOS,
# no a texto libre: menos superficie de fuga y ya auditado.
#
# Reglas comunes:
#   · **Solo ejecuciones exitosas.** Una llamada fallida o revertida no es un
#     hecho y no se le cuenta al cliente como si lo fuera.
#   · **Para agenda manda el dominio.** El log dice qué se intentó; `Appointment`
#     dice qué es verdad hoy.
#   · Alcance `(contact, channel_account)`, y `min_verification` de tool personal.

def _successful_executions(conversation, tool_names, limit):
    """Ejecuciones que de verdad salieron bien, del hilo de ESTE contacto.

    `ToolExecution` no tiene campo `success` (hay `http_status`, `error_code` y
    `policy_decision`), así que el predicado se escribe aquí en vez de suponerlo:
    HTTP 2xx/3xx **o** local sin HTTP, y `error_code` vacío. `policy_decision`
    denegada o escalada tampoco cuenta: no llegó a ocurrir nada.
    """
    from django.db.models import Q

    from .models import ToolExecution

    return list(
        ToolExecution.objects
        .for_organization(conversation.organization)
        .filter(
            conversation__contact=conversation.contact_id,
            conversation__channel_account=conversation.channel_account_id,
            tool_name__in=tool_names,
            error_code='',
        )
        .filter(Q(http_status__isnull=True) | Q(http_status__lt=400))
        .exclude(policy_decision__in=(ToolExecution.DECISION_DENIED,
                                      ToolExecution.DECISION_ESCALATED))
        .order_by('-created_at', '-id')[:limit]
    )


def get_recent_product_queries(conversation, executor, args, triggered_by=None):
    """Qué productos preguntó antes este cliente.

    Sale de la proyección propia (`product_query_resolved`), no de
    `args_redacted`: ahí vive el texto crudo del cliente, y construir memoria
    permanente sobre esa violación de R15 la cementaría.
    """
    limit = min(int(args.get('limit') or 3), MAX_ITEMS)
    seen, projection = set(), []
    for execution in _successful_executions(
            conversation, ['product_query_resolved'], limit * 4):
        summary = execution.result_summary_redacted or {}
        product = summary.get('producto')
        if not product or product in seen:
            continue
        seen.add(product)
        projection.append({
            'producto': product,
            'cuando': format_local_datetime(execution.created_at,
                                            conversation.organization),
        })
        if len(projection) >= limit:
            break
    executor.record_local(
        tool_name='get_recent_product_queries',
        summary={'consultas': len(projection)},
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(kind='READ', data=projection, validated=True,
                       scope=_scope(conversation, local_filters={'limit': limit}),
                       completeness='unknown', summary={'consultas': len(projection)})


def request_human(conversation, executor, args, triggered_by=None):
    """Ruta interna para tests y fallos controlados; el LLM no puede invocarla.

    Las transferencias se deciden en policy.evaluate / escalate_to_human,
    donde llevan razón, aviso visible y suspensión atómica del flujo.
    """
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
    return ToolOutcome(kind='EFFECT', validated=True, scope=_scope(conversation),
                       data={'handoff': True}, effects=({
                           'entity': 'human_handoff', 'reference': str(handoff.pk),
                           'action': 'request_human', 'state': 'persisted', 'result': 'success',
                       },), summary={'handoff_id': handoff.pk})


def set_client_path(conversation, executor, args, triggered_by=None):
    """Persiste la clasificación semántica de primera visita vs. cliente.

    La herramienta recibe un enum del modelo, no una frase del cliente. Su
    salida habilita o bloquea herramientas; no consulta expedientes ni revela
    si un nombre o teléfono existe en la clínica.
    """
    from . import confirmations, goals
    from .models import ConversationGoal

    requested = str((args or {}).get('path') or '')
    if requested not in (intake.PATH_NEW, intake.PATH_EXISTING):
        return ToolOutcome(ok=False, client_error='invalid_intake_path')
    if conversation.contact.owner_id is not None:
        return ToolOutcome(ok=False, client_error='intake_already_resolved')

    previous = conversation.intake_path
    changed = bool(previous and previous != requested)
    if changed:
        # Una propuesta de alta o agenda fue construida bajo la otra capacidad;
        # no puede sobrevivir a una corrección semántica del cliente.
        confirmations.supersede_pending(
            conversation, reason='client_path_corrected')
        active_goal = goals.get_open_goal(conversation)
        if active_goal is not None:
            goals.close(active_goal, ConversationGoal.STATUS_ABANDONED,
                        'cambió la ruta de atención')

    flow = dict(conversation.flow or {})
    # Los factores de identidad nunca deben contaminar una alta, ni volver a
    # aparecer si el cliente corrigió la interpretación anterior.
    if requested == intake.PATH_NEW or changed:
        flow.pop('aportado', None)
    conversation.intake_path = requested
    conversation.flow = flow
    conversation.save(update_fields=['intake_path', 'flow'])
    executor.record_local(
        tool_name=intake.PATH_SELECTION_TOOL,
        args_redacted={'path': requested},
        summary={'path': requested, 'changed': changed},
        triggered_by_message=triggered_by,
    )
    return ToolOutcome(
        ok=True,
        data={'ruta_cliente': intake.context_fact(conversation)},
        summary={'path': requested, 'changed': changed},
    )


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
    'get_offered_specialties': {
        'handler': get_offered_specialties,
        'tier': '1',
        'min_verification': 'unknown',
        'description': (
            'Especialidades que la clínica puede ofrecer hoy. Solo devuelve una '
            'especialidad cuando hay servicio activo Y personal activo con esa '
            'especialidad; no ofrezcas las que no salgan aquí.'
        ),
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
        'description': (
            'Busca productos activos. Una categoría aislada (alimentos, '
            'medicamentos, accesorios) busca por categoría; otras consultas '
            'buscan nombre, descripción y fabricante. Para agotados solo '
            'comunica que no hay; precio y stock solo aparecen si hay existencia.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'query': {'type': 'string'}},
            'required': ['query'],
        },
    },
    'get_appointments': {
        'handler': get_appointments,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'TODAS las citas del cliente verificado: próximas, pasadas, '
            'atendidas, canceladas y las que no alcanzó a venir. Cada una trae '
            'su estado, si ya pasó y su motivo — decide tú cuáles responden a '
            'lo que preguntó. Úsala también cuando dice que perdió una cita o '
            'que no pudo acudir: esas también salen aquí, con handle para '
            'reagendarlas o cancelarlas.'),
        'parameters': {
            'type': 'object',
            'properties': {'pet_handle': {'type': 'string'}},
            'required': [],
        },
    },
    # Memoria estructurada (F4). Tool PERSONAL: lo que este cliente preguntó es
    # su historial, así que exige el mismo nivel que `list_my_pets`. La otra
    # mitad de F4 —las visitas anteriores— la absorbió `get_appointments`: eran
    # las mismas citas con el filtro invertido, y separarlas fue justamente lo
    # que dejó a una cita perdida sin ninguna tool que la viera.
    'get_recent_product_queries': {
        'handler': get_recent_product_queries,
        'tier': '1',
        'min_verification': 'confirmed_in_chat',
        'description': ('Productos que este cliente preguntó en conversaciones '
                        'anteriores. Útil cuando dice «el producto que te '
                        'pregunté la otra vez».'),
        'parameters': {
            'type': 'object',
            'properties': {'limit': {'type': 'integer'}},
            'required': [],
        },
    },
    'find_available_slots': {
        'handler': find_available_slots,
        'tier': '1',
        'min_verification': 'unknown',
        'description': (
            'Hasta TRES alternativas libres para UN día concreto (formato '
            'YYYY-MM-DD). Úsalo si el cliente pidió una franja (mañana/tarde) '
            'o DESPUÉS de saber que su hora exacta no está disponible. '
            'Nunca concluyas que una hora concreta está ocupada porque no '
            'apareció aquí: para eso usa check_appointment_slot.'
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
    'check_appointment_slot': {
        'handler': check_appointment_slot,
        'tier': '1',
        'min_verification': 'unknown',
        'description': (
            'Disponibilidad de una hora CONCRETA. Úsala siempre que el '
            'cliente diga una hora exacta antes de afirmar que está ocupada.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time': {'type': 'string', 'description': 'HH:MM (24h)'},
            },
            'required': ['date', 'time'],
        },
    },
    BEGIN_OPERATION_TOOL: {
        'handler': begin_operation,
        'tier': '0',
        'min_verification': 'unknown',
        'description': (
            'Abre una NUEVA intención operativa después de que una operación '
            'anterior ya fue notificada. Úsala solamente si el mensaje '
            'entrante actual pide de verdad una nueva cita, alta, cancelación '
            'o cambio. No la uses para agradecer, saludar, despedirse ni '
            'consultar si algo ya quedó hecho. No agenda ni confirma nada: '
            'solo habilita las herramientas correctas para la nueva petición.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'operation': {
                    'type': 'string',
                    'enum': list(OPERATION_KINDS),
                },
            },
            'required': ['operation'],
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
            'Úsalo SOLO cuando el contacto no es un cliente existente; si YA '
            'es cliente y trae otra mascota, la herramienta es '
            'register_pet_and_schedule. PROPONE '
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
                'pet_birth_date': {
                    'type': 'string',
                    'description': (
                        'YYYY-MM-DD opcional. Pregunta si conoce una fecha '
                        'exacta o aproximada; si no conoce una fecha concreta, '
                        'omítela. No captures peso ni alergias por WhatsApp.'
                    ),
                },
                'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time': {'type': 'string', 'description': 'HH:MM (24h)'},
                'reason': {'type': 'string'},
            },
            'required': ['owner_name', 'pet_name', 'date', 'time', 'reason'],
        },
    },
    # Las dos altas de mascota de un cliente EXISTENTE. Sus descripciones se
    # escriben contra `register_new_client_and_pet` a propósito: el fallo del
    # piloto no fue que faltara la herramienta, fue que el modelo no sabía que
    # faltaba y prometió igual. Una frontera difusa reproduce ese fallo.
    'register_pet_and_schedule': {
        'handler': register_pet_and_schedule,
        'tier': '2',
        # Escribe en el expediente de una persona: misma barra que agendar o
        # cancelar. `phone_match` NO basta (INV-B).
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Registra OTRA mascota de un cliente que YA está en el sistema y '
            'le agenda su primera cita. Úsalo cuando el cliente ya está '
            'identificado y la mascota que menciona NO aparece en '
            'list_my_pets. NO pidas el nombre del cliente: ya lo tienes. '
            'PROPONE y espera el "sí". Fecha YYYY-MM-DD, hora HH:MM.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'pet_name': {'type': 'string'},
                'pet_species': {'type': 'string',
                                'description': 'perro/gato/… (opcional)'},
                'pet_birth_date': {
                    'type': 'string',
                    'description': (
                        'YYYY-MM-DD opcional; si no conoce una fecha concreta, '
                        'omítela. No captures peso ni alergias por WhatsApp.'
                    ),
                },
                'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'time': {'type': 'string', 'description': 'HH:MM (24h)'},
                'reason': {'type': 'string'},
            },
            'required': ['pet_name', 'date', 'time', 'reason'],
        },
    },
    'register_pet_only': {
        'handler': register_pet_only,
        'tier': '2',
        'min_verification': 'confirmed_in_chat',
        'description': (
            'Registra OTRA mascota de un cliente existente SIN agendarle '
            'cita. NO lo ofrezcas: el camino normal es registrarla junto con '
            'su primera cita (register_pet_and_schedule). Úsalo solo si el '
            'cliente ya dijo que no quiere agendar todavía. PROPONE y espera '
            'el "sí".'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'pet_name': {'type': 'string'},
                'pet_species': {'type': 'string',
                                'description': 'perro/gato/… (opcional)'},
                'pet_birth_date': {
                    'type': 'string',
                    'description': (
                        'YYYY-MM-DD opcional; si no conoce una fecha concreta, '
                        'omítela. No captures peso ni alergias por WhatsApp.'
                    ),
                },
            },
            'required': ['pet_name'],
        },
    },
    'set_client_path': {
        'handler': set_client_path,
        'tier': '0',
        'min_verification': 'unknown',
        'description': (
            'Registra la clasificación semántica que el cliente acaba de dar '
            'sobre su relación con la clínica. Úsala solamente cuando el '
            'cliente haya dejado claro si es su primera visita o si ya es '
            'cliente; no la adivines por su nombre, mascota o teléfono. No le '
            'responde al cliente: después continúa con la herramienta que la '
            'ruta habilitó.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'enum': ['new_client', 'existing_client'],
                },
            },
            'required': ['path'],
        },
    },
    'identify_client': {
        'handler': identify_client,
        'tier': '1',
        # `unknown` a propósito: puede identificar a un cliente existente que
        # aún no fue verificado. La frontera de triaje sí exige que esa ruta
        # semántica haya sido elegida antes de llegar aquí.
        'min_verification': 'unknown',
        'description': (
            'Identifica a una persona que ya indicó que es cliente existente. '
            'Úsala con los datos que esa persona aporte sobre su propio '
            'registro; no la uses para una primera visita ni solo porque '
            'mencionó un nombre o mascota. Te responde si ya quedó identificado '
            'y qué falta. NO te devuelve datos del expediente: tú nunca le '
            'dices un nombre al cliente para que lo confirme, es él quien los '
            'aporta.'
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
        'llm_exposed': False,
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


assert set(TOOL_SPECS) == set(EFFECTS), 'Every tool needs a static capability effect'
for _name, _spec in TOOL_SPECS.items():
    _spec.update(
        effect=EFFECTS[_name],
        identity_policy=('current_link' if _spec['min_verification'] != 'unknown'
                         else 'public' if EFFECTS[_name] == READ_PUBLIC else 'contact'),
        authorization_mode=('contained' if EFFECTS[_name] == WRITE_BUSINESS
                            else 'existing_identity' if EFFECTS[_name] == READ_PERSONAL
                            else 'existing_control' if EFFECTS[_name] == CONTROL else 'public'),
        result_contract='ToolOutcome/C3-v1',
    )
    if EFFECTS[_name] == WRITE_BUSINESS:
        _spec['operation_kind'] = _name
        _spec['idempotency_semantics'] = (
            'appointment_replay_by_header' if _name in ('create_appointment', 'register_new_client_and_pet')
            else 'expected_state' if _name in ('confirm_appointment', 'cancel_appointment', 'reschedule_appointment')
            else 'no_compound_atomicity')

TOOL_SPECS['get_appointments']['description'] += (
    ' Consulta también el estado de asistencia; preguntar si está confirmada '
    'es una lectura y nunca autoriza confirmarla.')
TOOL_SPECS['confirm_appointment']['description'] = (
    'WRITE de asistencia, bloqueado por containment. No sirve para consultas de estado.')


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


def as_openai_tools(conversation=None):
    """Specs en el formato de tool calling OpenAI-compatible (llm.py).

    Cuando hay conversación, el catálogo es una capacidad real, no una lista
    aspiracional: las tools incompatibles con la ruta de atención ni siquiera
    llegan al modelo. ``None`` conserva el catálogo completo para inspección y
    pruebas de schema.
    """
    from . import goals

    tools_payload = []
    for name, spec in TOOL_SPECS.items():
        if not spec.get('llm_exposed', True):
            continue
        # La autorización posrecibo pertenece al orquestador de turnos. Nunca
        # se ofrece al planner: de otro modo un modelo puede autoafirmar una
        # intención inexistente y volver a exponer agenda.
        if conversation is not None and name == BEGIN_OPERATION_TOOL:
            continue
        if conversation is not None and not intake.allows_tool(conversation, name):
            continue
        if (conversation is not None and spec['effect'] == READ_PERSONAL
                and not _verification_ok(conversation, spec['min_verification'])):
            continue
        if (conversation is not None
                and name != BEGIN_OPERATION_TOOL
                and not operation_tool_allowed(conversation, name)):
            continue
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

    # La salida libre no es un canal de negocio: obliga al modelo a declarar
    # que solo conversa o pide un dato. No existe un propósito “confirmar”:
    # las confirmaciones salen exclusivamente de `stage_pending` + planner.
    tools_payload.append({
        'type': 'function',
        'function': {
            'name': REPLY_TOOL_NAME,
            'description': (
                'Envía una respuesta conversacional al cliente. Úsala para '
                'contestar o pedir un dato. Nunca la uses para pedir una '
                'confirmación de agenda: las propuestas las emite el sistema.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'purpose': {
                        'type': 'string',
                        'enum': list(REPLY_PURPOSES),
                    },
                    'text': {'type': 'string'},
                },
                'required': ['purpose', 'text'],
            },
        },
    })
    return tools_payload


def run_tool(name, args, *, conversation, executor, triggered_by=None):
    """Punto único de ejecución. El Policy Engine (PR-11) valida tier y
    verificación ANTES; aquí queda la defensa en profundidad."""
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return ToolOutcome(ok=False, client_error='unknown_tool')
    if (executor.conversation.pk != conversation.pk
            or executor.agent_user.organization_id != conversation.organization_id
            or conversation.contact.organization_id != conversation.organization_id
            or conversation.channel_account.organization_id != conversation.organization_id):
        return ToolOutcome(kind='ERROR', error_kind='forbidden', client_error='verification_required')
    if intake.write_is_contained(name):
        executor.record_local(
            tool_name=name, args_redacted={}, policy_decision='denied',
            summary={'reason': 'autonomous_writes_paused'},
            triggered_by_message=triggered_by,
        )
        return ToolOutcome(ok=False, client_error='autonomous_writes_paused')
    if name == BEGIN_OPERATION_TOOL:
        executor.record_local(
            tool_name=name,
            args_redacted={},
            policy_decision='denied',
            summary={'reason': 'operation_authorization_managed_by_orchestrator'},
            triggered_by_message=triggered_by,
        )
        return ToolOutcome(
            ok=False,
            client_error='operation_authorization_managed_by_orchestrator',
        )
    if not intake.allows_tool(conversation, name):
        return ToolOutcome(
            ok=False,
            client_error=('intake_required' if intake.needs_selection(conversation)
                          else 'intake_path_conflict'),
        )
    if (name != BEGIN_OPERATION_TOOL
            and not operation_tool_allowed(conversation, name)):
        executor.record_local(
            tool_name=name,
            args_redacted={},
            policy_decision='denied',
            summary={'reason': 'operation_authorization_required'},
            triggered_by_message=triggered_by,
        )
        return ToolOutcome(ok=False,
                           client_error='operation_authorization_required')
    if not _verification_ok(conversation, spec['min_verification']):
        return ToolOutcome(ok=False, client_error='verification_required')
    if not isinstance(args, (dict, type(None))):
        return ToolOutcome(kind='ERROR', client_error='invalid_data')
    from . import goals
    parameters = (_with_confidence(spec['parameters']) if name in goals.TOOL_GOALS
                  else spec['parameters'])
    for key, value in (args or {}).items():
        schema = parameters.get('properties', {}).get(key)
        if schema is None:
            return ToolOutcome(kind='ERROR', client_error='invalid_data')
        expected = {'string': str, 'integer': int, 'object': dict}.get(schema.get('type'))
        if expected and type(value) is not expected:
            return ToolOutcome(kind='ERROR', client_error='invalid_data')
        if 'enum' in schema and value not in schema['enum']:
            return ToolOutcome(kind='ERROR', client_error='invalid_data')
        if schema.get('type') == 'number' and (type(value) not in (int, float) or not 0 <= value <= 1):
            return ToolOutcome(kind='ERROR', client_error='invalid_data')
        if name == 'get_recent_product_queries' and key == 'limit' and value < 1:
            return ToolOutcome(kind='ERROR', client_error='invalid_data')
    before = executor.last_execution_id
    outcome = spec['handler'](conversation, executor, args or {},
                              triggered_by=triggered_by)
    if executor.last_execution_id != before:
        executor.record_outcome(name, outcome)
    return outcome
