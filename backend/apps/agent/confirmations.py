"""B7A preparation facade and historical tier-2 diagnostic readers.

New definitions live only in ConversationOperation. Legacy matching remains
behind B0 containment and cannot authorize an operation. B7B is not implemented.
"""

from .turn_changes import save_local, create_local, open_handoff, local_or_locked_conversation
import re
import uuid
from datetime import timedelta

from django.utils import timezone

PENDING_TTL = timedelta(minutes=30)  # spec §2.4

# A pending action is intentionally narrow: a later "sí" must only be able to
# execute the exact proposal that created it. These families also let us detect
# a new request that arrives while an older proposal is awaiting confirmation.
OPERATION_FAMILIES = {
    'create_appointment': 'schedule',
    'cancel_appointment': 'cancel',
    'reschedule_appointment': 'reschedule',
    'register_new_client_and_pet': 'register',
    'register_pet_and_schedule': 'register',
    'register_pet_only': 'register',
}
_FAMILY_STEMS = {
    'schedule': ('agend', 'program'),
    'cancel': ('cancel', 'anul'),
    'reschedule': ('reagend', 'muev', 'mov', 'cambi'),
    'register': ('registr', 'agreg', 'alta'),
}
_BENIGN_ACKNOWLEDGEMENTS = {
    'gracias', 'muchas gracias', 'mil gracias', 'ok gracias',
    'perfecto gracias',
}
_SCOPE_CHANGE_PHRASES = (
    'otra mascota', 'otro perro', 'otro gato', 'otro paciente', 'otra cita',
    'otro dia', 'otra fecha', 'otra hora', 'otro horario',
    'diferente horario', 'horario diferente', 'distinta hora', 'hora distinta',
)
_RESCHEDULE_CHANGE_STEMS = ('cambi', 'muev', 'mov', 'reagend')
_SCHEDULE_PARAMETER_TOKENS = {
    'hoy', 'manana', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes',
    'sabado', 'domingo', 'mediodia', 'tarde', 'noche',
}
_TIME_OR_DATE = re.compile(r'\b\d{1,2}(?::\d{2})?\b')

# Parafraseos LITERALES (una plantilla por acción). Fechas absolutas (G5).
CONFIRM_CREATE = (
    "Te confirmo: cita para *{pet}* el *{fecha}*, motivo: {reason}. "
    "¿Es correcto?"
)
CONFIRM_CANCEL = (
    "Voy a cancelar la cita de *{pet}* del *{fecha}*. ¿Confirmas?"
)
CONFIRM_REPLACEMENT_CREATE = (
    "Tu cita anterior se canceló mientras hablábamos. Te confirmo: agendo "
    "una nueva para *{pet}* el *{fecha}*, motivo: {reason}. ¿Es correcto?"
)

CONFIRM_RESCHEDULE = (
    "Muevo la cita de *{pet}* del *{vieja}* al *{nueva}*. ¿Confirmas?"
)
CONFIRM_CREATE_NEW_CLIENT = (
    "Te confirmo: te registro como cliente (*{owner}*) y agendo cita para "
    "*{pet}* ({especie}) el *{fecha}*, motivo: {reason}. ¿Es correcto?"
)
# Mascota nueva de un cliente que YA está registrado: no se le vuelve a decir
# "te registro como cliente" — ya lo es, y repetirlo suena a que el sistema no
# lo reconoce (que es justo lo que el cliente reclamó en el piloto).
CONFIRM_ADD_PET = (
    "Te confirmo: registro a *{pet}* ({especie}) en tu expediente y le agendo "
    "cita el *{fecha}*, motivo: {reason}. ¿Es correcto?"
)
CONFIRM_ADD_PET_ONLY = (
    "Te confirmo: registro a *{pet}* ({especie}) en tu expediente, sin cita "
    "por ahora. ¿Es correcto?"
)

EXPIRED_REPARAPHRASE = "Pasó un rato — te confirmo de nuevo:\n{paraphrase}"


def stage_pending(conversation, *, tool, args=None, paraphrase=None, witness=None):
    """B7A facade. Legacy arguments never become an operation definition."""
    from .turn_changes import current_changes
    if current_changes() is not None:
        # B7A: actual workers never persist duplicated executable JSON. B3's
        # final publication prepares from B6; args/paraphrase are not authority.
        # Renderer/emission/consent binding is deliberately left to B7B.
        return None
    from . import matter_binding, operations
    if witness is None:
        raise operations.PreparationDenied('source_turn_required')
    goal = matter_binding.current_goal(conversation)
    if not goal:
        raise operations.PreparationDenied('matter_required')
    return operations.prepare_operation(witness=witness, goal_id=goal.pk, capability=tool,
        expected_binding_revision=goal.binding_revision,
        expected_identity_revision=conversation.contact.authorization_revision)


def get_pending(conversation):
    # Historical JSON is diagnostic compatibility only. Canonical operations
    # use current_operation; no synthetic proposal_id/digest/consent projection.
    return conversation.flow.get('pending_action')


def current_operation(conversation):
    from . import matter_binding, operations
    goal = matter_binding.current_goal(conversation)
    if goal is None:
        return None
    return operations.current_pending(organization_id=conversation.organization_id,
        conversation_id=conversation.pk, goal_id=goal.pk)


def stage_operation(**kwargs):
    from .operations import prepare_operation
    return prepare_operation(**kwargs)


def is_expired(pending, now=None):
    now = now or timezone.now()
    try:
        from datetime import datetime
        expires = datetime.fromisoformat(pending['expires_at'])
        if timezone.is_naive(expires):
            from datetime import timezone as dt_tz
            expires = expires.replace(tzinfo=dt_tz.utc)
        return now > expires
    except (KeyError, ValueError, TypeError):
        return True


def clear_pending(conversation):
    _retire_operation(conversation, 'cleared')
    if 'pending_action' in conversation.flow:
        flow = dict(conversation.flow)
        flow.pop('pending_action', None)
        conversation.flow = flow
        save_local(conversation, update_fields=['flow'])


def bind_pending_message(conversation, message_id):
    """Records the outbound message that contains the exact proposal."""
    pending = get_pending(conversation)
    if not pending:
        return

    flow = dict(conversation.flow)
    staged = dict(pending)
    staged['proposal_message_id'] = str(message_id)
    flow['pending_action'] = staged
    conversation.flow = flow
    save_local(conversation, update_fields=['flow'])


def binding_is_current(conversation, pending):
    """B6 semantic precondition, independent of the legacy delivery evidence."""
    from . import matter_binding
    goal = matter_binding.current_goal(conversation)
    return bool(goal and matter_binding.metadata(goal)
                and (pending or {}).get('binding') == matter_binding.snapshot(goal)
                and matter_binding.projection(conversation)['bindings']['owner']
                and not matter_binding.projection(conversation)['unresolved'])


def is_confirmable(conversation, pending):
    """True solo si el cliente recibió una propuesta tipada y vigente."""
    from apps.channels.models import Message
    if not binding_is_current(conversation, pending):
        return False

    proposal_id = str((pending or {}).get('proposal_id') or '')
    message_id = (pending or {}).get('proposal_message_id')
    if not proposal_id or not message_id:
        return False
    return Message.objects.filter(
        pk=message_id,
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        semantic_type=Message.SEMANTIC_CONFIRMATION,
        operation_key=proposal_id,
    ).exclude(
        status__in=(Message.STATUS_DISCARDED, Message.STATUS_FAILED),
    ).exists()

def supersede_pending(conversation, *, reason):
    """Invalidates a stale proposal before the planner processes a new topic.

    Only minimal audit metadata is retained. The old executable arguments are
    removed, so a later bare affirmative cannot revive the stale action.
    """
    _retire_operation(conversation, reason)
    pending = get_pending(conversation)
    if not pending:
        return None

    flow = dict(conversation.flow)
    flow.pop('pending_action', None)
    flow['last_superseded_pending'] = {
        'proposal_id': pending.get('proposal_id'),
        'tool': pending.get('tool'),
        'reason': reason,
        'superseded_at': timezone.now().isoformat(),
    }
    conversation.flow = flow
    save_local(conversation, update_fields=['flow'])
    return pending


def _retire_operation(conversation, reason):
    from .turn_changes import current_changes
    if current_changes() is not None:
        # B6 goal save / ownership invalidation retire atomically at B3 flush.
        return
    from .operations import invalidate_pending
    invalidate_pending(organization_id=conversation.organization_id,
                       conversation_id=conversation.pk, reason='context_invalidated')


def operation_family(tool):
    """Returns the coarse operation family for a staged tool."""
    return OPERATION_FAMILIES.get(tool, 'other')


def classify_pending_reply(pending, burst):
    """Classifies a reply without allowing semantic expansion of a proposal.

    A short, isolated affirmative confirms. Any new operation or substantive
    affirmative (for example, "sí, pero para otra mascota") invalidates the
    proposal and returns to normal planning. This is deliberately conservative:
    losing a stale proposal is recoverable; executing it is not.
    """
    from . import matchers

    messages = [part.strip() for part in burst if part and part.strip()]
    if not messages:
        return 'unclear'

    family = pending.get('operation_family') or operation_family(
        pending.get('tool')
    )
    if any(_mentions_different_operation(part, family) for part in messages):
        return 'supersede'
    if any(_mentions_scope_change(part, family) for part in messages):
        return 'supersede'

    verdicts = [matchers.classify_confirmation(part) for part in messages]
    affirmative_parts = [
        _is_affirmation_emphasis(part, matchers)
        or _is_benign_acknowledgement(part, matchers)
        for part in messages
    ]
    if all(affirmative_parts) and any(
            _is_affirmation_emphasis(part, matchers) for part in messages):
        return 'affirmative'
    if 'negative' in verdicts:
        return 'negative'
    if 'defer' in verdicts:
        return 'defer'

    # A question or an unrelated message pauses the proposal while the planner
    # answers it. It must not re-send the same confirmation or escalate merely
    # because the customer is conversing before deciding.
    return 'context'


def _mentions_different_operation(text, pending_family):
    from . import matchers

    tokens = matchers.normalize(text).split()
    for family, stems in _FAMILY_STEMS.items():
        if family == pending_family:
            continue
        if any(token.startswith(stem) for token in tokens for stem in stems):
            return True
    return False


def _mentions_scope_change(text, family):
    from . import matchers

    normalized = matchers.normalize(text)
    tokens = set(normalized.split())
    if any(phrase in normalized for phrase in _SCOPE_CHANGE_PHRASES):
        return True
    if family not in ('schedule', 'reschedule'):
        return False
    if any(token.startswith(stem) for token in tokens
           for stem in _RESCHEDULE_CHANGE_STEMS):
        return True
    # "¿Abren el domingo?" no modifica una cita pendiente. En cambio,
    # "domingo" o "a las 12" sin forma interrogativa sí puede ser el dato
    # nuevo que sustituye la propuesta anterior.
    if '?' in text or '¿' in text:
        return False
    return bool(tokens & _SCHEDULE_PARAMETER_TOKENS) or bool(
        _TIME_OR_DATE.search(normalized)
    )


def _is_affirmation_emphasis(text, matchers):
    normalized = matchers.normalize(text)
    explicit_reaffirmation = (
        'que si' in normalized
        or 'es si' in normalized
        or 'te dije' in normalized
        or 'no entiendes' in normalized
    )
    if '?' in text and not explicit_reaffirmation:
        return False
    if text.strip() == '👍' or matchers.classify_confirmation(text) == 'affirmative':
        return True
    return explicit_reaffirmation and 'si' in normalized.split()


def _is_benign_acknowledgement(text, matchers):
    return matchers.normalize(text) in _BENIGN_ACKNOWLEDGEMENTS


def suspend_pending(conversation, *, reason_code, detail='', priority='normal'):
    """Suspende la intención y abre/retiene su hand-off — **en un solo commit**.

    Es el hallazgo Q de la revisión de plan, y el más peligroso del Item porque
    falla en silencio y destruye justo lo que existe para proteger: suspender
    con `clear_pending()` + `escalate_to_human()` son **dos** `save()`, y entre
    ellos caben una excepción, un reinicio del worker o una carrera. El
    resultado es una conversación sin pendiente y sin suspensión, con el 409 ya
    devuelto y el cliente esperando algo que nadie va a hacer.

    Bajo `select_for_update()` de `Conversation` y en una transacción:

    1. Re-lee `flow` **bajo el lock** (read-modify-write; nunca sobre una
       instancia vieja que otro turno ya invalidó).
    2. Copia el `pending_action` **íntegro** a `flow['suspended']` con
       `suspension_id`, `suspended_at` y `handoff_reason`. El staged no se
       reescribe ni se recorta — TC-SEC-03 sigue valiendo.
    3. Elimina `flow['pending_action']`.
    4. Crea **o retiene** el `HumanHandoff` abierto (no se abren dos casos por
       el mismo hecho).
    5. Deja `state = HANDOFF_PENDING`.

    Idempotente: llamarlo dos veces no duplica el caso ni pisa la suspensión ya
    escrita. Devuelve `(handoff, suspension)` — `suspension` es `None` si no
    había ninguna intención que preservar.

    **Es el único escritor legítimo de `flow['suspended']`.** Escribirlo a mano
    vuelve a abrir el hueco.
    """
    from django.db import transaction

    from .models import Conversation, HumanHandoff

    with transaction.atomic():
        convo = local_or_locked_conversation(conversation)

        handoff = open_handoff(convo)
        if handoff is None:
            handoff = create_local(HumanHandoff,
                organization=convo.organization,
                conversation=convo,
                reason_code=reason_code,
                reason_detail=detail[:200],
                priority=priority,
                notification_status='NOT_CONFIGURED',
            )

        flow = convo.flow
        pending = flow.get('pending_action')
        suspension = flow.get('suspended')
        if pending:
            suspension = {
                'suspension_id': uuid.uuid4().hex,
                'kind': 'pending_action',
                'state': pending,
                'suspended_at': timezone.now().isoformat(),
                'handoff_reason': reason_code,
            }
            flow['suspended'] = suspension
            flow.pop('pending_action', None)
        # El acuse al cliente que insiste se rearma con cada escalada nueva.
        flow.pop('handoff_ack_sent', None)

        if not convo.claimed_by_id and convo.state != Conversation.STATE_HUMAN_ACTIVE:
            convo.state = Conversation.STATE_HANDOFF_PENDING
        save_local(convo, update_fields=['state', 'flow'])

    # El caller sigue trabajando sobre su instancia: se sincroniza para que no
    # escriba encima con un `flow` anterior al lock.
    conversation.flow = convo.flow
    conversation.state = convo.state
    return handoff, suspension
