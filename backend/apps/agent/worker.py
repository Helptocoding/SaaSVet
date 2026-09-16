"""
agent/worker.py — B3 TurnWork durable + sender compatible.

Un claim corto fija miembros/cursor y concede un único lease de TurnWork.
El planner prepara cambios en memoria; la transacción final verifica el
witness y publica junto con completion. El polling recupera trabajo expirado.
El sender conserva su transporte actual; incertidumbre HTTP corresponde a B4.

Este módulo es deliberadamente importable y puro-de-side-effects-globales
(el loop vive en el management command): cada función procesa un lote y
regresa cuánto hizo — testeable sin proceso.

Nota de tenancy: la cola es GLOBAL entre orgs por diseño (un worker sirve a
todas las clínicas); cada conversación ya trae su organización fijada desde
el webhook (R1) y todo lo que se escribe hereda ese contexto.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.channels.models import Message
from apps.channels.providers import ProviderError, get_provider

from .durable import MAX_ATTEMPTS as MAX_PROCESS_ATTEMPTS
from .durable import RETRY_DELAY as TURN_RETRY_DELAY
from .durable import LEASE as PROCESSING_LEASE
from .models import AgentSettings, Conversation
from .tier0 import render_first_reply

logger = logging.getLogger('agent.events')

# Reintentos del sender: backoff exponencial 30s·2^n, cap 1h, máx 5 intentos.
SEND_MAX_ATTEMPTS = 5
SEND_BACKOFF_BASE = timedelta(seconds=30)
SEND_BACKOFF_CAP = timedelta(hours=1)

# Ventana de sesión de WhatsApp: fuera de 24 h del último entrante solo
# caben plantillas HSM (F3) — en F0/F1 el texto libre se marca failed.
SESSION_WINDOW = timedelta(hours=24)

def process_pending_conversations(batch=10, now=None):
    """Poll durable retries/recovery and unassigned inbound using existing loop."""
    from django.db.models.functions import Now
    from .models import TurnWork
    from . import durable
    due = (Q(turn_works__status=TurnWork.PROCESSING,
             turn_works__lease_expires_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING,
             turn_works__next_attempt_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING,
             turn_works__next_attempt_at__isnull=True))
    incoming = Message.objects.filter(direction='in', status='pending',
        turn_work__isnull=True).filter(Q(available_at__isnull=True) |
        Q(available_at__lte=now or Now())).values('conversation_id')
    conv_ids = list(Conversation.objects.filter(due | Q(pk__in=incoming))
                    .order_by('last_activity_at', 'pk').values_list('pk', flat=True)
                    .distinct()[:batch])
    processed = 0
    for conv_id in conv_ids:
        witness = _claim_turn(conv_id, now)
        if witness is None:
            continue
        try:
            _run_turn(witness)
        except durable.OwnershipLost:
            pass  # Durable state belongs to the newer owner; never release it.
        except Exception as exc:
            _handle_turn_failure(witness, exc)
        processed += 1
    return processed


def _claim_turn(conv_id, now=None):
    from .durable import claim_turn
    return claim_turn(conv_id, eligible_at=now)


def _run_turn(witness):
    """Plan in memory, then publish under a fresh witness/CAS in one commit."""
    from . import durable, planner
    from .turn_changes import TurnChanges
    conversation = Conversation.objects.select_related(
        'organization', 'contact', 'channel_account').get(
            pk=witness.conversation_id, organization_id=witness.organization_id)
    turn_context = durable.context_for_work(witness)
    agent_settings = AgentSettings.objects.filter(
        organization_id=witness.organization_id).first()
    changes = TurnChanges(witness, conversation)
    with changes.activate():
        if agent_settings and agent_settings.enabled and agent_settings.agent_user_id:
            result = planner.handle_inbound(conversation, agent_settings=agent_settings,
                                            turn_context=turn_context)
        else:
            _first_reply_fallback(conversation, agent_settings, turn_context.clinic_now)
            result = {'decision': 'fallback'}
    outcome = durable.finalize_turn(witness, outputs=changes.outputs, changes=changes,
                                   outcome=result.get('decision', 'completed'))
    # Existing optional handoff alert stays outside the local transaction.
    # It is not a durable B5 notification or proof that a human was notified.
    for callback in changes.callbacks:
        try:
            callback()
        except Exception:
            logger.exception('AGENT_POST_TURN_CALLBACK_FAILED')
    return outcome




def _first_reply_fallback(conversation, agent_settings, now):
    from .outbound import enqueue_outbound
    if conversation.claimed_by_id or conversation.state in (
            Conversation.STATE_HUMAN_ACTIVE, Conversation.STATE_CLOSED):
        return
    if Message.objects.for_organization(conversation.organization_id).filter(
            conversation=conversation, direction='out').exists():
        return
    enqueue_outbound(conversation, render_first_reply(agent_settings, conversation.organization))




def _handle_turn_failure(witness, exc):
    from .durable import fail_turn, OwnershipLost
    logger.error('AGENT_TURN_EXCEPTION', extra={
        'event': 'AGENT_TURN_EXCEPTION', 'turn_work_id': witness.turn_work_id,
        'conversation_id': witness.conversation_id, 'error_class': type(exc).__name__})
    try:
        fail_turn(witness, reason=('turn_' + type(exc).__name__)[:64])
    except OwnershipLost:
        pass
    except Exception:
        logger.exception('AGENT_TURN_FAILURE_HANDLER_FAILED')
        # Keep PROCESSING durable; a later poll recovers its expired lease.


def _escalate_after_failure(conversation, *, work=None):
    """Existing terminal fallback, in the same local commit as FAILED."""
    from . import policy, tier0
    from .models import HumanHandoff
    from .outbound import enqueue_processing_failure_notice
    policy.escalate_to_human(conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
                            detail='turn_failed')
    enqueue_processing_failure_notice(conversation, tier0.T0_TECH_PROBLEM, work=work)




def send_pending_outbound(batch=20, provider_factory=get_provider, now=None):
    """Entrega salientes pendientes con reintentos. Devuelve cuántos intentó.

    Transporte legacy: SKIP LOCKED por mensaje y HTTP dentro del lote atómico.
    La comprobación B3 rechaza epochs obsoletos antes de admitir el envío.
    Un crash puede dejar incertidumbre remota y permitir reenvío: resolver
    esa frontera requiere B4; B3 no promete entrega exactamente una vez.
    """
    now = now or timezone.now()
    attempted = 0

    with transaction.atomic():
        messages = list(
            Message.objects
            # of=('self',): lockear SOLO la fila del mensaje — conversation es
            # FK nullable → outer join, y Postgres no permite FOR UPDATE en el
            # lado nullable. Los padres no necesitan lock (solo se leen).
            .select_for_update(skip_locked=True, of=('self',))
            .select_related('conversation', 'channel_account',
                            'conversation__contact', 'organization')
            .filter(direction=Message.DIRECTION_OUT,
                    status=Message.STATUS_PENDING)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            [:batch]
        )
        for message in messages:
            _send_one(message, provider_factory, now)
            attempted += 1
    return attempted


def _send_one(message, provider_factory, now):
    reason = _dispatch_rejection(message)
    if reason:
        message.status = Message.STATUS_DISCARDED
        message.failure_reason = reason
        message.save(update_fields=['status', 'failure_reason'])
        logger.info('AGENT_SEND_DISCARDED', extra={
            'event': 'AGENT_SEND_DISCARDED', 'message_id': message.pk,
            'outcome_code': reason})
        return
    conversation = message.conversation

    # Ventana de 24 h (la valida el sender, no el LLM — spec §2.8).
    last_in = conversation.last_inbound_at if conversation else None
    if last_in is None or (now - last_in) > SESSION_WINDOW:
        message.status = Message.STATUS_FAILED
        message.failure_reason = 'ventana de sesión de 24h cerrada'
        message.save(update_fields=['status', 'failure_reason'])
        logger.warning("AGENT_SEND_WINDOW_CLOSED", extra={
            "event": "AGENT_SEND_WINDOW_CLOSED",
            "message_id": message.pk,
        })
        return

    # attempts se persiste ANTES del HTTP: si morimos post-envío pre-commit,
    # el rollback regresa el attempt también — pero el SKIP LOCKED garantiza
    # que nadie más lo estaba enviando en paralelo.
    message.attempts += 1

    try:
        from .services import wa_id_to_sendable
        provider = provider_factory(message.channel_account)
        wamid = provider.send_text(
            # El wa_id entrante trae el '1' legacy de México (521...); Meta
            # exige el formato sin él para enviar (52...). Ver wa_id_to_sendable.
            wa_id_to_sendable(conversation.contact.external_id), message.body,
        )
    except ProviderError as exc:
        if exc.retryable and message.attempts < SEND_MAX_ATTEMPTS:
            backoff = min(
                SEND_BACKOFF_BASE * (2 ** (message.attempts - 1)),
                SEND_BACKOFF_CAP,
            )
            message.next_attempt_at = now + backoff
            message.save(update_fields=['attempts', 'next_attempt_at'])
        else:
            message.status = Message.STATUS_FAILED
            message.failure_reason = str(exc)[:200]
            message.save(update_fields=['status', 'failure_reason', 'attempts'])
            logger.error("AGENT_SEND_FAILED", extra={
                "event": "AGENT_SEND_FAILED",
                "message_id": message.pk,
                "attempts": message.attempts,
                "retryable": exc.retryable,
            })
        return

    message.status = Message.STATUS_SENT
    message.external_message_id = wamid or None
    message.save(update_fields=['status', 'external_message_id', 'attempts'])

    # El sellado de la pregunta del reto se RETIRÓ (ADR p59). Servía para
    # derivar el régimen probatorio, y con uno solo no hay nada que decidir.
    #
    # Se gana algo aparte de código menos: era el único write que corría DESPUÉS
    # de que el proveedor aceptara el mensaje, dentro de la misma transacción que
    # guarda `STATUS_SENT`. Necesitaba un `try/except` propio precisamente porque
    # un `raise` ahí habría hecho rollback de un WhatsApp ya entregado y el
    # sender lo habría reenviado.


def _dispatch_rejection(message):
    """B3 selection fence, immediately before admitting existing sender HTTP.

    No durable send claim and no cancellation of a remote request already
    admitted. That race/uncertainty remains B4, including legacy retries.
    """
    from .models import TurnWork
    if message.origin_epoch is None:
        return 'legacy_unverified'
    conv = Conversation.objects.filter(pk=message.conversation_id,
        organization_id=message.organization_id,
        channel_account_id=message.channel_account_id,
        channel_account__organization_id=message.organization_id,
        contact__organization_id=message.organization_id).first()
    if conv is None:
        return 'scope_invalid'
    if message.contact_id not in (None, conv.contact_id):
        return 'scope_invalid'
    if message.origin_epoch != conv.ownership_epoch:
        return 'ownership_invalidated'
    if message.turn_work_id is not None and not TurnWork.objects.filter(
            pk=message.turn_work_id, organization_id=message.organization_id,
            conversation_id=conv.pk, ownership_epoch=message.origin_epoch,
            ).filter(Q(status=TurnWork.COMPLETED) |
                     Q(status=TurnWork.FAILED, messages__pk=message.pk,
                       messages__semantic_type=Message.SEMANTIC_PROCESSING_FAILURE)).exists():
        return 'turn_work_invalid'
    message.conversation = conv
    return ''
