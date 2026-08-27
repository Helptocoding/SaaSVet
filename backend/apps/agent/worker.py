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
import os
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.channels.models import Message
from apps.channels.providers import ProviderError, get_provider

from . import goals
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

# Aislamiento de fallos del turno (É-F3 W0-3).
MAX_PROCESS_ATTEMPTS = 3               # tras esto, dead-letter + humano
TURN_RETRY_DELAY = timedelta(seconds=30)
PROCESSING_LEASE = timedelta(minutes=5)  # ventana de exclusividad del turno

TURN_FAILURE_TEXT = (
    "Perdón, tuve un problema técnico y no pude atenderte bien 🙏 Ya avisé al "
    "equipo para que te contacte."
)


def process_pending_conversations(batch=10, now=None):
    """Drena conversaciones con entrantes pendientes. Devuelve cuántas tocó.

    Con el agente encendido corre el pipeline completo (policy → planner →
    tools); sin provisionar cae al buzón F0 (saludo único por conversación).

    Dos garantías que antes no existían (É-F3 W0-3/W0-7):

    1. **Una transacción CORTA por conversación**, solo para reclamar el turno.
       Antes, un único `atomic()` envolvía el lote entero *incluyendo* las
       llamadas al LLM (hasta 30 s cada una) y el loopback HTTP: una clínica
       lenta bloqueaba las otras nueve y la conexión quedaba idle-in-transaction.
    2. **Un turno que revienta no tumba el worker.** Antes, cualquier excepción
       salía hasta el command, mataba el proceso, el rollback devolvía el
       mensaje a `pending` y al reiniciar se reprocesaba: crash-loop con todas
       las clínicas mudas y una llamada al LLM quemada por vuelta.
    """
    now = now or timezone.now()
    conv_ids = list(
        Message.objects.filter(
            direction=Message.DIRECTION_IN,
            status=Message.STATUS_PENDING,
            conversation__isnull=False,
        )
        .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
        .values_list('conversation_id', flat=True)
        .distinct()[:batch]
    )

    processed = 0
    for conv_id in conv_ids:
        claimed = _claim_turn(conv_id, now)
        if claimed is None:
            continue
        conversation, pending = claimed
        try:
            _run_turn(conversation, pending, now)
        except Exception as exc:
            _handle_turn_failure(conversation, pending, exc)
        else:
            _release_turn(conversation)
        processed += 1
    return processed


def _claim_turn(conv_id, now):
    """Reclama la conversación y sus entrantes elegibles. Transacción corta.

    Devuelve `(conversation, pending)` o None si otro worker la tiene, si el
    turno anterior sigue vivo (lease) o si ya no hay nada elegible. El lease
    sustituye al lock sostenido: serializa el turno entre réplicas sin mantener
    una transacción abierta mientras se espera al modelo.
    """
    with transaction.atomic():
        conversation = (
            Conversation.objects
            # of=('self',): lockear SOLO la conversación. Sin esto el lock se
            # extiende a organization/contact/channel_account y dos
            # conversaciones del mismo contacto se bloquean entre sí.
            .select_for_update(skip_locked=True, of=('self',))
            .select_related('organization', 'contact', 'channel_account')
            .filter(pk=conv_id)
            .first()
        )
        if conversation is None:
            return None                       # otra réplica la tiene tomada
        if conversation.processing_until and conversation.processing_until > now:
            return None                       # turno en vuelo en otra réplica

        org = conversation.organization
        pending = list(
            Message.objects.for_organization(org)
            .filter(
                conversation=conversation,
                direction=Message.DIRECTION_IN,
                status=Message.STATUS_PENDING,
            )
            .filter(Q(available_at__isnull=True) | Q(available_at__lte=now))
            .order_by('created_at', 'id')
        )
        if not pending:
            return None

        Message.objects.for_organization(org).filter(
            pk__in=[m.pk for m in pending],
        ).update(
            status=Message.STATUS_PROCESSED,
            process_attempts=F('process_attempts') + 1,
        )
        conversation.processing_until = now + PROCESSING_LEASE
        conversation.save(update_fields=['processing_until'])
    return conversation, pending


def _run_turn(conversation, pending, now):
    """Ejecuta el turno FUERA de toda transacción (red: LLM + loopback)."""
    org = conversation.organization
    agent_settings = AgentSettings.objects.filter(organization=org).first()

    # É-F1: con el agente encendido y provisionado, el turno pasa por el
    # pipeline completo (policy → planner → tools). Si NO está provisionado el
    # actor (agent_user), caemos al comportamiento F0 de buzón (auto-saludo
    # único) para no romper instalaciones a medio provisionar.
    if agent_settings and agent_settings.enabled and agent_settings.agent_user_id:
        from . import planner
        before_ids = set(
            Message.objects.for_organization(org)
            .filter(conversation=conversation,
                    direction=Message.DIRECTION_OUT)
            .values_list('pk', flat=True)
        )
        result = planner.handle_inbound(
            conversation, agent_settings=agent_settings,
            triggered_by=pending[-1],
            # La ráfaga COMPLETA va al Policy Engine: la urgencia puede venir
            # en cualquier mensaje del grupo, no solo en el último (W0-2).
            #
            # Viajan los OBJETOS, no los cuerpos (plan de continuidad, D24): sin
            # PK no hay procedencia de identidad que sellar, y `triggered_by`
            # solo apunta al último de la ráfaga. Antes iban dos listas
            # paralelas (`burst` y `payload_types`) que podían desalinearse;
            # ahora se derivan dentro, de la misma fuente.
            burst_messages=pending,
        )
        _discard_if_superseded(conversation, pending, before_ids, result)
        return

    _first_reply_fallback(conversation, agent_settings, now)


def _discard_if_superseded(conversation, pending, before_ids, result):
    """Descarta la respuesta si el cliente siguió escribiendo mientras el
    modelo pensaba (É-F3 W1-4). Devuelve cuántos salientes descartó.

    Solo aplica a respuestas de TEXTO PURO. Si el turno ejecutó una
    herramienta, propuso una confirmación o escaló, el mensaje sale igual:
    descartar la confirmación de una cita ya creada sería mucho peor que una
    respuesta ligeramente desfasada.
    """
    result = result or {}
    if result.get('decision') not in ('planner_reply', 'reply'):
        return 0
    if result.get('tools'):
        return 0

    org = conversation.organization
    superseded = Message.objects.for_organization(org).filter(
        conversation=conversation,
        direction=Message.DIRECTION_IN,
        status=Message.STATUS_PENDING,
        created_at__gt=pending[-1].created_at,
    ).exists()
    if not superseded:
        return 0

    discarded = (
        Message.objects.for_organization(org)
        .filter(conversation=conversation,
                direction=Message.DIRECTION_OUT,
                status=Message.STATUS_PENDING,
                author_type__in=[
                    Message.AUTHOR_AGENT,
                    Message.AUTHOR_SYSTEM,
                ])
        .exclude(pk__in=before_ids)
        .update(status=Message.STATUS_DISCARDED,
                failure_reason='descartado: el cliente siguió escribiendo')
    )
    if discarded:
        logger.info("AGENT_REPLY_SUPERSEDED", extra={
            "event": "AGENT_REPLY_SUPERSEDED",
            "organization_id": org.pk,
            "conversation_id": conversation.pk,
            "discarded": discarded,
        })
    return discarded


def _first_reply_fallback(conversation, agent_settings, now):
    """Buzón F0 (sin LLM): saludo/aviso una sola vez por conversación."""
    org = conversation.organization
    has_outbound = Message.objects.for_organization(org).filter(
        conversation=conversation, direction=Message.DIRECTION_OUT,
    ).exists()
    if has_outbound:
        return
    Message(
        organization=org,
        channel_account=conversation.channel_account,
        conversation=conversation,
        contact_id=conversation.contact_id,   # F2
        direction=Message.DIRECTION_OUT,
        author_type=Message.AUTHOR_SYSTEM,
        body=render_first_reply(agent_settings, org),
        status=Message.STATUS_PENDING,
    ).save()
    conversation.last_activity_at = now
    conversation.save(update_fields=['last_activity_at'])
    logger.info("AGENT_FIRST_REPLY_QUEUED", extra={
        "event": "AGENT_FIRST_REPLY_QUEUED",
        "organization_id": org.pk,
        "conversation_id": conversation.pk,
    })


def _release_turn(conversation):
    conversation.processing_until = None
    conversation.save(update_fields=['processing_until'])


def _exception_origin(exc):
    """Identificador seguro del último frame de una excepción."""
    trace = exc.__traceback__
    if trace is None:
        return ''
    while trace.tb_next is not None:
        trace = trace.tb_next
    code = trace.tb_frame.f_code
    return f'{os.path.basename(code.co_filename)}:{trace.tb_lineno}:{code.co_name}'


def _handle_turn_failure(conversation, pending, exc):
    """Turno fallido: reintentar con respiro, o dead-letter + humano.

    Trade-off consciente: si el turno murió DESPUÉS de encolar una respuesta,
    el reintento puede duplicarla. Está acotado a `MAX_PROCESS_ATTEMPTS` y es
    preferible al silencio — un cliente sin respuesta es peor que uno con dos.
    """
    logger.exception("AGENT_TURN_FAILED", extra={
        "event": "AGENT_TURN_FAILED",
        "organization_id": conversation.organization_id,
        "conversation_id": conversation.pk,
        "error_class": type(exc).__name__,
        "error_origin": _exception_origin(exc),
    })
    try:
        with transaction.atomic():
            org = conversation.organization
            rows = list(
                Message.objects.for_organization(org)
                .filter(pk__in=[m.pk for m in pending])
            )
            exhausted = [m for m in rows
                         if m.process_attempts >= MAX_PROCESS_ATTEMPTS]
            if exhausted:
                Message.objects.for_organization(org).filter(
                    pk__in=[m.pk for m in rows],
                ).update(
                    status=Message.STATUS_FAILED,
                    failure_reason=f'turn_failed:{type(exc).__name__}'[:200],
                    available_at=None,
                )
                _escalate_after_failure(conversation)
            else:
                Message.objects.for_organization(org).filter(
                    pk__in=[m.pk for m in rows],
                ).update(
                    status=Message.STATUS_PENDING,
                    available_at=timezone.now() + TURN_RETRY_DELAY,
                )
            conversation.processing_until = None
            conversation.save(update_fields=['processing_until'])
    except Exception:
        # El manejador de fallos jamás puede propagar: sería el crash-loop
        # que este bloque existe para evitar.
        logger.exception("AGENT_TURN_FAILURE_HANDLER_FAILED", extra={
            "event": "AGENT_TURN_FAILURE_HANDLER_FAILED",
            "conversation_id": conversation.pk,
        })


def _escalate_after_failure(conversation):
    from . import policy
    from .models import HumanHandoff
    from .outbound import enqueue_processing_failure_notice
    policy.escalate_to_human(
        conversation, reason_code=HumanHandoff.REASON_TOOL_FAILURE,
        detail='turn_failed',
    )
    enqueue_processing_failure_notice(conversation, TURN_FAILURE_TEXT)


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
