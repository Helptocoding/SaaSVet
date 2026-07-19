"""
agent/confirmations.py — Flujo de confirmación tier-2 (É-F2 PR-16).

Toda mutación de agenda se PROPONE primero: la tool arma un `pending_action`
(tool + args YA resueltos a public_id + idempotency_key + expiración) y un
**parafraseo por PLANTILLA** (nunca generado por el LLM — spec §2.4, G5
fecha absoluta). El cliente confirma ("sí") → el planner ejecuta el
`pending_action` TAL CUAL fue parafraseado (invariante TC-SEC-03: la
afirmativa jamás amplía el alcance).

El `pending_action` vive en `Conversation.flow['pending_action']`.
"""
import uuid
from datetime import timedelta

from django.utils import timezone

PENDING_TTL = timedelta(minutes=30)  # spec §2.4

# Parafraseos LITERALES (una plantilla por acción). Fechas absolutas (G5).
CONFIRM_CREATE = (
    "Te confirmo: cita para *{pet}* el *{fecha}*, motivo: {reason}. "
    "¿Es correcto?"
)
CONFIRM_CANCEL = (
    "Voy a cancelar la cita de *{pet}* del *{fecha}*. ¿Confirmas?"
)
CONFIRM_RESCHEDULE = (
    "Muevo la cita de *{pet}* del *{vieja}* al *{nueva}*. ¿Confirmas?"
)
CONFIRM_CREATE_NEW_CLIENT = (
    "Te confirmo: te registro como cliente (*{owner}*) y agendo cita para "
    "*{pet}* ({especie}) el *{fecha}*, motivo: {reason}. ¿Es correcto?"
)

EXPIRED_REPARAPHRASE = "Pasó un rato — te confirmo de nuevo:\n{paraphrase}"


def stage_pending(conversation, *, tool, args, paraphrase):
    """Persiste el pending_action y devuelve el texto de confirmación.

    `args` ya trae public_ids resueltos + idempotency_key — NUNCA handles ni
    nada que el LLM re-genere en el turno de la confirmación."""
    conversation.flow['pending_action'] = {
        'tool': tool,
        'args': args,
        'paraphrase': paraphrase,
        'idempotency_key': args.get('idempotency_key') or uuid.uuid4().hex,
        'expires_at': (timezone.now() + PENDING_TTL).isoformat(),
    }
    conversation.save(update_fields=['flow'])
    return paraphrase


def get_pending(conversation):
    return conversation.flow.get('pending_action')


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
    if 'pending_action' in conversation.flow:
        conversation.flow.pop('pending_action', None)
        conversation.save(update_fields=['flow'])
