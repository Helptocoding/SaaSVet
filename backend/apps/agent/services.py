"""
agent/services.py — Servicios del núcleo conversacional (É-F0).

PR-4: ingesta de mensajes entrantes — normalización telefónica (Q5),
resolución de identidad de contacto (spec §2.3, regla G4) y conversación
abierta. El webhook (`channels.views`) es transporte puro: verifica firma,
parsea y delega aquí. Nada de LLM en F0.

Regla de tenancy: la organización nace del ChannelAccount receptor (R1) y
de ahí NUNCA se re-deriva; todo acceso a modelos tenant-scoped va con
`for_organization()`.
"""
import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.channels.models import Message
from apps.patients.models import Owner

from .models import ContactIdentity, Conversation

logger = logging.getLogger('agent.events')

# Drain-on-pickup (plan v1.1 §7-C9): los entrantes se vuelven elegibles para
# el worker N segundos después de llegar — agrupa ráfagas cortas sin timers.
INBOUND_AVAILABLE_DELAY = timedelta(seconds=3)


def normalize_wa_id(wa_id: str) -> str:
    """Últimos 10 dígitos de un wa_id mexicano (decisión Q5 — México-only;
    el dominio NO migra a E.164).

    Formatos aceptados (tras quedarnos solo con dígitos):
      - ``521`` + 10 dígitos (13) → últimos 10  (móvil MX con '1' histórico)
      - ``52`` + 10 dígitos (12)  → últimos 10
      - 10 dígitos                → tal cual
    Cualquier otro formato → ``''`` (no normalizable: la identidad queda
    ``unknown`` y el alta de cliente por chat se bloquea — escalada E-10).
    """
    digits = ''.join(ch for ch in (wa_id or '') if ch.isdigit())
    if len(digits) == 13 and digits.startswith('521'):
        return digits[-10:]
    if len(digits) == 12 and digits.startswith('52'):
        return digits[-10:]
    if len(digits) == 10:
        return digits
    return ''


def resolve_contact_identity(channel_account, wa_id, profile_name=''):
    """``get_or_create`` de la identidad de contacto + match a Owner.

    El match corre SOLO al crear la identidad (spec §2.3):
      0 owners → ``unknown`` · 1 → ``phone_match`` · ≥2 → ``unknown`` +
      ``is_ambiguous`` (el sistema jamás "elige" — D1: Owner.phone no es
      unique por org; las intenciones personales escalan, E-05).

    ``display_name`` (perfil de WhatsApp) se refresca en cada mensaje pero
    es dato NO confiable — solo display de bandeja, jamás verificación.
    """
    org = channel_account.organization
    contact = (
        ContactIdentity.objects
        .for_organization(org)
        .filter(channel_type=channel_account.channel_type, external_id=wa_id)
        .first()
    )
    if contact is not None:
        if profile_name and contact.display_name != profile_name[:128]:
            contact.display_name = profile_name[:128]
            contact.save(update_fields=['display_name'])
        return contact

    phone = normalize_wa_id(wa_id)
    owner = None
    ambiguous = False
    level = ContactIdentity.VERIFICATION_UNKNOWN
    if phone:
        owners = list(
            Owner.objects.for_organization(org)
            .filter(phone=phone, is_generic=False)[:2]
        )
        if len(owners) == 1:
            owner = owners[0]
            level = ContactIdentity.VERIFICATION_PHONE_MATCH
        elif len(owners) > 1:
            ambiguous = True

    contact = ContactIdentity(
        organization=org,
        channel_type=channel_account.channel_type,
        external_id=wa_id,
        phone_normalized=phone,
        owner=owner,
        verification_level=level,
        display_name=(profile_name or '')[:128],
        is_ambiguous=ambiguous,
    )
    try:
        with transaction.atomic():
            contact.save()
        logger.info("AGENT_CONTACT_CREATED", extra={
            "event": "AGENT_CONTACT_CREATED",
            "organization_id": org.pk,
            "contact_id": contact.pk,
            "verification_level": level,
            "ambiguous": ambiguous,
        })
    except (ValidationError, IntegrityError):
        # Carrera entre dos mensajes simultáneos del mismo contacto: gana
        # una fila (unique org+channel+external_id); reusar la ganadora.
        contact = ContactIdentity.objects.for_organization(org).get(
            channel_type=channel_account.channel_type, external_id=wa_id,
        )
    return contact


def get_or_create_open_conversation(contact, channel_account):
    """Conversación no-cerrada más reciente del contacto, o una nueva.

    Spec §2.8: una conversación CLOSED no se reabre — un mensaje posterior
    abre un hilo NUEVO que hereda la ContactIdentity (y su nivel de
    verificación persistido).
    """
    org = channel_account.organization
    conv = (
        Conversation.objects
        .for_organization(org)
        .filter(contact=contact)
        .exclude(state=Conversation.STATE_CLOSED)
        .order_by('-created_at')
        .first()
    )
    if conv is None:
        conv = Conversation(
            organization=org,
            channel_account=channel_account,
            contact=contact,
        )
        conv.save()
        logger.info("AGENT_CONVERSATION_OPENED", extra={
            "event": "AGENT_CONVERSATION_OPENED",
            "organization_id": org.pk,
            "conversation_id": conv.pk,
        })
    return conv


def ingest_inbound_message(channel_account, *, wamid, wa_id, body='',
                           payload_type=Message.PAYLOAD_TEXT,
                           profile_name='', raw=None):
    """Persistir un entrante con dedup — el corazón del webhook (PR-4).

    Devuelve el ``Message`` creado, o ``None`` si el wamid ya se vio (R5:
    reintento del proveedor) o si perdimos la carrera contra otro request
    idéntico (el unique parcial de DB decide).

    Contacto bloqueado (GB-10): el mensaje SE persiste (auditable) pero con
    ``status='discarded'`` — el worker no lo procesa y no hay respuesta.
    """
    org = channel_account.organization
    if wamid and Message.objects.for_organization(org).filter(
        channel_account=channel_account,
        direction=Message.DIRECTION_IN,
        external_message_id=wamid,
    ).exists():
        return None

    contact = resolve_contact_identity(channel_account, wa_id, profile_name)
    conversation = get_or_create_open_conversation(contact, channel_account)

    now = timezone.now()
    message = Message(
        organization=org,
        channel_account=channel_account,
        conversation=conversation,
        direction=Message.DIRECTION_IN,
        author_type=Message.AUTHOR_CLIENT,
        payload_type=payload_type,
        body=body or '',
        external_message_id=wamid or None,
        raw_metadata=raw or {},
        status=(
            Message.STATUS_DISCARDED if contact.is_blocked
            else Message.STATUS_PENDING
        ),
        available_at=now + INBOUND_AVAILABLE_DELAY,
    )
    try:
        with transaction.atomic():
            message.save()
    except (ValidationError, IntegrityError):
        return None  # carrera de reintentos: otro request ya lo insertó

    conversation.last_inbound_at = now
    conversation.last_activity_at = now
    conversation.save(update_fields=['last_inbound_at', 'last_activity_at'])
    return message


# Orden forward-only de los acuses de entrega del proveedor.
_DELIVERY_RANK = {
    Message.STATUS_PENDING: 0,
    Message.STATUS_SENT: 1,
    Message.STATUS_DELIVERED: 2,
    Message.STATUS_READ: 3,
}
_PROVIDER_STATUS_MAP = {
    'sent': Message.STATUS_SENT,
    'delivered': Message.STATUS_DELIVERED,
    'read': Message.STATUS_READ,
}


def record_status_update(channel_account, wamid, provider_status,
                         error_detail=''):
    """Acuse de entrega de un SALIENTE (value.statuses[] del webhook).

    Forward-only: un acuse tardío 'sent' no degrada un 'read' ya aplicado.
    """
    if not wamid:
        return None
    org = channel_account.organization
    message = Message.objects.for_organization(org).filter(
        channel_account=channel_account,
        direction=Message.DIRECTION_OUT,
        external_message_id=wamid,
    ).first()
    if message is None:
        return None

    if provider_status == 'failed':
        message.status = Message.STATUS_FAILED
        message.failure_reason = (error_detail or 'proveedor: failed')[:200]
        message.save(update_fields=['status', 'failure_reason'])
        return message

    new_status = _PROVIDER_STATUS_MAP.get(provider_status)
    if new_status is None:
        return None
    if _DELIVERY_RANK.get(new_status, 0) <= _DELIVERY_RANK.get(message.status, 0):
        return message  # acuse viejo o repetido: no degradar
    message.status = new_status
    message.save(update_fields=['status'])
    return message
