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
import re
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger('agent.events')

# Versionada para poder subirla por env sin release (Meta depreca versiones).
DEFAULT_API_BASE = 'https://graph.facebook.com/v20.0'


class ProviderError(Exception):
    """Legacy exception; retryable alone NEVER proves non-acceptance."""

    def __init__(self, message, retryable):
        super().__init__(message)
        self.retryable = retryable


def valid_provider_id(value):
    return (isinstance(value, str) and 6 < len(value) <= 128
            and re.fullmatch(r'wamid\.[A-Za-z0-9_+/=.\-]+', value) is not None)


@dataclass(frozen=True)
class SendResult:
    """Evidence from one external attempt; unrelated to business ToolOutcome."""
    kind: str  # accepted | known_rejected | uncertain
    provider_id: str = ''
    code: str = ''
    retryable: bool = False


class MetaWhatsAppProvider:
    """Meta Cloud API — envío de texto de sesión (ventana 24 h).

    Las plantillas HSM (fuera de ventana) llegan en F3; este adaptador
    F0/F1 solo envía `type=text`.
    """

    def __init__(self, channel_account):
        self.channel_account = channel_account

    def _access_token(self):
        # 1) Token cifrado en DB (rotable desde la UI, sin restart).
        db_token = self.channel_account.get_access_token()
        if db_token:
            return db_token
        # 2) Fallback: env var nombrada por provider_credentials_ref (.env.prod).
        ref = self.channel_account.provider_credentials_ref
        token = os.environ.get(ref, '') or getattr(settings, ref, '')
        if not token:
            raise ProviderError(
                f"access token no configurado (ni en DB ni env {ref})",
                retryable=False,
            )
        return token

    def send_text(self, to_wa_id, body, *, reply_to_id=None):
        """No network retries. 5xx/network/invalid 2xx remain uncertain."""
        if reply_to_id is not None and not valid_provider_id(reply_to_id):
            return SendResult('known_rejected', code='invalid_reply_id')
        base = getattr(settings, 'WHATSAPP_API_BASE_URL', DEFAULT_API_BASE)
        url = f"{base}/{self.channel_account.external_account_id}/messages"
        try:
            token = self._access_token()
        except ProviderError:
            return SendResult('known_rejected', code='credentials_missing')
        try:
            response = requests.post(
                url,
                headers={'Authorization': f'Bearer {token}'},
                json={
                    'messaging_product': 'whatsapp',
                    'recipient_type': 'individual',
                    'to': to_wa_id,
                    'type': 'text',
                    'text': {'body': body},
                    **({'context': {'message_id': reply_to_id}} if reply_to_id else {}),
                },
                timeout=15,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            return SendResult('uncertain', code=f'transport_{exc.__class__.__name__}')
        try:
            data = response.json()
        except ValueError:
            return SendResult('uncertain', code='invalid_json')
        if not isinstance(data, dict):
            return SendResult('uncertain', code='invalid_shape')
        if 200 <= response.status_code < 300:
            messages = data.get('messages')
            if (isinstance(messages, list) and len(messages) == 1
                    and isinstance(messages[0], dict)
                    and valid_provider_id(messages[0].get('id'))
                    and 'error' not in data
                    and data.get('messaging_product', 'whatsapp') == 'whatsapp'):
                return SendResult('accepted', provider_id=messages[0]['id'])
            return SendResult('uncertain', code='acceptance_id_missing')
        error = data.get('error')
        code = error.get('code') if isinstance(error, dict) else None
        # Only explicit pre-acceptance contract/auth/rate-limit errors in 4xx.
        # An error envelope in a 5xx is deliberately NOT sufficient evidence.
        if (400 <= response.status_code < 500 and response.status_code != 408
                and type(code) is int and code in (10, 100, 190, 200, 130429, 131047)
                and not data.get('messages')):
            return SendResult('known_rejected', code=f'meta_{code}',
                              retryable=code == 130429)
        return SendResult('uncertain', code=f'http_{response.status_code}_unclassified')


def get_provider(channel_account):
    """Factory por tipo de canal. Hoy solo WhatsApp (Meta directa, Q1)."""
    return MetaWhatsAppProvider(channel_account)
