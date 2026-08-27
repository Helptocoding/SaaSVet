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
