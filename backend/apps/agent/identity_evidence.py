"""
agent/identity_evidence.py — Evidencia de identidad: extraer, sellar, verificar.

**Servicio ÚNICO** (plan de continuidad, D17/D28). Antes había dos caminos hacia
`identity._promote`: `policy` verificaba de forma pasiva con el texto del turno y
`identify_client` lo hacía desde el tool loop. Ninguno de los dos comprobaba si el
nombre lo había dicho el sistema primero, y el pasivo ni siquiera satisfacía el
slot del compromiso — así que el agente podía pedir la mascota justo después de
haber verificado con ella.

Reglas que este módulo hace cumplir, todas del plan:

- **El candidato lo extrae el servicio** (D30, §2.3.1), con una gramática cerrada:
  un token suelto nunca es evidencia. Con una mascota llamada «Sol», «¿va a haber
  sol mañana?» promovía.
- **`match_mode` lo deriva el servidor** (D35). Si dependiera del call site, el
  modelo elegiría el régimen probatorio llamando a `identify_client`.
- **La procedencia la deriva el servidor** (D24): el mensaje origen sale del
  burst, nunca de los argumentos de una tool.
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
# Gramática cerrada de marco fuerte (§2.3.1)
# ---------------------------------------------------------------------------
# Lo que la gramática no reconoce NO promueve. Falla segura: el modelo pregunta,
# un turno de más. Un marco laxo, en cambio, acepta «¿venden lentes para sol?».

_CLINICAL_NOUNS = {
    'cita', 'citas', 'consulta', 'consultas', 'vacuna', 'vacunas',
    'vacunacion', 'revision', 'urgencia', 'emergencia', 'bano', 'banio',
    'cirugia', 'operacion', 'desparasitacion', 'chequeo', 'control',
}
_PET_NOUNS = {
    'mascota', 'perro', 'perra', 'perrito', 'perrita', 'gato', 'gata',
    'gatito', 'gatita', 'cachorro', 'cachorra', 'michi', 'firulais',
}
_LINK_WORDS = {'para', 'de'}
# Verbos/estados que solo tienen sentido dicho de un ser vivo del cliente.
_STATE_STARTS = (
    ('necesita',), ('tiene',), ('presenta',), ('esta',), ('anda',),
    ('se', 'puso'), ('le', 'duele'), ('no', 'come'), ('no', 'quiere'),
    ('no', 'camina'), ('vomito',), ('vomita',), ('amanecio',),
)
# Negación de IDENTIDAD (rechaza). La de ESTADO CLÍNICO no: «Luna no come» es de
# los mensajes más importantes que manda un cliente, y una regla ciega sobre `no`
# lo tiraba.
_IDENTITY_NEGATIONS = (('no', 'es'), ('no', 'se', 'llama'), ('ni',))


def _tokens(text):
    return identity._norm(text).split()


def _spans(tokens, registered):
    """Posiciones donde `registered` aparece como token(s) COMPLETO(s)."""
    target = identity._norm(registered).split()
    if not target:
        return []
    found = []
    for start in range(len(tokens) - len(target) + 1):
        if tokens[start:start + len(target)] == target:
            found.append((start, start + len(target)))
    if found:
        return found
    # Nombre compuesto nombrado por una de sus partes: «Luna» por «Luna Bella».
    for part in (tok for tok in target if len(tok) >= 3):
        for index, token in enumerate(tokens):
            if token == part:
                found.append((index, index + 1))
    return found


def _framed(tokens, start, end):
    """¿El nombre aparece dentro de un marco fuerte? (gramática cerrada)"""
    before = tokens[:start]
    after = tokens[end:]

    for negation in _IDENTITY_NEGATIONS:
        if tuple(before[-len(negation):]) == negation:
            return False

    # <mascota> necesita|tiene|no come…
    for state in _STATE_STARTS:
        if tuple(after[:len(state)]) == state:
            return True

    # (cita|consulta|vacuna…) … (para|de) <mascota>
    if before and before[-1] in _LINK_WORDS:
        if any(word in _CLINICAL_NOUNS for word in before[:-1]):
            return True

    # mi (mascota|perro|gato…) [se llama] <mascota>
    #
    # `se llama` EXIGE ese sujeto posesivo: suelto aceptaba «el producto se llama
    # Luna». `_norm` ya se come el artículo «mi», así que el sustantivo de
    # mascota inmediatamente antes (con o sin «se llama») es la señal.
    tail = before[-3:]
    if tail and tail[-1] in _PET_NOUNS:
        return True
    if tuple(tail[-2:]) == ('se', 'llama') and any(
        word in _PET_NOUNS for word in before[:-2]
    ):
        return True
    return False


def extract_pet_candidate(text, registered_names, *, mode):
    """Nombre de mascota que el cliente aportó, o `None`.

    En `challenge_response` no hace falta marco: el sistema **acaba de
    preguntar** por el nombre, así que «Luna» a secas es la respuesta natural.
    En `passive_free_text` manda la gramática.

    Candidato único = un solo nombre normalizado DISTINTO (dos mascotas del
    mismo dueño llamadas «Luna» no invalidan identidad), y en compuestos gana el
    **longest-match**.
    """
    tokens = _tokens(text)
    if not tokens:
        return None

    matched = {}
    for registered in registered_names:
        if mode == MODE_CHALLENGE:
            if identity.matches_pet_name_tolerant(text, registered):
                matched[identity._norm(registered)] = registered
            continue
        for start, end in _spans(tokens, registered):
            if _framed(tokens, start, end):
                matched[identity._norm(registered)] = registered
                break

    if not matched:
        return None
    if len(matched) > 1:
        # Longest-match ANTES de evaluar unicidad: «Luna Bella» gana a «Luna».
        longest = max(matched, key=lambda name: len(name.split()))
        rivals = [name for name in matched
                  if len(name.split()) == len(longest.split())]
        if len(rivals) > 1:
            return None
        return matched[longest]
    return next(iter(matched.values()))


# ---------------------------------------------------------------------------
# Régimen probatorio: lo decide el SERVIDOR (D35)
# ---------------------------------------------------------------------------

def derive_match_mode(conversation, inbound_message, *, now=None):
    """`challenge_response` solo si el sistema preguntó de verdad y el cliente
    pudo verlo. Cualquier duda ⇒ `passive_free_text`.

    Ni los argumentos de la tool, ni el nombre de la tool, ni el caller pueden
    seleccionarlo: si pudieran, el modelo saltaría la gramática pasiva llamando a
    `identify_client` y elegiría con qué reglas se le juzga.
    """
    from . import goals

    now = now or timezone.now()
    commitment = goals.get_identity_commitment(conversation)
    if commitment is None:
        return MODE_PASSIVE

    asked = (commitment.working_state or {}).get('identity_question') or {}
    if asked.get('asked_state') != 'emitted':
        return MODE_PASSIVE                     # pending/failed/discarded: no la vio
    if not asked.get('deterministic_clause'):
        return MODE_PASSIVE                     # la pregunta no la puso el sistema
    if not asked.get('pet_pending'):
        return MODE_PASSIVE                     # no se preguntó por la mascota

    asked_at = _parse_dt(asked.get('asked_at'))
    if asked_at is None or now - asked_at > IDENTITY_EVIDENCE_TTL:
        return MODE_PASSIVE

    question = Message.objects.filter(pk=asked.get('message_id')).first()
    if question is None or question.conversation_id != conversation.pk:
        return MODE_PASSIVE
    if question.direction != Message.DIRECTION_OUT:
        return MODE_PASSIVE
    if question.status not in (Message.STATUS_SENT, Message.STATUS_DELIVERED,
                               Message.STATUS_READ):
        return MODE_PASSIVE
    # `asked_at` se estampa en el ENVÍO real, no al encolar: `Message.created_at`
    # no prueba el orden de emisión (el sender usa skip_locked con réplicas).
    if inbound_message is not None and asked_at >= inbound_message.created_at:
        return MODE_PASSIVE
    return MODE_CHALLENGE


# ---------------------------------------------------------------------------
# Resolución: extraer + sellar procedencia + anti-eco
# ---------------------------------------------------------------------------

def resolve_pet_evidence(conversation, burst_messages, *, now=None):
    """Devuelve `NoEvidence` | `SealedPetEvidence` | `EchoRejected`.

    `burst_messages` son los `Message` entrantes de este turno — objetos, no
    cuerpos: sin PK no hay procedencia que sellar (D24).
    """
    now = now or timezone.now()
    contact = conversation.contact
    if contact.owner_id is None:
        return NoEvidence('sin owner')

    registered = identity._pet_names(contact.owner)
    if not registered:
        return NoEvidence('owner sin mascotas')

    for message in burst_messages:
        if message.direction != Message.DIRECTION_IN:
            continue
        if message.author_type != Message.AUTHOR_CLIENT:
            continue
        if message.conversation_id != conversation.pk:
            # Ni «misma organización» ni «misma cuenta» bastan: podría ser el
            # mensaje de otro contacto de la misma clínica.
            continue
        mode = derive_match_mode(conversation, message, now=now)
        candidate = extract_pet_candidate(message.body or '', registered,
                                          mode=mode)
        if candidate is None:
            continue
        disclosure = _first_disclosure(conversation, candidate, message, now=now)
        if disclosure is not None:
            return EchoRejected(from_message_id=message.pk,
                                disclosure_message_id=disclosure.pk)
        return SealedPetEvidence(
            value=(message.body or '').strip()[:120],
            registered_name=candidate,
            from_message_id=message.pk,
            match_mode=mode,
            captured_at=now,
        )
    return NoEvidence('sin mención de mascota')


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
