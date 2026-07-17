"""
channels/providers.py — Adaptador del proveedor de WhatsApp (É-F0 PR-5).

Interfaz mínima para enviar texto libre. El worker y el sender hablan con
esta interfaz, nunca con `requests` directo — cambiar de proveedor (Q1:
Meta Cloud API directa hoy) es cambiar el adaptador.

Credenciales: `ChannelAccount.provider_credentials_ref` guarda el NOMBRE de
la env var con el access token (default WHATSAPP_ACCESS_TOKEN); el secreto
vive en el entorno (.env.prod), jamás en DB ni en logs.
"""
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger('agent.events')

# Versionada para poder subirla por env sin release (Meta depreca versiones).
DEFAULT_API_BASE = 'https://graph.facebook.com/v20.0'


class ProviderError(Exception):
    """Fallo al enviar. `retryable` decide si el sender re-intenta con
    backoff (5xx/timeout/429) o marca failed directo (4xx de contrato)."""

    def __init__(self, message, retryable):
        super().__init__(message)
        self.retryable = retryable


class MetaWhatsAppProvider:
    """Meta Cloud API — envío de texto de sesión (ventana 24 h).

    Las plantillas HSM (fuera de ventana) llegan en F3; este adaptador
    F0/F1 solo envía `type=text`.
    """

    def __init__(self, channel_account):
        self.channel_account = channel_account

    def _access_token(self):
        ref = self.channel_account.provider_credentials_ref
        token = os.environ.get(ref, '') or getattr(settings, ref, '')
        if not token:
            raise ProviderError(
                f"access token no configurado (env {ref})", retryable=False,
            )
        return token

    def send_text(self, to_wa_id, body):
        """Envía texto; devuelve el wamid asignado por el proveedor."""
        base = getattr(settings, 'WHATSAPP_API_BASE_URL', DEFAULT_API_BASE)
        url = f"{base}/{self.channel_account.external_account_id}/messages"
        try:
            response = requests.post(
                url,
                headers={'Authorization': f'Bearer {self._access_token()}'},
                json={
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': to_wa_id,
                    'type': 'text',
                    'text': {'body': body},
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"red: {exc.__class__.__name__}", retryable=True)

        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError(
                f"proveedor {response.status_code}", retryable=True,
            )
        if response.status_code >= 400:
            # 4xx de contrato (token inválido, destinatario mal formado,
            # ventana cerrada…): reintentar no lo arregla.
            raise ProviderError(
                f"proveedor {response.status_code}", retryable=False,
            )

        try:
            data = response.json()
            return data['messages'][0]['id']
        except (ValueError, KeyError, IndexError):
            # Envió (2xx) pero sin wamid parseable: no reintentar (riesgo de
            # duplicar el mensaje al cliente); el acuse llegará por webhook.
            logger.warning("PROVIDER_RESPONSE_UNPARSEABLE", extra={
                "event": "PROVIDER_RESPONSE_UNPARSEABLE",
                "status_code": response.status_code,
            })
            return ''


def get_provider(channel_account):
    """Factory por tipo de canal. Hoy solo WhatsApp (Meta directa, Q1)."""
    return MetaWhatsAppProvider(channel_account)
