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
        convo = (Conversation.objects.select_for_update()
                 .get(pk=conversation.pk))

        handoff = HumanHandoff.objects.filter(
            conversation=convo, resolved_at__isnull=True,
        ).first()
        if handoff is None:
            handoff = HumanHandoff.objects.create(
                organization=convo.organization,
                conversation=convo,
                reason_code=reason_code,
                reason_detail=detail[:200],
                priority=priority,
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

        convo.state = Conversation.STATE_HANDOFF_PENDING
        convo.save(update_fields=['state', 'flow'])

    # El caller sigue trabajando sobre su instancia: se sincroniza para que no
    # escriba encima con un `flow` anterior al lock.
    conversation.flow = convo.flow
    conversation.state = convo.state
    return handoff, suspension
