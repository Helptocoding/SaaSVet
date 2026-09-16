"""
channels/views.py — Webhook de WhatsApp (transporte puro, É-F0 PR-4).

Vive FUERA de ``/api/`` (config/urls.py → ``/hooks/whatsapp/``): endpoint
público que autentica por firma HMAC del proveedor, no por JWT — es una
vista Django plana a propósito, para no heredar DEFAULT_PERMISSION_CLASSES
ni la maquinaria de auth de DRF.

Contrato Meta Cloud API:
  GET  → handshake de suscripción (``hub.verify_token`` / ``hub.challenge``).
  POST → eventos firmados: ``X-Hub-Signature-256 = 'sha256=' + HMAC-SHA256``
         del BODY CRUDO con el APP_SECRET. Comparación constant-time.
         Tras validar la firma SIEMPRE se responde 200 (aunque el payload
         traiga eventos no procesables) — un non-200 pone a Meta a
         reintentar en bucle; el dedup por wamid absorbe los reintentos.

Seguridad:
  - Fail-closed: sin ``WHATSAPP_APP_SECRET`` configurado, todo POST → 403.
  - Sin firma válida NO se persiste NADA ni se toca la base.
  - Cero datos en las respuestas (ni detalle de error).
  - PII: los cuerpos de mensaje jamás se loguean (regla R15) — los logs
    llevan ids y metadatos, nunca ``body``.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ChannelAccount
from .events import EVENT_METADATA_KEY, normalize_whatsapp_event

logger = logging.getLogger('agent.events')


def _valid_signature(request) -> bool:
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        logger.error("WEBHOOK_SECRET_MISSING", extra={
            "event": "WEBHOOK_SECRET_MISSING",
        })
        return False
    header = request.headers.get('X-Hub-Signature-256', '')
    if not header.startswith('sha256='):
        return False
    expected = hmac.new(
        secret.encode('utf-8'), request.body, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, header[7:])


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    # --- GET: handshake de verificación del webhook (una vez, al suscribir)
    if request.method == 'GET':
        verify_token = settings.WHATSAPP_VERIFY_TOKEN
        if (
            request.GET.get('hub.mode') == 'subscribe'
            and verify_token
            and hmac.compare_digest(
                request.GET.get('hub.verify_token', ''), verify_token,
            )
        ):
            return HttpResponse(
                request.GET.get('hub.challenge', ''),
                content_type='text/plain',
            )
        return HttpResponseForbidden()

    # --- POST: eventos firmados
    if not _valid_signature(request):
        logger.warning("WEBHOOK_SIGNATURE_REJECTED", extra={
            "event": "WEBHOOK_SIGNATURE_REJECTED",
        })
        return HttpResponseForbidden()

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        # Firmado pero malformado: ACK para cortar reintentos + log.
        logger.warning("WEBHOOK_MALFORMED_PAYLOAD", extra={
            "event": "WEBHOOK_MALFORMED_PAYLOAD",
        })
        return HttpResponse(status=200)

    _process_payload(payload)
    return HttpResponse(status=200)


def _extract_body(msg: dict):
    """Text/caption plus explicit channel evidence; never binary comprehension."""
    return normalize_whatsapp_event(msg)


def _process_payload(payload):
    # Import perezoso: evita ciclos de import channels↔agent al cargar apps.
    from apps.agent.services import ingest_inbound_message, record_status_update

    def objects(value):
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    if not isinstance(payload, dict):
        return
    for entry in objects(payload.get('entry')):
        for change in objects(entry.get('changes')):
            value = change.get('value')
            if not isinstance(value, dict):
                continue
            metadata = value.get('metadata')
            if not isinstance(metadata, dict):
                continue
            phone_number_id = metadata.get(
                'phone_number_id', '',
            )
            if not isinstance(phone_number_id, str) or not phone_number_id:
                continue
            # Resolutor número→org (R1): la ÚNICA lectura sin org previa del
            # subsistema — aquí NACE el tenant context de todo lo que sigue.
            # Baselined con revisión en test_tenant_scoping_audit.
            channel = ChannelAccount.objects.filter(
                external_account_id=phone_number_id,
                status=ChannelAccount.STATUS_ACTIVE,
            ).first()
            if channel is None:
                logger.warning("WEBHOOK_UNKNOWN_CHANNEL", extra={
                    "event": "WEBHOOK_UNKNOWN_CHANNEL",
                    "phone_number_id": phone_number_id,
                })
                continue

            profiles = {
                c.get('wa_id'): (c.get('profile') or {}).get('name', '')
                for c in objects(value.get('contacts'))
                if isinstance(c.get('profile'), dict) and isinstance(c.get('wa_id'), str)
            }
            for msg in objects(value.get('messages')):
                event = _extract_body(msg)
                ingest_inbound_message(
                    channel,
                    wamid=msg.get('id', ''),
                    wa_id=msg.get('from', ''),
                    body=event.text,
                    payload_type=event.payload_type,
                    profile_name=profiles.get(msg.get('from'), ''),
                    raw={
                        'type': msg.get('type'),
                        'timestamp': msg.get('timestamp'),
                        EVENT_METADATA_KEY: event.projection(),
                    },
                )
            for status_event in objects(value.get('statuses')):
                record_status_update(
                    channel,
                    status_event.get('id', ''),
                    status_event.get('status', ''),
                )
