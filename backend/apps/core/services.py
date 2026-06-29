"""
apps/core/services.py — efectos externos del dominio core.

`send_support_report`: envía un reporte de soporte al webhook de Discord. Es el
único punto que arma el embed y hace el POST externo; la view solo valida input y
delega (boundary del proyecto: los efectos secundarios viven en services, las
views son delgadas). Los fallos se levantan como `APIException` para que el
`custom_exception_handler` arme el shape canónico `{code, message}` — sin
duplicar ese contrato en la view.
"""
import json
import logging

import requests
from django.conf import settings
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

# Límites de Discord (truncado defensivo → evita 502 espurios por payload inválido).
_SUPPORT_HTTP_TIMEOUT = 10          # s — cap del bloqueo síncrono del worker
_DISCORD_DESC_MAX = 4096            # embed.description
_DISCORD_FIELD_MAX = 1024           # embed field value


class SupportUnavailable(APIException):
    """503 — el canal de soporte no está configurado (sin webhook)."""
    status_code = 503
    default_detail = "El soporte no está disponible en este momento."
    default_code = "service_unavailable"


class SupportDeliveryFailed(APIException):
    """502 — Discord rechazó, no respondió a tiempo, o hubo error de red."""
    status_code = 502
    default_detail = "No se pudo enviar el reporte. Intenta más tarde."
    default_code = "service_error"


def send_support_report(*, user, message, image, page_url, timestamp):
    """
    Envía un reporte de soporte al webhook de Discord.

    El caller (view) ya validó el input (mensaje no vacío, imagen dentro de
    límites). Aquí vive el efecto externo: armado del embed + POST. Llamada
    SÍNCRONA (bloquea el worker hasta _SUPPORT_HTTP_TIMEOUT s) — aceptable al
    volumen del endpoint (throttle 10/h por usuario); si escala, mover a una cola
    asíncrona (el proyecto no tiene task queue hoy, trade-off consciente).

    Raises:
        SupportUnavailable: webhook no configurado (503).
        SupportDeliveryFailed: Discord rechazó / timeout / error de red (502).
    """
    webhook_url = getattr(settings, 'DISCORD_WEBHOOK_URL', '')
    if not webhook_url:
        logger.error("SUPPORT_WEBHOOK_NOT_CONFIGURED")
        raise SupportUnavailable()

    user_name = f"{user.first_name or ''} {user.last_name or ''} (@{user.username})".strip()
    org_name = getattr(user.organization, 'name', 'N/A') if user.organization else 'N/A'

    embed = {
        "title": "🚀 Nuevo reporte de problema",
        "description": (message or '').strip()[:_DISCORD_DESC_MAX],
        "color": 16711680,
        "fields": [
            {"name": "👤 Usuario", "value": user_name[:_DISCORD_FIELD_MAX], "inline": True},
            {"name": "🏢 Organización", "value": org_name[:_DISCORD_FIELD_MAX], "inline": True},
            {"name": "📍 Página", "value": (page_url or "N/A")[:_DISCORD_FIELD_MAX], "inline": False},
        ],
        "footer": {"text": "SaaSly — Intelligent Diagnostics"},
        "timestamp": timestamp or "",
    }
    if image:
        embed["image"] = {"url": f"attachment://{image.name}"}

    payload = {"embeds": [embed]}

    try:
        if image:
            image.seek(0)
            resp = requests.post(
                webhook_url,
                data={"payload_json": json.dumps(payload)},
                files={"file": (image.name, image.read(), image.content_type)},
                timeout=_SUPPORT_HTTP_TIMEOUT,
            )
        else:
            resp = requests.post(webhook_url, json=payload, timeout=_SUPPORT_HTTP_TIMEOUT)
    except requests.Timeout:
        logger.error("SUPPORT_WEBHOOK_TIMEOUT")
        raise SupportDeliveryFailed()
    except requests.RequestException as exc:
        logger.error("SUPPORT_WEBHOOK_ERROR", extra={"error": str(exc)[:200]})
        raise SupportDeliveryFailed()

    if 200 <= resp.status_code < 300:
        logger.info(
            "SUPPORT_MESSAGE_SENT",
            extra={"user_id": user.pk, "org_id": user.organization_id},
        )
        return

    logger.error(
        "SUPPORT_WEBHOOK_FAILED",
        extra={"status": resp.status_code, "body": resp.text[:500]},
    )
    raise SupportDeliveryFailed()
