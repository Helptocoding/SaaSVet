"""
agent/outbound.py — Encolar un saliente del agente (É-F1 PR-12).

Toda respuesta (plantilla o generada) se persiste como Message pendiente;
el sender (PR-5) la entrega con reintentos y ventana de 24h. Nunca se llama
al proveedor desde el planner.
"""
from django.utils import timezone

from apps.channels.models import Message


def enqueue_outbound(conversation, body, *, author='system'):
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
    author_type = (
        Message.AUTHOR_AGENT if author == 'agent' else Message.AUTHOR_SYSTEM
    )
    message = Message(
        organization=conversation.organization,
        channel_account=conversation.channel_account,
        conversation=conversation,
        direction=Message.DIRECTION_OUT,
        author_type=author_type,
        body=body,
        status=Message.STATUS_PENDING,
    )
    message.save()
    conversation.last_activity_at = timezone.now()
    conversation.save(update_fields=['last_activity_at'])
    return message
