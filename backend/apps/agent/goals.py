"""
agent/goals.py — Conversación por objetivos (É-F3 W2).

Hasta aquí el agente funcionaba como `mensaje → intent → tool → respuesta`:
cada turno re-derivaba la intención desde una ventana de 12 mensajes y las
herramientas de escritura eran todo-o-nada. Una recepcionista no funciona así:
persigue un objetivo, sabe qué le falta, lo pide, y cierra.

La capa de objetivos existía en el diseño (`whatsapp-agent-architecture.md`
§7.3: `flow.name` + `flow.slots`) y nunca se implementó.

Contrato (revisión del PO, 2026-07-24) — deliberadamente pequeño:

- **Slot = nombre + validador.** Nada de extractores: el LLM propone el valor
  ("el próximo martes como las cuatro" → date/time) y el código lo valida.
  Escribir parsers de lenguaje natural es un pozo sin fondo; el modelo ya hace
  bien esa tarea. Lo que no se puede es *confiar* en ella — para eso está el
  validador.
- **El objetivo NO sabe preguntar.** Publica `missing` y ya; cómo se pregunta
  es del modelo. En cuanto el dominio redacta preguntas se convierte en un
  motor de diálogo y arrastra copy, tono y localización.
- **Confianza por slot.** Un valor por debajo del umbral NO llena el slot:
  entra a `low_confidence` para que el agente lo confirme en vez de asumirlo.
  Es un filtro EN SERIE con el validador, no una alternativa.
- **Estado explícito** (`active/paused/completed/cancelled/handoff`), en tabla
  propia: un blob JSON no se agrega, y esto tiene que servir para analytics.

El objetivo se sitúa ANTES de la confirmación tier-2 y DESPUÉS del Policy
Engine: no toca ninguna barrera de control existente.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('agent.events')

DEFAULT_CONFIDENCE = 1.0
HORIZON_DAYS = 60          # spec §2.6
CONFIDENCE_SUFFIX = '_confidence'


def confidence_threshold():
    return float(getattr(settings, 'AGENT_SLOT_CONFIDENCE_THRESHOLD', 0.70))


# ---------------------------------------------------------------------------
# Validadores — (ok, normalizado, motivo). Ninguno redacta copy para el cliente.
# ---------------------------------------------------------------------------

def _v_handle(prefix):
    def validate(value, conversation):
        from . import tools
        if not value:
            return False, None, 'vacío'
        public_id = tools.resolve_handle(conversation, str(value))
        if public_id is None:
            return False, None, 'handle desconocido'
        return True, str(value), ''
    return validate


def _v_date(value, conversation):
    from apps.core.datetime_utils import org_today_local
    try:
        day = datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False, None, 'formato'
    today = org_today_local(conversation.organization)
    if day < today:
        return False, None, 'pasado'
    if day > today + timedelta(days=HORIZON_DAYS):
        return False, None, 'fuera de horizonte'
    return True, day.isoformat(), ''


def _v_time(value, conversation):
    try:
        parsed = datetime.strptime(str(value)[:5], '%H:%M')
    except (ValueError, TypeError):
        return False, None, 'formato'
    return True, parsed.strftime('%H:%M'), ''


def _v_text(min_len=1):
    def validate(value, conversation):
        text = str(value or '').strip()
        if len(text) < min_len:
            return False, None, 'vacío'
        return True, text, ''
    return validate


def _v_species(value, conversation):
    """La especie es opcional en el dominio: un valor no mapeable NO invalida
    el slot, se queda vacío (el backend rechaza fuera de SPECIES_CHOICES)."""
    from . import tools
    return True, tools._normalize_species(value), ''


# ---------------------------------------------------------------------------
# Catálogo — 4 objetivos, solo multi-turno
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Factor:
    """Un dato que un compromiso necesita para poder cumplirse.

    **`why` no es documentación: es un requisito estructural (R9, ADR p55
    §5).** Es el motivo que el agente tiene que poder decir en voz alta si el
    cliente pregunta "¿y eso para qué?". Un `Factor` sin `why` **no compila** —
    literalmente: el constructor lo rechaza.

    R9 empezó como criterio de revisión de copy y el principio
    contenido/control la volvió estructural: el árbitro decide *qué* factor
    toca (control), nunca *cómo* se pide (contenido), así que el porqué tiene
    que vivir aquí o no existe en ningún lado. En la conv 13 el agente pidió
    los últimos 4 dígitos y, al preguntarle el cliente para qué, no tenía qué
    contestar.

    El `why` se escribe en **voz de clínica**, jamás de sistema: "el alta la
    hacemos junto con tu primera cita" sí; "el sistema me pide una fecha" no
    (R6 — es el defecto exacto de la conv 12, y `WhyVoiceTests` lo gatea).
    """
    name: str
    why: str
    validator: object = None

    def __post_init__(self):
        if not (self.why or '').strip():
            raise ValueError(
                f"Factor '{self.name}' sin `why`. R9 (ADR p55 §5): todo dato "
                f"que se le pide al cliente lleva un motivo decible en voz alta."
            )


@dataclass(frozen=True)
class GoalSpec:
    """Catálogo de un compromiso. `required_slots`/`validators` se DERIVAN de
    los factores para que el resto del módulo no cambie: el contrato de slot
    (nombre + validador, ADR p54) sigue igual, solo gana el `why`."""
    name: str
    factors: tuple = ()
    optional_factors: tuple = ()
    max_stall_turns: int = 3

    @property
    def all_factors(self):
        return self.factors + self.optional_factors

    @property
    def required_slots(self):
        return tuple(f.name for f in self.factors)

    @property
    def optional_slots(self):
        return tuple(f.name for f in self.optional_factors)

    @property
    def validators(self):
        return {f.name: f.validator
                for f in self.all_factors if f.validator is not None}

    def why(self, slot):
        for factor in self.all_factors:
            if factor.name == slot:
                return factor.why
        return ''


SCHEDULE = 'schedule_appointment'
REGISTER = 'register_and_schedule'
CANCEL = 'cancel_appointment'
RESCHEDULE = 'reschedule_appointment'

# El alta va SIEMPRE con la primera cita: es política de la clínica, no un
# requisito del schema (decisión del PO 2026-07-30; Fase 5 del plan É-F4 se
# canceló por esto). El motivo tiene que sonar a eso — en la conv 12 el agente
# dijo "el sistema me pide al menos una fecha y hora" y terminó discutiendo
# con el cliente en nombre de una tabla.
_WHY_ALTA_CON_CITA = (
    'el alta la hacemos junto con tu primera cita, así te queda todo listo de '
    'una vez'
)

GOAL_SPECS = {
    SCHEDULE: GoalSpec(
        name=SCHEDULE,
        factors=(
            Factor('pet_handle', 'saber a cuál de tus mascotas vamos a atender',
                   _v_handle('mascota')),
            Factor('date', 'apartar el día en la agenda del veterinario',
                   _v_date),
            Factor('time', 'apartarte la hora y que no se empalme con otra cita',
                   _v_time),
            Factor('reason',
                   'que el veterinario sepa qué revisar y le reserve el tiempo '
                   'que necesita', _v_text()),
        ),
    ),
    REGISTER: GoalSpec(
        name=REGISTER,
        factors=(
            Factor('owner_name', 'abrir tu expediente en la clínica',
                   _v_text(2)),
            Factor('pet_name', 'abrir el expediente de tu mascota', _v_text()),
            Factor('date', _WHY_ALTA_CON_CITA, _v_date),
            Factor('time', _WHY_ALTA_CON_CITA, _v_time),
            Factor('reason',
                   'que el veterinario sepa qué revisar en esa primera visita',
                   _v_text()),
        ),
        optional_factors=(
            Factor('pet_species',
                   'que el veterinario prepare lo adecuado para tu mascota',
                   _v_species),
        ),
    ),
    CANCEL: GoalSpec(
        name=CANCEL,
        factors=(
            Factor('appointment_handle',
                   'asegurarme de que cancelo la cita correcta',
                   _v_handle('cita')),
        ),
    ),
    RESCHEDULE: GoalSpec(
        name=RESCHEDULE,
        factors=(
            Factor('appointment_handle',
                   'asegurarme de que muevo la cita correcta',
                   _v_handle('cita')),
            Factor('new_date', 'apartar el día nuevo en la agenda', _v_date),
            Factor('new_time',
                   'apartarte la hora nueva con el veterinario', _v_time),
        ),
    ),
}

# Qué objetivo abre cada herramienta de escritura.
TOOL_GOALS = {
    'create_appointment': SCHEDULE,
    'register_new_client_and_pet': REGISTER,
    'cancel_appointment': CANCEL,
    'reschedule_appointment': RESCHEDULE,
}


def spec_for(name):
    return GOAL_SPECS.get(name)


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def get_open_goal(conversation):
    """El compromiso EN EL FRENTE (activo o desviado). Un suspendido no está
    al frente: se ofrece de vuelta, no se retoma solo."""
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        status__in=ConversationGoal.FOREGROUND_STATUSES,
    ).first()


def get_suspended_goal(conversation):
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        status=ConversationGoal.STATUS_SUSPENDED,
    ).first()


def open_goal(conversation, name):
    """Abre, retoma o SUPLANTA.

    Cambio de ADR p55 §3 (R4): abrir otro compromiso ya no **cancela** el
    anterior — lo **suspende**. Un cliente cuyo perro convulsiona a mitad de
    agendar no abandonó la cita; al cerrar la urgencia hay que poder decir
    "¿retomamos la cita de Luna?". Con `close(CANCELLED)` esa frase era
    imposible porque el compromiso ya no existía.

    Si ya había uno suspendido, ese sí se da por **abandonado**: el slot es
    único (ver constraint) y apilar compromisos no tiene caso de uso hoy.
    """
    from .models import ConversationGoal
    current = get_open_goal(conversation)
    if current is not None:
        if current.name == name:
            return resume(current)
        suspended = get_suspended_goal(conversation)
        if suspended is not None:
            close(suspended, ConversationGoal.STATUS_ABANDONED,
                  'desplazado por otro compromiso')
        suspend(current, supplanted_by=name)
    else:
        # Retomar explícitamente lo que se ofreció de vuelta.
        suspended = get_suspended_goal(conversation)
        if suspended is not None and suspended.name == name:
            return resume(suspended)
    goal = ConversationGoal.objects.create(
        organization=conversation.organization,
        conversation=conversation,
        name=name,
    )
    _log(goal, 'AGENT_GOAL_OPENED')
    return goal


def close(goal, status, reason=''):
    if goal is None:
        return None
    goal.status = status
    goal.closed_at = timezone.now()
    goal.closed_reason = reason[:80]
    goal.save(update_fields=['status', 'closed_at', 'closed_reason'])
    _log(goal, 'AGENT_GOAL_CLOSED')
    return goal


def deviate(goal, return_to):
    """El agente atiende otra cosa y VUELVE al punto exacto (R4).

    `return_to` es obligatorio: sin dirección de retorno esto no es un desvío,
    es una interrupción sobrevivida por suerte.
    """
    from .models import ConversationGoal
    if goal is None or goal.status != ConversationGoal.STATUS_ACTIVE:
        return goal
    if not (return_to or '').strip():
        raise ValueError(
            "deviate() exige `return_to` (R4, ADR p55 §3): un desvío sin "
            "dirección de retorno obliga a re-derivar la pregunta pendiente."
        )
    goal.status = ConversationGoal.STATUS_DEVIATED
    goal.return_to = return_to[:32]
    goal.save(update_fields=['status', 'return_to'])
    return goal


def suspend(goal, *, supplanted_by):
    """Otro compromiso tomó el frente. NO es abandono: se ofrece de vuelta."""
    from .models import ConversationGoal
    if goal is None or goal.status not in ConversationGoal.FOREGROUND_STATUSES:
        return goal
    goal.status = ConversationGoal.STATUS_SUSPENDED
    goal.supplanted_by = (supplanted_by or '')[:40]
    goal.save(update_fields=['status', 'supplanted_by'])
    return goal


def resume(goal):
    """Vuelve al frente conservando `return_to` (el punto exacto)."""
    from .models import ConversationGoal
    if goal is None or goal.status == ConversationGoal.STATUS_ACTIVE:
        return goal
    if goal.status not in ConversationGoal.OPEN_STATUSES:
        return goal
    goal.status = ConversationGoal.STATUS_ACTIVE
    goal.supplanted_by = ''
    goal.save(update_fields=['status', 'supplanted_by'])
    return goal


def block(goal, reason):
    """El dominio NO PUEDE cumplirlo (p.ej. `no_vet`): se dice una vez y se
    deja de pedir.

    Distinto de `abandon`, y la distinción importa: ahí el dominio sí podía y
    quien no quiso fue el cliente. Confundirlos manda a un humano casos que
    solo necesitaban cerrarse, y deja pidiendo para siempre los que de verdad
    no tienen salida.
    """
    from .models import ConversationGoal
    if goal is None:
        return None
    goal.blocked_reason = (reason or '')[:40]
    goal.save(update_fields=['blocked_reason'])
    return close(goal, ConversationGoal.STATUS_BLOCKED, reason)


def abandon(goal, reason=''):
    """El CLIENTE lo abandonó — incluido "no quiero agendar" dentro de un
    alta: esa restricción es política de la clínica y el dominio sí podía
    cumplirla, así que no es `block`."""
    from .models import ConversationGoal
    return close(goal, ConversationGoal.STATUS_ABANDONED, reason)


# Alias histórico: `pause` era el desvío sin dirección de retorno. Se conserva
# el nombre para no tocar los call sites de un golpe, pero ahora EXIGE saber
# dónde se retoma (R4).
def pause(goal, return_to=''):
    return deviate(goal, return_to or _default_return_to(goal))


def _default_return_to(goal):
    """Dónde retomar si el caller no lo dijo: el primer dato que falta. Es la
    pregunta que estaba pendiente — derivable del propio compromiso, no de la
    ventana de mensajes."""
    pending = missing_slots(goal) if goal is not None else []
    return pending[0] if pending else 'confirmacion'


def close_open_goal(conversation, status, reason=''):
    return close(get_open_goal(conversation), status, reason)


# ---------------------------------------------------------------------------
# Captura de slots
# ---------------------------------------------------------------------------

def capture(goal, raw_args, conversation):
    """Ingiere lo que el modelo propuso. Devuelve el estado del objetivo.

    Cada valor pasa por DOS filtros en serie:
      1. confianza ≥ umbral (¿el modelo está seguro?) → si no, `low_confidence`
      2. validador (¿el dato es válido?)              → si no, `rejected`

    Un valor rechazado nunca se pierde en silencio: viaja al contexto para que
    el agente lo confirme o lo vuelva a pedir.
    """
    spec = spec_for(goal.name)
    raw_args = raw_args or {}
    threshold = confidence_threshold()
    low, rejected, filled = [], {}, []

    known = set(spec.required_slots) | set(spec.optional_slots)
    # Foto previa: distinguir "el modelo reenvió lo mismo" de "el objetivo
    # avanzó". Sin esto, repetir los datos ya conocidos contaba como progreso
    # y el estancamiento no se detectaba nunca (piloto conv 12).
    before = {slot: (goal.slots.get(slot) or {}).get('value') for slot in known}
    for slot in known:
        if slot not in raw_args or raw_args.get(slot) in (None, ''):
            continue
        value = raw_args[slot]
        confidence = _confidence_of(raw_args, slot)
        if confidence < threshold:
            low.append({'slot': slot, 'valor': str(value)[:60],
                        'confianza': confidence})
            continue
        validator = spec.validators.get(slot)
        if validator is None:
            goal.slots[slot] = {'value': value, 'confidence': confidence}
            filled.append(slot)
            continue
        ok, normalized, why = validator(value, conversation)
        if not ok:
            rejected[slot] = why
            continue
        goal.slots[slot] = {'value': normalized, 'confidence': confidence}
        filled.append(slot)

    # PROGRESO = un slot que estaba vacío ahora tiene valor, o el cliente
    # corrigió uno (martes → jueves). Reafirmar lo ya sabido NO es avanzar.
    advanced = [slot for slot in filled
                if before.get(slot) != (goal.slots.get(slot) or {}).get('value')]

    goal.low_confidence = low
    goal.missing = missing_slots(goal)
    if advanced:
        goal.last_progress_at = timezone.now()
        goal.stall_turns = 0
    goal.save(update_fields=['slots', 'low_confidence', 'missing',
                             'last_progress_at', 'stall_turns'])
    return {'filled': filled, 'advanced': advanced, 'missing': goal.missing,
            'low_confidence': low, 'rejected': rejected}


def _confidence_of(raw_args, slot):
    raw = raw_args.get(slot + CONFIDENCE_SUFFIX, DEFAULT_CONFIDENCE)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    return min(max(value, 0.0), 1.0)


def missing_slots(goal):
    spec = spec_for(goal.name)
    if spec is None:
        return []
    return [slot for slot in spec.required_slots
            if not (goal.slots.get(slot) or {}).get('value')]


def is_complete(goal):
    return not missing_slots(goal)


def values(goal):
    """Slots normalizados listos para la herramienta ({slot: valor})."""
    return {slot: data.get('value')
            for slot, data in (goal.slots or {}).items()
            if data.get('value') not in (None, '')}


def mark_asked(goal, slots):
    """Cuenta cuántas veces se ha pedido cada slot (anti-repetición)."""
    for slot in slots:
        goal.asked[slot] = goal.asked.get(slot, 0) + 1
    goal.save(update_fields=['asked'])


def bump_stall(goal):
    """Un turno sin progreso. Devuelve si se agotó la paciencia del objetivo.

    Sustituye al presupuesto contable como disparador principal de escalada:
    "no avanzamos" es una señal semántica; "gastaste 15 llamadas" no lo es.
    """
    if goal is None:
        return False
    goal.stall_turns += 1
    goal.save(update_fields=['stall_turns'])
    spec = spec_for(goal.name)
    return goal.stall_turns >= (spec.max_stall_turns if spec else 3)


# ---------------------------------------------------------------------------
# Contexto para el modelo — DATOS, sin una sola palabra de copy
# ---------------------------------------------------------------------------

def context_block(conversation):
    goal = get_open_goal(conversation)
    if goal is None:
        return None
    block = {
        'objetivo': goal.name,
        'estado': goal.status,
        'ya_tengo': values(goal),
        'me_falta': missing_slots(goal),
    }
    if goal.low_confidence:
        # Valores que el modelo propuso con poca seguridad: se confirman con
        # el cliente, jamás se asumen.
        block['por_confirmar'] = goal.low_confidence
    repeated = [slot for slot, n in (goal.asked or {}).items() if n >= 2]
    if repeated:
        block['ya_preguntado_2_veces'] = repeated
    return block


def _log(goal, event):
    logger.info(event, extra={
        'event': event,
        'organization_id': goal.organization_id,
        'conversation_id': goal.conversation_id,
        'goal': goal.name,
        'status': goal.status,
    })
