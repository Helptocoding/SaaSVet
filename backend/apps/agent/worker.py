"""
agent/worker.py — Lógica del worker (É-F0 PR-5): inbox-como-cola + sender.

Diseño v1.1 §7-C4: NO hay tabla de cola. El worker toma CONVERSACIONES con
mensajes entrantes pendientes vía FOR UPDATE SKIP LOCKED — lockear la
conversación serializa sus mensajes (FIFO por conversación) y paraleliza
entre conversaciones/réplicas del worker gratis. Drain-on-pickup (§7-C9):
al tomar una conversación se procesan TODOS sus pendientes elegibles
(available_at vencido) en un solo turno.

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
from django.db.models import Q, Subquery
from django.utils import timezone

from apps.channels.models import Message
from apps.channels.providers import ProviderError, get_provider

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
    """Drena conversaciones con entrantes pendientes. Devuelve cuántas tocó.

    F0 (buzón): marca los entrantes como procesados y, si la conversación
    aún no tiene NINGÚN saliente, encola la primera respuesta automática
    (T0-GREET / T0-DISABLED / fuera-de-horario). Los mensajes siguientes
    los atiende un humano desde la bandeja (PR-6/7). El planner LLM
    sustituirá esta rama en É-F1.
    """
    now = now or timezone.now()
    processed = 0

    pending_conv_ids = Message.objects.filter(
        direction=Message.DIRECTION_IN,
        status=Message.STATUS_PENDING,
        available_at__lte=now,
        conversation__isnull=False,
    ).values('conversation_id')

    with transaction.atomic():
        conversations = list(
            Conversation.objects
            .select_for_update(skip_locked=True)
            .filter(pk__in=Subquery(pending_conv_ids))
            [:batch]
        )
        for conversation in conversations:
            _process_one(conversation, now)
            processed += 1
    return processed


def _process_one(conversation, now):
    org = conversation.organization
    pending = list(
        Message.objects.for_organization(org).filter(
            conversation=conversation,
            direction=Message.DIRECTION_IN,
            status=Message.STATUS_PENDING,
            available_at__lte=now,
        ).order_by('created_at', 'id')
    )
    if not pending:
        return

    Message.objects.for_organization(org).filter(
        pk__in=[m.pk for m in pending],
    ).update(status=Message.STATUS_PROCESSED)

    agent_settings = AgentSettings.objects.filter(organization=org).first()
    triggered_by = pending[-1]

    # É-F1: con el agente encendido y provisionado, cada entrante pasa por el
    # pipeline completo (policy → planner → tools). Si NO está provisionado el
    # actor (agent_user), caemos al comportamiento F0 de buzón (auto-saludo
    # único) para no romper instalaciones a medio provisionar.
    if agent_settings and agent_settings.enabled and agent_settings.agent_user_id:
        from . import planner
        planner.handle_inbound(
            conversation, agent_settings=agent_settings,
            triggered_by=triggered_by,
        )
        return

    # F0 fallback (buzón sin LLM): saludo/aviso una sola vez por conversación.
    has_outbound = Message.objects.for_organization(org).filter(
        conversation=conversation, direction=Message.DIRECTION_OUT,
    ).exists()
    if has_outbound:
        return
    body = render_first_reply(agent_settings, org)
    Message(
        organization=org,
        channel_account=conversation.channel_account,
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        author_type=Message.AUTHOR_SYSTEM,
        body=body,
        status=Message.STATUS_PENDING,
    ).save()
    conversation.last_activity_at = now
    conversation.save(update_fields=['last_activity_at'])
    logger.info("AGENT_FIRST_REPLY_QUEUED", extra={
        "event": "AGENT_FIRST_REPLY_QUEUED",
        "organization_id": org.pk,
        "conversation_id": conversation.pk,
    })


def send_pending_outbound(batch=20, provider_factory=get_provider, now=None):
    """Entrega salientes pendientes con reintentos. Devuelve cuántos intentó.

    Multi-réplica-safe: lock por mensaje con SKIP LOCKED. El envío HTTP
    ocurre DENTRO del lock del mensaje (si el proceso muere a mitad, el
    mensaje queda pending y otro worker lo retoma — el proveedor dedupea
    razonablemente poco, por eso attempts se persiste ANTES de enviar:
    a lo sumo un reintento manual, nunca un bucle).
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
        provider = provider_factory(message.channel_account)
        wamid = provider.send_text(
            conversation.contact.external_id, message.body,
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
