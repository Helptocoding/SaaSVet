"""
agent/outbound.py — Encolar un saliente del agente (É-F1 PR-12).

Toda respuesta (plantilla o generada) se persiste como Message pendiente;
el sender (PR-5) la entrega con reintentos y ventana de 24h. Nunca se llama
al proveedor desde el planner.
"""
from django.utils import timezone

from apps.channels.models import Message


def enqueue_outbound(conversation, body, *, author='agent'):
    """Crea un Message saliente pendiente. `author`: 'agent' | 'system'."""
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
