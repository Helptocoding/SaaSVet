"""
agent/outbound.py — Encolar un saliente del agente (É-F1 PR-12).

Toda respuesta (plantilla o generada) se persiste como Message pendiente;
el sender (PR-5) la entrega con reintentos y ventana de 24h. Nunca se llama
al proveedor desde el planner.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.channels.models import Message

logger = logging.getLogger('agent.events')


def enqueue_outbound(conversation, body, *, author='system', semantic_type='',
                     operation_key=''):
    """Crea un Message saliente pendiente. `author`: 'agent' | 'system'.

    **El default es `'system'` a propósito** (É-F4 Fase 2 §2.1, R11): hay que
    OPTAR por afirmar que el texto es voz propia del agente. La regla:

      `agent`  → el texto lo produjo el modelo en este turno (o lo propuso él
                 vía su llamada a herramienta, caso del parafraseo tier-2).
      `system` → plantilla tier-0 o texto fijo del router/planner. El modelo
                 no lo redactó y no debe responder por su redacción.

    Antes TODO salía como `agent`, así que en el historial el modelo veía como
    suyas plantillas que escribió el router — y se disculpaba por ellas
    (auditoría de rigidez 2026-07-29, conv 13 / CR-6). `assemble_messages` es
    quien consume esta distinción.
    """
    if semantic_type == Message.SEMANTIC_OPERATION_RECEIPT:
        if not operation_key:
            raise ValueError('operation receipt requires operation_key')
        return _enqueue_operation_receipt(
            conversation, body, author=author, operation_key=operation_key)

    _warn_if_repeated(conversation, body)
    author_type = (
        Message.AUTHOR_AGENT if author == 'agent' else Message.AUTHOR_SYSTEM
    )
    message = Message(
        organization=conversation.organization,
        channel_account=conversation.channel_account,
        conversation=conversation,
        contact_id=conversation.contact_id,   # F2 · el mensaje es de la PERSONA
        direction=Message.DIRECTION_OUT,
        author_type=author_type,
        semantic_type=semantic_type,
        operation_key=operation_key,
        body=body,
        status=Message.STATUS_PENDING,
    )
    message.save()
    conversation.last_activity_at = timezone.now()
    conversation.save(update_fields=['last_activity_at'])
    return message


def _enqueue_operation_receipt(conversation, body, *, author, operation_key):
    """Outbox idempotente para el recibo de un commit.

    El commit puede reintentarse por una caída entre el dominio y el sender;
    repetirle al cliente "cita creada" no es inocuo. La unicidad vive en la
    base y no en una comparación del texto, que puede cambiar de copy.
    """
    existing = Message.objects.filter(
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
        operation_key=operation_key,
    ).first()
    if existing is not None:
        return existing

    author_type = (
        Message.AUTHOR_AGENT if author == 'agent' else Message.AUTHOR_SYSTEM
    )
    try:
        with transaction.atomic():
            message = Message.objects.create(
                organization=conversation.organization,
                channel_account=conversation.channel_account,
                conversation=conversation,
                contact_id=conversation.contact_id,
                direction=Message.DIRECTION_OUT,
                author_type=author_type,
                semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
                operation_key=operation_key,
                body=body,
                status=Message.STATUS_PENDING,
            )
    except IntegrityError:
        # Otra ejecución ganó la carrera: devuelve el recibo existente sin
        # crear ni enviar una segunda notificación.
        return Message.objects.get(
            conversation=conversation,
            direction=Message.DIRECTION_OUT,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key=operation_key,
        )

    conversation.last_activity_at = timezone.now()
    conversation.save(update_fields=['last_activity_at'])
    return message

def _warn_if_repeated(conversation, body):
    """C7 · el sistema repitiéndose, mire quien mire (É-F5 Fase 3).

    Hasta aquí los guards de conducta solo miraban el texto del MODELO
    (`planner` → `guards.check_behaviour`). Se vigilaba al sospechoso
    equivocado: en la conversación que abrió É-F5, quien repitió la misma
    plantilla tres veces carácter por carácter fue el ROUTER, y ningún
    contador subió, ningún guard disparó y `tasa_repregunta` lo registró
    como 0.00.

    Aquí no se bloquea nada, y es deliberado: un saliente repetido es un
    defecto del SISTEMA que hay que ver, no un texto peligroso que haya que
    detener — retenerlo dejaría al cliente sin respuesta, que es peor. Se
    detecta y se registra para que aparezca en incidentes, no solo en el
    informe semanal (`metrics.salientes_repetidos`).

    Sin el cuerpo del mensaje en el log (PII, regla R15).
    """
    previous = (
        Message.objects.filter(
            conversation=conversation, direction=Message.DIRECTION_OUT,
        ).exclude(status=Message.STATUS_DISCARDED)
        .order_by('-id').values_list('body', flat=True).first()
    )
    if previous is None or (previous or '').strip() != (body or '').strip():
        return
    logger.warning("AGENT_OUTPUT_GUARD", extra={
        "event": "AGENT_OUTPUT_GUARD",
        "organization_id": conversation.organization_id,
        "conversation_id": conversation.pk,
        "violations": "repeated_outbound",
        "action": "sent",
    })
