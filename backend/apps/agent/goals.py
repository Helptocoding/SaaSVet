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
from dataclasses import dataclass, field
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
class GoalSpec:
    name: str
    required_slots: tuple
    validators: dict = field(default_factory=dict)
    optional_slots: tuple = ()
    max_stall_turns: int = 3


SCHEDULE = 'schedule_appointment'
REGISTER = 'register_and_schedule'
CANCEL = 'cancel_appointment'
RESCHEDULE = 'reschedule_appointment'

GOAL_SPECS = {
    SCHEDULE: GoalSpec(
        name=SCHEDULE,
        required_slots=('pet_handle', 'date', 'time', 'reason'),
        validators={
            'pet_handle': _v_handle('mascota'),
            'date': _v_date,
            'time': _v_time,
            'reason': _v_text(),
        },
    ),
    REGISTER: GoalSpec(
        name=REGISTER,
        required_slots=('owner_name', 'pet_name', 'date', 'time', 'reason'),
        optional_slots=('pet_species',),
        validators={
            'owner_name': _v_text(2),
            'pet_name': _v_text(),
            'pet_species': _v_species,
            'date': _v_date,
            'time': _v_time,
            'reason': _v_text(),
        },
    ),
    CANCEL: GoalSpec(
        name=CANCEL,
        required_slots=('appointment_handle',),
        validators={'appointment_handle': _v_handle('cita')},
    ),
    RESCHEDULE: GoalSpec(
        name=RESCHEDULE,
        required_slots=('appointment_handle', 'new_date', 'new_time'),
        validators={
            'appointment_handle': _v_handle('cita'),
            'new_date': _v_date,
            'new_time': _v_time,
        },
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
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        status__in=(ConversationGoal.STATUS_ACTIVE,
                    ConversationGoal.STATUS_PAUSED),
    ).first()


def open_goal(conversation, name):
    """Abre (o retoma) el objetivo. Uno abierto por conversación: iniciar otro
    cancela el anterior — la spec §2.7 ya exigía un solo flujo de escritura."""
    from .models import ConversationGoal
    current = get_open_goal(conversation)
    if current is not None:
        if current.name == name:
            if current.status == ConversationGoal.STATUS_PAUSED:
                current.status = ConversationGoal.STATUS_ACTIVE
                current.save(update_fields=['status'])
            return current
        close(current, ConversationGoal.STATUS_CANCELLED, 'otro objetivo')
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


def pause(goal):
    from .models import ConversationGoal
    if goal is None or goal.status != ConversationGoal.STATUS_ACTIVE:
        return goal
    goal.status = ConversationGoal.STATUS_PAUSED
    goal.save(update_fields=['status'])
    return goal


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

    goal.low_confidence = low
    goal.missing = missing_slots(goal)
    if filled:
        goal.last_progress_at = timezone.now()
        goal.stall_turns = 0
    goal.save(update_fields=['slots', 'low_confidence', 'missing',
                             'last_progress_at', 'stall_turns'])
    return {'filled': filled, 'missing': goal.missing,
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
