"""
agent/alerts.py — Aviso operativo de escaladas urgentes (É-F3 W0-4).

Una urgencia clínica detectada (INT-01) creaba un `HumanHandoff` y ahí moría:
la bandeja `/inbox` no notifica y puede estar cerrada. Este módulo empuja el
aviso al canal de ops que el proyecto ya usa (webhook Discord, mismo patrón
que `core/services.py::send_support_report`).

Dos reglas duras:
- **Jamás levanta.** Un fallo del webhook no puede tumbar el turno del cliente
  ni el worker: el aviso es telemetría, la respuesta al cliente es el producto.
- **Jamás lleva PII.** Solo organización, id de conversación y motivo. Los
  cuerpos de mensaje viven únicamente en la DB (regla R15).
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger('agent.events')

_TIMEOUT = 5


def notify_urgent_handoff(conversation, *, reason_code, detail=''):
    """Avisa a ops que hay una escalada urgente esperando. Devuelve si se envió."""
    url = getattr(settings, 'DISCORD_WEBHOOK_URL', '')
    org = conversation.organization
    if not url:
        # Sin webhook configurado el evento igual queda en el log estructurado:
        # el aviso se degrada, no desaparece.
        logger.error("AGENT_URGENT_HANDOFF", extra={
            "event": "AGENT_URGENT_HANDOFF",
            "organization_id": org.pk,
            "conversation_id": conversation.pk,
            "reason_code": reason_code,
            "alert_delivered": False,
        })
        return False

    payload = {"embeds": [{
        "title": "🚨 Urgencia en WhatsApp — requiere atención humana",
        "color": 0xE53935,
        "fields": [
            {"name": "Clínica", "value": org.name[:100], "inline": True},
            {"name": "Motivo", "value": reason_code, "inline": True},
            {"name": "Conversación", "value": str(conversation.public_id),
             "inline": False},
        ],
        "footer": {"text": "Ábrela en /inbox — el agente ya está en pausa"},
    }]}
    if detail:
        payload["embeds"][0]["fields"].append(
            {"name": "Detalle", "value": detail[:200], "inline": False})

    try:
        response = requests.post(url, json=payload, timeout=_TIMEOUT)
        delivered = 200 <= response.status_code < 300
    except requests.RequestException:
        delivered = False

    logger.error("AGENT_URGENT_HANDOFF", extra={
        "event": "AGENT_URGENT_HANDOFF",
        "organization_id": org.pk,
        "conversation_id": conversation.pk,
        "reason_code": reason_code,
        "alert_delivered": delivered,
    })
    return delivered
