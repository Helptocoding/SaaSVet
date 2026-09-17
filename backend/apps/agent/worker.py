"""
agent/worker.py — B3 TurnWork durable + sender compatible.

Un claim corto fija miembros/cursor y concede un único lease de TurnWork.
El planner prepara cambios en memoria; la transacción final verifica el
witness y publica junto con completion. El polling recupera trabajo expirado.
El sender B4 vive en sender.py: claim/admisión/evidencia externa separados.

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
from .sender import (send_pending_outbound, SEND_MAX_ATTEMPTS,
                     SEND_BACKOFF_BASE, SEND_BACKOFF_CAP, SESSION_WINDOW)

from .durable import MAX_ATTEMPTS as MAX_PROCESS_ATTEMPTS
from .durable import RETRY_DELAY as TURN_RETRY_DELAY
from .durable import LEASE as PROCESSING_LEASE
from .models import AgentSettings, Conversation
from .tier0 import render_first_reply

logger = logging.getLogger('agent.events')

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
    from . import safety, safety_handoff
    if safety_handoff.automation_enabled():
        assessment = safety.assess_context(conversation, turn_context)
        if assessment.classification != safety.NO_SIGNAL:
            return safety_handoff.finalize_safety(witness, assessment)
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
    # Callbacks cannot provide evidence of notification or human attention.
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




def _dispatch_rejection(message):
    """Compatibility diagnostic. The B4 admission revalidates under locks."""
    from .sender import _rejection
    conv = Conversation.objects.select_related('contact', 'channel_account').filter(
        pk=message.conversation_id, organization_id=message.organization_id).first()
    return _rejection(message, conv)
