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


def _v_birth_date(value, conversation):
    """Fecha de nacimiento conocida, incluso si el cliente la expresa como aproximada.

    El modelo Pet solo conserva una fecha, no un grado de precisión. Por eso
    este factor acepta exclusivamente una fecha concreta y nunca inventa un día
    para convertir una edad textual o un mes/año incompleto.
    """
    try:
        day = datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False, None, 'formato'
    from apps.core.datetime_utils import org_today_local
    if day > org_today_local(conversation.organization):
        return False, None, 'futuro'
    return True, day.isoformat(), ''


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
    # Cómo se NOMBRA el dato al publicarlo al modelo (É-F5 Fase 3, C3). Sin
    # esto el bloque de estado viajaba con la clave interna —`me_falta:
    # ['date', 'pet_handle']`— y el modelo aprendía a hablar en jerga del
    # sistema. Vive aquí, junto al `why`, y no en un mapa aparte: un mapa
    # obliga a tocar DOS sitios por factor nuevo, que es exactamente el
    # "camino nuevo por cada hecho" que esta fase viene a eliminar.
    label: str = ''

    def __post_init__(self):
        if not (self.why or '').strip():
            raise ValueError(
                f"Factor '{self.name}' sin `why`. R9 (ADR p55 §5): todo dato "
                f"que se le pide al cliente lleva un motivo decible en voz alta."
            )

    def as_fact(self):
        """El factor como HECHO publicable: qué falta y para qué."""
        return {'dato': self.label or self.name, 'para': self.why}


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
ADD_PET = 'add_pet_and_schedule'
ADD_PET_ONLY = 'add_pet_only'
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
                   _v_handle('mascota'),
                   label='la mascota que vamos a atender'),
            Factor('date', 'apartar el día en la agenda del veterinario',
                   _v_date,
                   label='el día de la cita'),
            Factor('time', 'apartarte la hora y que no se empalme con otra cita',
                   _v_time,
                   label='la hora de la cita'),
            Factor('reason',
                   'que el veterinario sepa qué revisar y le reserve el tiempo '
                   'que necesita', _v_text(),
                   label='el motivo de la consulta'),
        ),
    ),
    REGISTER: GoalSpec(
        name=REGISTER,
        factors=(
            Factor('owner_name', 'abrir tu expediente en la clínica',
                   _v_text(2),
                   label='tu nombre'),
            Factor('pet_name', 'abrir el expediente de tu mascota', _v_text(),
                   label='el nombre de tu mascota'),
            Factor('date', _WHY_ALTA_CON_CITA, _v_date,
                   label='el día de la cita'),
            Factor('time', _WHY_ALTA_CON_CITA, _v_time,
                   label='la hora de la cita'),
            Factor('reason',
                   'que el veterinario sepa qué revisar en esa primera visita',
                   _v_text(),
                   label='el motivo de la consulta'),
        ),
        optional_factors=(
            Factor('pet_species',
                   'que el veterinario prepare lo adecuado para tu mascota',
                   _v_species,
                   label='qué tipo de mascota es'),
            Factor('pet_birth_date',
                   'que el expediente tenga su fecha de nacimiento si la conoces',
                   _v_birth_date,
                   label='su fecha de nacimiento'),
        ),
    ),
    # Mascota NUEVA de un cliente que YA está registrado. Distinto de REGISTER:
    # aquí el expediente existe y el vínculo ya se verificó, así que no se pide
    # el nombre del cliente — pedirlo otra vez sería tratarlo como desconocido.
    ADD_PET: GoalSpec(
        name=ADD_PET,
        factors=(
            Factor('pet_name', 'abrir el expediente de tu otra mascota',
                   _v_text(), label='el nombre de tu mascota'),
            Factor('date', 'apartar el día en la agenda del veterinario',
                   _v_date, label='el día de la cita'),
            Factor('time', 'apartarte la hora y que no se empalme con otra cita',
                   _v_time, label='la hora de la cita'),
            Factor('reason',
                   'que el veterinario sepa qué revisar en esa primera visita',
                   _v_text(), label='el motivo de la consulta'),
        ),
        optional_factors=(
            Factor('pet_species',
                   'que el veterinario prepare lo adecuado para tu mascota',
                   _v_species, label='qué tipo de mascota es'),
            Factor('pet_birth_date',
                   'que el expediente tenga su fecha de nacimiento si la conoces',
                   _v_birth_date, label='su fecha de nacimiento'),
        ),
    ),
    # Alta SIN cita. Existe porque el PO decidió permitirla, pero **nunca se
    # ofrece**: el camino que se propone es siempre con cita (política de la
    # clínica, igual que en REGISTER). Es un compromiso aparte —y no una
    # bandera de ADD_PET— para que quedarse sin cita sea un acto explícito en
    # `ToolExecution` y se pueda medir, en vez de un slot que nadie llenó.
    ADD_PET_ONLY: GoalSpec(
        name=ADD_PET_ONLY,
        factors=(
            Factor('pet_name', 'abrir el expediente de tu otra mascota',
                   _v_text(), label='el nombre de tu mascota'),
        ),
        optional_factors=(
            Factor('pet_species',
                   'que su expediente quede completo desde el principio',
                   _v_species, label='qué tipo de mascota es'),
            Factor('pet_birth_date',
                   'que el expediente tenga su fecha de nacimiento si la conoces',
                   _v_birth_date, label='su fecha de nacimiento'),
        ),
    ),
    CANCEL: GoalSpec(
        name=CANCEL,
        factors=(
            Factor('appointment_handle',
                   'asegurarme de que cancelo la cita correcta',
                   _v_handle('cita'),
                   label='cuál de tus citas'),
        ),
    ),
    RESCHEDULE: GoalSpec(
        name=RESCHEDULE,
        factors=(
            Factor('appointment_handle',
                   'asegurarme de que muevo la cita correcta',
                   _v_handle('cita'),
                   label='cuál de tus citas'),
            Factor('new_date', 'apartar el día nuevo en la agenda', _v_date,
                   label='el día nuevo'),
            Factor('new_time',
                   'apartarte la hora nueva con el veterinario', _v_time,
                   label='la hora nueva'),
        ),
    ),
}

# Qué objetivo abre cada herramienta de escritura.
TOOL_GOALS = {
    'create_appointment': SCHEDULE,
    'register_new_client_and_pet': REGISTER,
    'register_pet_and_schedule': ADD_PET,
    'register_pet_only': ADD_PET_ONLY,
    'cancel_appointment': CANCEL,
    'reschedule_appointment': RESCHEDULE,
}


# ---------------------------------------------------------------------------
# Compromisos de IDENTIDAD (É-F4 Fase 3, R7)
# ---------------------------------------------------------------------------
# Hasta aquí vivían como tres dicts sueltos en `Conversation.flow`
# (`identity_triage`, `family_challenge`, `identity_challenge`): un blob que no
# se agrega, no se mide y se destruía con un `pop`. Son compromisos como
# cualquier otro —promesa, paso actual, lo ya reunido, presupuesto de paciencia
# y salida terminal— así que viven en el mismo modelo.
#
# Sus `why` estaban en `tier0.FACTOR_WHY`, un dict paralelo que la Fase 0
# introdujo como mínimo honesto. Aquí desaparece: el motivo pertenece al
# factor (R9), no a una tabla de copy indexada por etapa.

TRIAGE = 'identity_triage'
FAMILY = 'family_challenge'
TITULAR_CHALLENGE = 'identity_challenge'

_WHY_DIGITS = 'confirmar que eres tú y proteger los datos del titular'
_WHY_PET = 'proteger el expediente: ese nombre solo lo sabes tú'
_WHY_TITULAR = 'buscar el registro con el nombre correcto'

IDENTITY_SPECS = {
    TRIAGE: GoalSpec(
        name=TRIAGE,
        factors=(
            Factor('client_kind',
                   'no pedirte datos de más ni abrirte un expediente '
                   'duplicado si ya eres cliente',
                   label='si ya has venido antes o es tu primera vez'),
        ),
        max_stall_turns=2,
    ),
    FAMILY: GoalSpec(
        name=FAMILY,
        factors=(
            Factor('titular', _WHY_TITULAR,
                   label='el nombre del titular del registro'),
            Factor('pet', _WHY_PET,
                   label='el nombre de una de sus mascotas'),
            Factor('digits', _WHY_DIGITS,
                   label='los últimos 4 dígitos del teléfono registrado'),
        ),
        max_stall_turns=2,
    ),
    TITULAR_CHALLENGE: GoalSpec(
        name=TITULAR_CHALLENGE,
        factors=(
            # SOLO `pet` (plan de continuidad, D20). `owner` salió porque el
            # nombre del titular dejó de ser factor de verificación (D4b): el
            # sistema lo conoce y se lo muestra al staff en la bandeja, así que
            # no prueba nada sobre quien escribe. Cambiar solo `falta` en
            # `identify_client` no habría bastado — `context_block` seguiría
            # publicando que falta «el nombre del titular» y el modelo lo
            # pediría.
            Factor('pet', _WHY_PET,
                   label='el nombre de una de sus mascotas'),
        ),
        max_stall_turns=2,
    ),
}

IDENTITY_GOALS = frozenset(IDENTITY_SPECS)

# Tres conjuntos, no uno (plan de continuidad, D37). «Pertenece a IDENTITY_GOALS»
# respondía a la vez a tres preguntas distintas —¿es de identidad? ¿se puede
# iniciar? ¿se puede reanudar?— y por eso `policy` resucitaba al frente filas de
# una máquina retirada. Producción tenía una `identity_triage` suspendida.
HISTORICAL_IDENTITY_GOALS = frozenset({TRIAGE, FAMILY, TITULAR_CHALLENGE})
STARTABLE_IDENTITY_GOALS = frozenset({FAMILY, TITULAR_CHALLENGE})
RESUMABLE_IDENTITY_GOAL_NAMES = frozenset({FAMILY, TITULAR_CHALLENGE})

ALL_SPECS = {**GOAL_SPECS, **IDENTITY_SPECS}


def is_resumable_identity_goal(goal, now=None):
    """PREDICADO sobre la fila, no pertenencia a un conjunto de nombres.

    `TRIAGE` es identidad **histórica**: nunca iniciable, nunca reanudable, y
    nunca tratada como tarea normal. Sin este predicado, un reto de la FSM
    retirada volvía al frente y arrastraba un `GoalSpec` que ya no conduce nadie.
    """
    if goal is None:
        return False
    from .models import ConversationGoal
    if goal.name not in RESUMABLE_IDENTITY_GOAL_NAMES:
        return False
    return goal.status in ConversationGoal.OPEN_STATUSES


def is_orphan_identity_goal(goal, now=None):
    """Huérfano = reto de identidad que ya no puede conducirse.

    Predicado formal, no adjetivo: sin él la remediación era ambigua en los dos
    sentidos (cerrar de más destruye un reto válido; cerrar solo la fila
    observada deja viva la vía que resucitaría otra).
    """
    if goal is None or goal.name not in HISTORICAL_IDENTITY_GOALS:
        return False
    return not is_resumable_identity_goal(goal, now=now)


def why_for(goal_name, factor_name):
    """Motivo decible en voz alta de un factor (R9). '' si no aplica."""
    spec = ALL_SPECS.get(goal_name)
    return spec.why(factor_name) if spec else ''


def spec_for(name):
    return ALL_SPECS.get(name)


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def get_open_goal(conversation):
    """El compromiso de TAREA en el frente (agendar, cancelar, reagendar…).

    Un suspendido no está al frente: se ofrece de vuelta, no se retoma solo.

    **Excluye los compromisos de identidad a propósito.** `context_block`
    publica `me_falta` al modelo; si un reto de identidad apareciera ahí, el
    sistema le estaría enumerando al cliente los factores que se le van a
    pedir — justo lo que G4 prohíbe ("el cliente aporta, el sistema verifica";
    jamás se enumeran datos para que los confirme). Los retos se consultan con
    `get_identity_commitment`.
    """
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        status__in=ConversationGoal.FOREGROUND_STATUSES,
    ).exclude(name__in=IDENTITY_GOALS).first()


def get_suspended_goal(conversation):
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        status=ConversationGoal.STATUS_SUSPENDED,
    ).first()


def open_goal(conversation, name, *, authorization_message=None,
              operation_assessment=None):
    """Abre, retoma o SUPLANTA.

    Cambio de ADR p55 §3 (R4): abrir otro compromiso ya no **cancela** el
    anterior — lo **suspende**. Un cliente cuyo perro convulsiona a mitad de
    agendar no abandonó la cita; al cerrar la urgencia hay que poder decir
    "¿retomamos la cita de Luna?". Con `close(CANCELLED)` esa frase era
    imposible porque el compromiso ya no existía.

    Si ya había uno suspendido, ese sí se da por **abandonado**: el slot es
    único (ver constraint) y apilar compromisos no tiene caso de uso hoy.

    **No crea retos de identidad** (plan de continuidad, D36): ésos tienen un
    escritor único, `start_identity`, invocado desde un solo sitio productivo. Sin
    este rechazo, un refactor futuro produce de verdad el estado que
    `finish_identity` tiene que reparar.
    """
    from .models import ConversationGoal
    if name in HISTORICAL_IDENTITY_GOALS:
        raise ValueError(
            f'open_goal no crea retos de identidad ({name}); '
            'usa start_identity, que es el escritor único'
        )
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
        authorization_message=authorization_message,
        operation_assessment=operation_assessment,
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


def close_task_commitments(conversation, status, reason=''):
    """Cierra los compromisos de TAREA vivos: el del frente y el suspendido.

    Los de identidad quedan fuera a propósito — se apartan solos con
    `park_identity` para sobrevivir a una escalada.
    """
    from .models import ConversationGoal
    live = list(
        ConversationGoal.objects.filter(
            conversation=conversation,
            status__in=ConversationGoal.OPEN_STATUSES,
        ).exclude(name__in=IDENTITY_GOALS)
    )
    return [close(goal, status, reason) for goal in live]


# ---------------------------------------------------------------------------
# Compromisos de identidad — mismo modelo, accesores propios (R7)
# ---------------------------------------------------------------------------

def get_identity_commitment(conversation):
    """El reto de identidad en curso, si lo hay."""
    from .models import ConversationGoal
    return ConversationGoal.objects.filter(
        conversation=conversation,
        name__in=IDENTITY_GOALS,
        status__in=ConversationGoal.FOREGROUND_STATUSES,
    ).first()


def start_identity(conversation, name, *, first_factor, working_state=None):
    """Arranca un reto de identidad y le da el FRENTE de la conversación.

    Mientras el agente pregunta "¿los últimos 4 dígitos?", el frente es el
    reto: la tarea que el cliente pidió sigue viva pero **suspendida**, y se
    retoma sola al terminar (`finish_identity`). Antes la tarea seguía
    marcada como activa en paralelo, que es la fragmentación que R7 retira.
    """
    from .models import ConversationGoal
    live = get_identity_commitment(conversation)
    if live is not None:
        close(live, ConversationGoal.STATUS_ABANDONED,
              'reiniciado' if live.name == name else 'otro reto')

    # Un reto viejo suspendido queda superado por este (en el camino normal
    # `evaluate` ya lo habría retomado antes de llegar aquí).
    stale_identity = get_suspended_goal(conversation)
    if stale_identity is not None and stale_identity.name in IDENTITY_GOALS:
        close(stale_identity, ConversationGoal.STATUS_ABANDONED, 'reiniciado')

    task = get_open_goal(conversation)
    if task is not None:
        stale = get_suspended_goal(conversation)
        if stale is not None:
            close(stale, ConversationGoal.STATUS_ABANDONED,
                  'desplazado por otro compromiso')
        suspend(task, supplanted_by=name)

    commitment = ConversationGoal.objects.create(
        organization=conversation.organization,
        conversation=conversation,
        name=name,
        return_to=first_factor,
        working_state=working_state or {},
    )
    _log(commitment, 'AGENT_GOAL_OPENED')
    return commitment


# ---------------------------------------------------------------------------
# La pregunta del reto (ADR p59)
# ---------------------------------------------------------------------------
# `bind_identity_question_enqueued` y `mark_identity_question_emitted` se
# RETIRARON. Existían solo para alimentar `derive_match_mode`: probar que el
# sistema había preguntado de verdad —y que el cliente lo había visto— era la
# condición para aplicar el régimen tolerante en vez del estricto.
#
# Con un solo régimen no hay nada que decidir, así que tres escritores, un campo
# en `working_state` y un write dentro de la transacción del sender se vuelven
# maquinaria sin destino. El sender ya no escribe nada al enviar la pregunta, que
# de paso retira el único write que podía fallar con un WhatsApp ya entregado.
#
# **La pregunta la sigue poniendo el sistema** (`T0_IDENTITY_QUESTION`, D38): el
# modelo demostró en producción que pide los 4 dígitos si le dejas, y ése es un
# factor retirado por circular. Lo que desaparece es el registro de que se hizo,
# no la práctica de hacerla.



def park_identity(conversation, commitment, *, going_to_human):
    """Aparta un reto de identidad SIN cerrarlo (R5/R8).

    El slot de suspensión es **único**, así que antes hay que resolver qué
    pasa con la TAREA que este reto había suspendido:

    - `going_to_human=True` (2 fallos reales, tope de desvíos): la tarea se
      cierra como `handoff` — se va con la persona que va a atender.
    - `going_to_human=False` (el tamiz que no se entendió y cede al planner):
      la tarea **vuelve al frente**, que es donde estaba antes del reto.

    En ambos casos el slot queda libre para el reto, que es el que tiene que
    sobrevivir: es lo que hace que un `4586` correcto llegado tarde resuelva
    la verificación en vez de caer al vacío (conv 13).
    """
    from .models import ConversationGoal
    task = get_suspended_goal(conversation)
    if task is not None and task.name not in IDENTITY_GOALS:
        if going_to_human:
            close(task, ConversationGoal.STATUS_HANDOFF, 'handoff')
        else:
            resume(task)
    return suspend(commitment,
                   supplanted_by='handoff' if going_to_human else 'planner')


def finish_identity(conversation, commitment, status, reason=''):
    """Cierra el reto y devuelve el frente a la tarea suspendida.

    El retorno es DETERMINISTA, no depende de que el modelo vuelva a llamar
    una herramienta: el cliente nunca abandonó lo que estaba pidiendo, solo
    tuvo que identificarse primero (R4).

    **Invariante semántico** (plan de continuidad, D32/D34): lo que se reanuda
    tiene que ser una TAREA, no otro reto de identidad. Los constraints
    garantizan cardinalidad —como máximo un suspendido— pero no significado, y
    reanudar un reto de identidad aquí significaría volver a pedir identidad
    justo después de haberla verificado. El caso llega por la resurrección de
    filas legacy (`policy`), no por el flujo normal: `start_identity` limpia las
    suyas.
    """
    from .models import ConversationGoal

    close(commitment, status, reason)
    suspended = get_suspended_goal(conversation)
    if suspended is not None and suspended.name in IDENTITY_GOALS:
        close(suspended, ConversationGoal.STATUS_ABANDONED,
              'duplicate_identity_goal')
        logger.error('AGENT_IDENTITY_GOAL_ANOMALY', extra={
            'event': 'AGENT_IDENTITY_GOAL_ANOMALY',
            'organization_id': conversation.organization_id,
            'conversation_id': conversation.pk,
            'goal': suspended.pk,
            'goal_name': suspended.name,   # `name` es atributo de LogRecord
        })
        return None
    return resume(suspended)


def advance_to(commitment, factor):
    """Mueve el reto al siguiente factor. `return_to` ES la etapa actual: la
    coordenada de dónde se retoma si algo interrumpe (R4)."""
    if commitment is None:
        return None
    commitment.return_to = (factor or '')[:32]
    commitment.save(update_fields=['return_to'])
    return commitment


def satisfy(commitment, factor, value=True, *, provenance=None):
    """Da por aportado un factor del reto.

    Guarda que el factor quedó SATISFECHO, no el secreto: de los 4 dígitos se
    registra `True`, nunca los dígitos (hoy tampoco se guardan, y este modelo
    no es excusa para empezar). Los nombres sí se guardan — el titular ya
    viajaba en el estado y el embudo lo necesita.

    **CHOKE POINT de procedencia** (plan de continuidad, D15): un factor de
    identidad con valor solo se guarda si viene con su `provenance` (el mensaje
    del cliente que lo aportó, sellado por `identity_evidence`). Bloquear aquí
    —en el ESCRITOR— y no al publicar es lo que hace la regla cierta para
    cualquier vía futura: `anchored_identity_facts` publica `titular_declarado`
    desde estos slots, así que filtrar solo `flow['aportado']` dejaba entrar por
    aquí el nombre que el modelo copió de una fuga.

    El alcance es **solo factores de identidad**: el nombre de la función es
    genérico y otros goals la usan para slots de negocio (fecha, hora, motivo),
    que no tienen procedencia que exigir.
    """
    if commitment is None:
        return None
    if (commitment.name in IDENTITY_GOALS and value is not True
            and provenance is None):
        raise ValueError(
            f'satisfy({factor!r}) en un reto de identidad exige provenance: '
            'un valor sin mensaje origen no es un aporte del cliente'
        )
    commitment.slots[factor] = {'value': value,
                                'confidence': DEFAULT_CONFIDENCE}
    if provenance is not None:
        commitment.slots[factor]['from_message'] = provenance.get('from_message')
        commitment.slots[factor]['match_mode'] = provenance.get('match_mode')
    commitment.missing = missing_slots(commitment)
    commitment.last_progress_at = timezone.now()
    commitment.save(update_fields=['slots', 'missing', 'last_progress_at'])
    return commitment


def register_failure(commitment):
    """Un intento FALLIDO (dato equivocado). Devuelve si se agotó la paciencia.

    Preguntar no llega aquí nunca (É-F4 Fase 0): una no-respuesta no es una
    respuesta equivocada.
    """
    if commitment is None:
        return False
    commitment.attempts_failed += 1
    commitment.save(update_fields=['attempts_failed'])
    spec = spec_for(commitment.name)
    return commitment.attempts_failed >= (spec.max_stall_turns if spec else 2)


def scratch(commitment, key, default=None):
    return (commitment.working_state or {}).get(key, default) if commitment else default


def set_scratch(commitment, **values):
    if commitment is None:
        return None
    commitment.working_state = {**(commitment.working_state or {}), **values}
    commitment.save(update_fields=['working_state'])
    return commitment


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


def promise_for(name):
    """Lo que le prometimos al cliente, en voz de clínica. '' si no aplica.

    Accesor público de `_GOAL_PROMISE`, que ya existía para hablarle al
    cliente. La bandeja lo reusa para contarle al STAFF qué venía haciendo el
    agente cuando escaló: la promesa es la misma, cambia quién la lee.
    """
    return _GOAL_PROMISE.get(name, '')


def last_task_goal(conversation):
    """El compromiso de TAREA que estaba en juego, viva o no.

    `get_open_goal` solo mira los estados de primer plano porque decide qué
    hacer AHORA. Esto es para explicar algo que ya pasó: cuando el agente
    escala, el objetivo queda en `handoff`, `blocked` o `abandoned` —
    justamente los estados que aquel excluye. Sin esto, la bandeja no puede
    contar por qué llegó el caso, que es el 90 % de su valor.
    """
    from .models import ConversationGoal
    return (ConversationGoal.objects
            .filter(conversation=conversation)
            .exclude(name__in=IDENTITY_GOALS)
            .order_by('-id')
            .first())


def describe(goal):
    """Proyección legible por una persona: qué se buscaba, qué había, qué faltaba.

    Devuelve etiquetas, nunca nombres de slot. La recepcionista no tiene por
    qué saber qué es un `pet_handle`; el `label` del `Factor` ya dice «la
    mascota que vamos a atender», y vive junto al dato precisamente para que
    no haya un segundo diccionario de copy que se desincronice.
    """
    spec = spec_for(goal.name)
    if spec is None:
        return None
    faltan = set(missing_slots(goal))
    captured, missing = [], []
    for factor in spec.all_factors:
        label = factor.label or factor.name
        value = (goal.slots.get(factor.name) or {}).get('value')
        if value:
            captured.append({'label': label, 'value': str(value)})
        elif factor.name in faltan:
            missing.append({'label': label, 'why': factor.why})
    return {
        'name': goal.name,
        'promise': promise_for(goal.name),
        'status': goal.status,
        'captured': captured,
        'missing': missing,
    }


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

# Qué le PROMETIMOS al cliente, en su idioma. La clave interna
# (`schedule_appointment`) no viaja: el modelo no debe aprender a hablar en
# jerga del sistema (C3, É-F5 Fase 3).
_GOAL_PROMISE = {
    SCHEDULE: 'agendarle una cita',
    REGISTER: 'darlo de alta y agendarle su primera cita',
    ADD_PET: 'registrar a su otra mascota y agendarle su primera cita',
    ADD_PET_ONLY: 'registrar a su otra mascota',
    CANCEL: 'cancelarle una cita',
    RESCHEDULE: 'moverle una cita',
    TRIAGE: 'saber si ya es cliente para poder atenderlo',
    FAMILY: 'verificar que puede gestionar las citas del titular',
    TITULAR_CHALLENGE: 'confirmar que es el titular del registro',
}


def context_block(conversation):
    """Qué le debemos a esta persona, publicado como HECHOS.

    Antes viajaban las claves internas —`objetivo: schedule_appointment`,
    `me_falta: ['date', 'time']`, `estado: active`— y el modelo aprendía a
    nombrar los datos como los nombra la base. C3 lo prohíbe: el estado se
    publica en lenguaje semántico o no se publica.

    Cada dato que falta viaja con su MOTIVO (R9), que hasta aquí solo existía
    dentro del `Factor` y no llegaba al modelo salvo por una plantilla. Ahora
    el agente puede contestar «¿y eso para qué?» sin que nadie se lo prepare.
    """
    goal = get_open_goal(conversation)
    if goal is None:
        return None
    spec = spec_for(goal.name)
    by_name = {f.name: f for f in spec.all_factors} if spec else {}

    def _fact(slot):
        factor = by_name.get(slot)
        return factor.as_fact() if factor else {'dato': slot, 'para': ''}

    def _label(slot):
        factor = by_name.get(slot)
        return factor.label if (factor and factor.label) else slot

    block = {
        'le_prometi': _GOAL_PROMISE.get(goal.name, goal.name),
        # También lo YA reunido va con etiqueta: el gate lo cazó cuando solo
        # se habían etiquetado los huecos. Los VALORES no se traducen —un
        # handle (`mascota_1`) es el vocabulario con el que el modelo llama a
        # las herramientas y tiene que viajar tal cual.
        'ya_tengo': {_label(slot): value
                     for slot, value in values(goal).items()},
        'me_falta': [_fact(slot) for slot in missing_slots(goal)],
    }
    if goal.low_confidence:
        # Valores que el modelo propuso con poca seguridad: se confirman con
        # el cliente, jamás se asumen.
        block['por_confirmar'] = {_label(slot): value
                                  for slot, value in goal.low_confidence.items()}
    gastados = [slot for slot, n in (goal.asked or {}).items()
                if n >= 2]
    if gastados:
        # C7 · no es un dato más: es una instrucción de conducta. Repetir por
        # tercera vez es defecto del sistema, no del cliente.
        block['ya_lo_pediste_dos_veces_no_lo_repitas'] = [
            _label(s) for s in gastados
        ]
    return block


def _log(goal, event):
    logger.info(event, extra={
        'event': event,
        'organization_id': goal.organization_id,
        'conversation_id': goal.conversation_id,
        'goal': goal.name,
        'status': goal.status,
    })
