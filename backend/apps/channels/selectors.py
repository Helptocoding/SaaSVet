"""
channels/selectors.py — Qué mensajes «existen» para quien lee la conversación.

Fuente ÚNICA del predicado de visibilidad (plan de continuidad, D11/D27). Antes
cada consumidor filtraba a mano y ninguno filtraba igual: `prompts` excluía los
salientes `discarded` pero **no** los `failed`, que son los que el proveedor
nunca entregó porque la ventana de 24 h ya estaba cerrada (`worker._send_one`).
El modelo veía como dichos mensajes que el cliente jamás recibió.

La distinción importa para algo más que el prompt: el anti-eco de identidad
decide si un dato lo reveló el sistema ANTES que el cliente, y un mensaje que
no salió no reveló nada. Un selector laxo ahí rechaza evidencia legítima.

Reglas de visibilidad en la bandeja:
  entrantes  → `pending` (la ráfaga de este turno) y `processed`
  salientes  → `sent`, `delivered`, `read`; también `pending` cuando lo
               escribió staff humano, para que su outbox aparezca de inmediato
  fuera      → `discarded` (nunca se envió), `failed` (el proveedor lo rechazó)
               y `pending` de agente/sistema (todavía no salieron)
"""
from django.db.models import Q

from .models import Message

# Salientes que el cliente PUDO ver. `pending` no está: aún no ha salido.
EMITTED_OUT_STATUSES = (
    Message.STATUS_SENT,
    Message.STATUS_DELIVERED,
    Message.STATUS_READ,
)
# Entrantes que cuentan como recibidos. `discarded` no está: es el mensaje de
# un contacto bloqueado, que el worker no procesa.
RECEIVED_IN_STATUSES = (
    Message.STATUS_PENDING,
    Message.STATUS_PROCESSED,
    Message.STATUS_FAILED,
)


def visible_messages(queryset):
    """Filtra un queryset de `Message` a lo visible en el chat de recepción."""
    return queryset.filter(
        Q(direction=Message.DIRECTION_IN, status__in=RECEIVED_IN_STATUSES)
        | Q(direction=Message.DIRECTION_OUT, status__in=EMITTED_OUT_STATUSES)
        | Q(
            direction=Message.DIRECTION_OUT,
            status=Message.STATUS_PENDING,
            author_type=Message.AUTHOR_HUMAN,
        )
    )


def emitted_outbound(queryset):
    """Solo los salientes que el cliente pudo ver (base del anti-eco)."""
    return queryset.filter(
        direction=Message.DIRECTION_OUT, status__in=EMITTED_OUT_STATUSES,
    )


def before_cursor(queryset, cursor):
    """Exclusive local order, independent of Message processing status."""
    if cursor is None:
        return queryset.none()  # legacy text-only inputs have no causal cursor
    if cursor.message_id is None:
        # A standalone read with no inbound has only a time boundary, no anchor.
        return queryset.filter(created_at__lt=cursor.created_at)
    return queryset.filter(
        Q(created_at__lt=cursor.created_at)
        | Q(created_at=cursor.created_at, pk__lt=cursor.message_id)
    )


def prior_messages(queryset, cursor):
    """Received inputs and emitted outputs strictly before a causal boundary.

    Inbox visibility (including unsent staff drafts) is not evidence of emission.
    Status controls eligibility; only the cursor determines what is previous.
    """
    return before_cursor(queryset, cursor).filter(
        Q(direction=Message.DIRECTION_IN, status__in=RECEIVED_IN_STATUSES)
        | Q(direction=Message.DIRECTION_OUT, status__in=EMITTED_OUT_STATUSES)
    )


def referenced_message(conversation, *, turn_context, event):
    """Exact channel reference within this episode, for inspection only.

    No semantic resolution, cross-episode expansion or authorization. Ambiguous,
    un-emitted, foreign and post-cursor references return None.
    """
    turn_context.assert_scope(conversation)
    if event not in turn_context.events or not event.reply_to_id:
        return None
    candidates = list(prior_messages(
        Message.objects.for_organization(turn_context.organization_id).filter(
            conversation_id=turn_context.conversation_id,
            contact_id=turn_context.contact_id,
            channel_account_id=turn_context.channel_account_id,
            external_message_id=event.reply_to_id,
        ), turn_context.history_before,
    )[:2])
    return candidates[0] if len(candidates) == 1 else None
