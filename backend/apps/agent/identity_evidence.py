"""
agent/identity_evidence.py — Evidencia de identidad: extraer, sellar, verificar.

**Servicio ÚNICO** (plan de continuidad, D17/D28). Antes había dos caminos hacia
`identity._promote`: `policy` verificaba de forma pasiva con el texto del turno y
`identify_client` lo hacía desde el tool loop. Ninguno de los dos comprobaba si el
nombre lo había dicho el sistema primero, y el pasivo ni siquiera satisfacía el
slot del compromiso — así que el agente podía pedir la mascota justo después de
haber verificado con ella.

**El modelo interpreta; el servidor comprueba** (ADR p59). La gramática cerrada
y los dos regímenes probatorios se retiraron: enumeraban formas de nombrar una
mascota y de negar identidad, dos espacios infinitos, y en producción rechazaron
a un cliente legítimo que había contestado bien (conv 21). Lo que queda es la
barrera que de verdad cerraba el bypass: el valor que el modelo propone tiene que
aparecer en un mensaje **del cliente**. Puede equivocarse leyendo; no puede
inventar el aporte.

Reglas que este módulo hace cumplir:

- **La procedencia la deriva el servidor**: el mensaje origen lo localiza este
  módulo dentro de la ventana, nunca llega en los argumentos de una tool.
- **Anti-eco por primera mención** (D7c) con el matcher TOLERANTE (D6): aceptar
  exige estricto, detectar un eco exige laxo. Con un solo matcher, «Lunna» dicho
  por staff no se detectaba y «Luna» del cliente promovía.
- **Unión cerrada** (D33): verificar un `EchoRejected` es inexpresable, y además
  se rechaza en runtime.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.channels.models import Message
from apps.channels.selectors import visible_messages

from . import identity
from .models import ContactIdentity, Conversation, ConversationGoal

logger = logging.getLogger('agent.events')

# Ventana de vida de una evidencia de identidad. La sesión NO sirve como ventana:
# `close_inactive_conversations` mide inactividad, no vida, y en producción hay
# conversaciones de 29 h y 47 h (plan D7b).
IDENTITY_EVIDENCE_TTL = timedelta(minutes=60)

# Un solo régimen desde p59: lo propone el modelo y el servidor lo comprueba
# contra el texto real. Se conserva el nombre del campo (`match_mode`) para no
# romper la lectura de los `flow` y slots ya escritos; ahora dice QUIÉN propuso.
MATCHED_BY_MODEL_CLAIM = 'model_claim'

# Regímenes de p58, retirados en p59. Se dejan como constantes muertas SOLO para
# que un `flow` sellado antes del despliegue siga siendo legible en auditoría.
MODE_PASSIVE = 'passive_free_text'
MODE_CHALLENGE = 'challenge_response'

# Dónde vive la evidencia SELLADA dentro de `Conversation.flow`. Distinta de
# `flow['aportado']`, que es lo que el modelo dice haber oído y no lleva
# procedencia.
FLOW_KEY = 'identity_evidence'


# ---------------------------------------------------------------------------
# Unión cerrada del resultado de resolución (D33)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoEvidence:
    """El turno no aporta identidad. El turno sigue su curso."""
    reason: str = ''


@dataclass(frozen=True)
class SealedPetEvidence:
    """Evidencia con procedencia sellada. Lo ÚNICO que `verify` acepta."""
    value: str
    registered_name: str
    from_message_id: int
    match_mode: str
    captured_at: object


@dataclass(frozen=True)
class EchoRejected:
    """El sistema dijo ese nombre antes que el cliente: no es aporte suyo.

    **No expone `.sealed`**: verificar a partir de esto no es algo que haya que
    acordarse de no hacer, es algo que no se puede escribir.
    """
    from_message_id: int
    disclosure_message_id: int


# ---------------------------------------------------------------------------
# Resolución: el modelo interpreta, el servidor comprueba (ADR p59)
# ---------------------------------------------------------------------------
# Aquí vivía una **gramática cerrada** (sustantivo clínico + `para/de`, posesivo
# de mascota, verbo de estado) más una lista de negaciones de identidad y dos
# regímenes probatorios derivados por el servidor. Retirado todo en p59, con el
# motivo medido en producción:
#
#   'koler'  -> None    en passive_free_text
#   'koler'  -> 'Koler' en challenge_response
#
# Conv 21: el cliente contestó exactamente lo que se le preguntó, con el nombre
# correcto de su mascota, y se rechazó por llegar «sin marco». Seis mensajes y 18
# minutos, y se fue sin su cita. La gramática enumeraba formas de nombrar una
# mascota y la lista de negaciones enumeraba formas de negar identidad: dos
# espacios infinitos, así que cada fraseo nuevo era un bug nuevo.
#
# Lo que NO cambia, y es lo que de verdad cerraba el bypass de p58:
#
#   1. PROCEDENCIA — el servidor localiza qué mensaje *del cliente*, en *esta*
#      conversación, contiene el valor. Nunca llega en los argumentos de la tool.
#   2. ANTI-ECO — primera mención gana, sobre mensajes realmente emitidos.
#   3. TTL — 60 min sobre el mensaje origen.
#
# El modelo pasa de elegir el régimen con que se le juzga (el agujero fino de
# D35) a **proponer una lectura que el servidor comprueba contra el texto real**.
# Puede equivocarse interpretando; no puede inventar el aporte.


def resolve_pet_evidence(conversation, claimed, *, now=None):
    """`NoEvidence` | `SealedPetEvidence` | `EchoRejected`.

    `claimed` es el valor que el modelo afirma que aportó el cliente. El
    servidor lo resuelve contra las mascotas registradas y **exige encontrarlo
    en un mensaje entrante del cliente** dentro de la ventana: ésa es la
    barrera, y es la que impide que el modelo se invente el aporte.

    Ya no hay ruta pasiva. Sin gramática, un escaneo sin propuesta del modelo
    promovería con cualquier coincidencia de token —«¿va a haber sol mañana?»
    con una mascota llamada Sol— que es exactamente el bug que la gramática
    existía para tapar. Con una sola vía, la intención del modelo ES el marco.
    """
    now = now or timezone.now()
    contact = conversation.contact
    if contact.owner_id is None:
        return NoEvidence('sin owner')

    registered_names = identity._pet_names(contact.owner)
    if not registered_names:
        return NoEvidence('owner sin mascotas')

    # 1 · ¿lo que el modelo afirma corresponde a una mascota de ESTE expediente?
    candidate = _registered_match(claimed, registered_names)
    if candidate is None:
        return NoEvidence('no es una de sus mascotas')

    # 2 · LA BARRERA · ¿lo dijo el cliente, de verdad, en esta conversación?
    #
    # Ventana = entrantes del cliente dentro del TTL, del más viejo al más
    # nuevo: la primera mención es la que cuenta, que es lo que hace
    # comprobable el anti-eco del paso 3.
    window = now - IDENTITY_EVIDENCE_TTL
    said_by_client = visible_messages(
        Message.objects.filter(
            conversation=conversation,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            created_at__gte=window,
        )
    ).order_by('created_at', 'id')

    source = next(
        (message for message in said_by_client
         if _says_the_pet(message.body or '', claimed, candidate)),
        None,
    )
    if source is None:
        return NoEvidence('el cliente no lo dijo')

    # 3 · anti-eco: ¿lo dijimos NOSOTROS antes que él?
    disclosure = _first_disclosure(conversation, candidate, source, now=now)
    if disclosure is not None:
        return EchoRejected(from_message_id=source.pk,
                            disclosure_message_id=disclosure.pk)

    return SealedPetEvidence(
        value=(source.body or '').strip()[:120],
        registered_name=candidate,
        from_message_id=source.pk,
        match_mode=MATCHED_BY_MODEL_CLAIM,
        captured_at=now,
    )


# Lo que lee recepción cuando el aporte resultó ser un eco. Vive aquí, con el
# detector, y no en el call site: cuando había dos rutas cada una tenía su copia.
ECHO_HANDOFF_DETAIL = (
    'El dato con el que intentó identificarse ya lo habíamos mencionado '
    'nosotros antes que él, así que no confirma quién es. Verifícalo tú y '
    'registra la verificación.'
)


def log_echo_rejected(conversation, resolution):
    """Deja el rastro del rechazo. Sin cuerpos de mensaje: solo ids (R15)."""
    logger.info('AGENT_IDENTITY_ECHO_REJECTED', extra={
        'event': 'AGENT_IDENTITY_ECHO_REJECTED',
        'organization_id': conversation.organization_id,
        'conversation_id': conversation.pk,
        'source_message_id': resolution.from_message_id,
        'disclosure_message_id': resolution.disclosure_message_id,
    })


def _says_the_pet(body, claimed, candidate):
    """¿Este mensaje del cliente nombra a la mascota?

    Se acepta contra **lo que el modelo transcribió** o contra **el nombre
    registrado**: con «Luna Bella» en el expediente, el cliente escribe «cita
    para Luna» y el modelo propone «Luna». Exigir el nombre completo en el texto
    rechazaría a quien llama a su perra como la llama siempre.
    """
    return (identity.matches_pet_name_tolerant(body, claimed)
            or identity.matches_pet_name_tolerant(body, candidate))


def _registered_match(claimed, registered_names):
    """La mascota registrada que corresponde a lo que el modelo afirmó.

    Tolerante (typo, nombre de pila de un compuesto), porque el modelo puede
    reescribir lo que leyó. Si encajan DOS nombres distintos no se elige: eso
    sería la decisión automática entre candidatos que INV-C prohíbe en su
    dominio, y aquí tampoco corresponde.
    """
    if not (claimed or '').strip():
        return None
    matched = {}
    for registered in registered_names:
        if identity.matches_pet_name_tolerant(claimed, registered):
            matched[identity._norm(registered)] = registered
    if len(matched) != 1:
        return None
    return next(iter(matched.values()))

def _first_disclosure(conversation, candidate, inbound, *, now):
    """El saliente que reveló el nombre ANTES de que el cliente lo aportara.

    Matcher TOLERANTE a propósito (D6): un falso rechazo cuesta un escalado; un
    falso negativo abre historial y herramientas personales. Staff escribiendo
    «Lunna» tiene que contar como revelación.
    """
    window = now - IDENTITY_EVIDENCE_TTL
    history = visible_messages(
        Message.objects.filter(conversation=conversation,
                               created_at__gte=window,
                               created_at__lte=inbound.created_at)
    ).order_by('created_at', 'id')
    for message in history:
        if not identity.matches_pet_name_tolerant(message.body or '', candidate):
            continue
        if message.direction == Message.DIRECTION_IN:
            return None          # el cliente lo dijo primero: no es eco
        return message
    return None


# ---------------------------------------------------------------------------
# Verificación: la ÚNICA vía a `_promote`
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """Todo lo que la transacción mutó. El caller reasigna lo que tenga cacheado
    (D31): reasignar solo `contact` deja `flow` viejo y republica evidencia que
    el reconciliador acaba de borrar."""
    verified: bool
    contact_identity: object
    conversation_flow: dict
    goal_satisfied: bool = False
    resumed_goal: object = None
    source_message_id: int = None
    match_mode: str = ''
    anomalies: list = field(default_factory=list)


def verify_pet_evidence(conversation, sealed):
    """Promueve, sella el aporte y cierra el reto — todo en un solo commit.

    Cerrar el reto va DENTRO: `goals.finish_identity` es `close()` + `resume()`,
    y omitirlo dejaba «verificado + reto en primer plano + tarea suspendida», o
    sea el agente atascado justo después de verificar bien.
    """
    from . import goals

    if not isinstance(sealed, SealedPetEvidence):
        # Garantía en RUNTIME, no solo de tipos: los chequeos estáticos pueden
        # no correr, y aquí se decide una promoción.
        raise TypeError(
            'verify_pet_evidence solo acepta SealedPetEvidence; '
            f'recibió {type(sealed).__name__}'
        )

    anomalies = []
    with transaction.atomic():
        contact = ContactIdentity.objects.select_for_update().get(
            pk=conversation.contact_id)
        convo = Conversation.objects.select_for_update().get(pk=conversation.pk)
        open_goals = list(
            ConversationGoal.objects.select_for_update()
            .filter(conversation=convo,
                    status__in=ConversationGoal.OPEN_STATUSES)
            .order_by('id')
        )

        identity._promote(contact)

        # Clave PROPIA, separada de `flow['aportado']`: ahí el modelo acumula lo
        # que el cliente dice por su cuenta (el reto familiar lo necesita a lo
        # largo de varios turnos) y no lleva procedencia. Mezclarlas haría que el
        # reconciliador, al caducar la evidencia sellada, borrara de paso la
        # acumulación del reto familiar.
        evidence = dict((convo.flow or {}).get(FLOW_KEY) or {})
        evidence['pet_name'] = {
            'value': sealed.registered_name,
            'from_message': sealed.from_message_id,
            'match_mode': sealed.match_mode,
            'captured_at': sealed.captured_at.isoformat(),
        }
        convo.flow = dict(convo.flow or {})
        convo.flow[FLOW_KEY] = evidence
        convo.save(update_fields=['flow'])

        foreground_identity = [
            goal for goal in open_goals
            if goal.name in goals.IDENTITY_GOALS
            and goal.status in ConversationGoal.FOREGROUND_STATUSES
        ]
        if len(foreground_identity) > 1:
            # La DB lo prohíbe (`conversationgoal_one_open_per_conversation`).
            # Esto es una comprobación de invariante, no una rama funcional: si
            # salta, hay que verlo.
            anomalies.append('multiple_foreground_identity')
            logger.error('AGENT_IDENTITY_GOAL_ANOMALY', extra={
                'event': 'AGENT_IDENTITY_GOAL_ANOMALY',
                'organization_id': convo.organization_id,
                'conversation_id': convo.pk,
                'goals': [goal.pk for goal in foreground_identity],
            })

        commitment = foreground_identity[0] if foreground_identity else None
        satisfied = False
        resumed = None
        if commitment is not None:
            goals.satisfy(commitment, 'pet', sealed.registered_name,
                          provenance=evidence['pet_name'])
            satisfied = True
            resumed = goals.finish_identity(
                convo, commitment, ConversationGoal.STATUS_COMPLETED,
                'identified')

    return VerificationResult(
        verified=True,
        contact_identity=contact,
        conversation_flow=convo.flow,
        goal_satisfied=satisfied,
        resumed_goal=resumed,
        source_message_id=sealed.from_message_id,
        match_mode=sealed.match_mode,
        anomalies=anomalies,
    )


# ---------------------------------------------------------------------------
# Caducidad: reducer PURO + reconciliador con efectos (D26)
# ---------------------------------------------------------------------------

def reduce_identity_facts(conversation, now=None):
    """FUNCIÓN PURA: `(vigentes, vencidos)` de `flow['aportado']`.

    No escribe. La separación existe porque el TTL no es una comparación suelta
    sino estado derivado, y mezclarlo con escritura hacía que `missing_slots`
    pudiera tocar la base y que ensamblar un prompt mutara estado — además de
    una recursión real (`satisfy` → `missing_slots` → recalcular `missing`).
    """
    now = now or timezone.now()
    stored = (conversation.flow or {}).get(FLOW_KEY) or {}
    valid, expired = {}, {}
    for key, fact in stored.items():
        if not isinstance(fact, dict) or not fact.get('from_message'):
            expired[key] = fact          # forma legacy: sin procedencia, no vale
            continue
        captured = _parse_dt(fact.get('captured_at'))
        if captured is None or now - captured > IDENTITY_EVIDENCE_TTL:
            expired[key] = fact
            continue
        valid[key] = fact
    return valid, expired


def reconcile_identity_facts(conversation, now=None):
    """Aplica la caducidad: limpia `flow`, vacía los slots afectados y recalcula
    `missing`. Corre UNA vez, al inicio del turno (D29)."""
    from . import goals

    now = now or timezone.now()
    valid, expired = reduce_identity_facts(conversation, now=now)
    if not expired:
        return VerificationResult(
            verified=False, contact_identity=conversation.contact,
            conversation_flow=conversation.flow or {})

    conversation.flow = dict(conversation.flow or {})
    conversation.flow[FLOW_KEY] = valid
    conversation.save(update_fields=['flow'])

    commitment = goals.get_identity_commitment(conversation)
    if commitment is not None:
        factors = {'pet_name': 'pet', 'owner_name': 'titular',
                   'phone_digits': 'digits'}
        touched = False
        for key in expired:
            slot = factors.get(key)
            if slot and slot in (commitment.slots or {}):
                commitment.slots.pop(slot, None)
                touched = True
        if touched:
            commitment.missing = goals.missing_slots(commitment)
            commitment.save(update_fields=['slots', 'missing'])

    logger.info('AGENT_IDENTITY_EVIDENCE_EXPIRED', extra={
        'event': 'AGENT_IDENTITY_EVIDENCE_EXPIRED',
        'organization_id': conversation.organization_id,
        'conversation_id': conversation.pk,
        'factors': sorted(expired),
    })
    return VerificationResult(
        verified=False, contact_identity=conversation.contact,
        conversation_flow=conversation.flow)


def _parse_dt(raw):
    if not raw:
        return None
    if hasattr(raw, 'tzinfo'):
        return raw
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        from datetime import timezone as dt_timezone
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed
