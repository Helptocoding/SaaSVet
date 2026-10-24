"""Application-level scope for citations; a self-FK alone cannot enforce tenants."""
from django.core.exceptions import ValidationError

from .models import Message


def resolve_reply_target(*, organization_id, channel_account_id, contact_id, target_id, lock=False):
    """Resolve a target across episodes; lock=True requires the caller's atomic."""
    if target_id is None:
        return None
    target = None
    if organization_id is not None and channel_account_id is not None and contact_id is not None:
        try:
            # Explicit organization scope, including soft-hidden history: hiding
            # a target must not break validation of an already persisted reply.
            targets = Message.all_objects.filter(organization_id=organization_id,
                channel_account_id=channel_account_id, contact_id=contact_id,
                pk=target_id)
            if lock:
                targets = targets.select_for_update()
            target = targets.first()
        except (TypeError, ValueError, OverflowError):
            pass
    if target is None:
        raise ValidationError({'reply_to': ValidationError(
            'La cita debe pertenecer al mismo hilo y clínica.', code='invalid_reply_target')})
    return target


def provider_reply_target(channel_account, external_message_id):
    """A provider ID must identify exactly one row in the receiving account."""
    if (not isinstance(external_message_id, str) or not external_message_id
            or len(external_message_id) > 128):
        return None
    targets = list(Message.all_objects.filter(
        organization_id=channel_account.organization_id, channel_account=channel_account,
        external_message_id=external_message_id).only('pk').order_by('pk')[:2])
    return targets[0] if len(targets) == 1 else None


def outbound_provider_reply_id(message):
    """Only a scoped, externally addressable original becomes Meta context."""
    from .providers import valid_provider_id

    if not message.reply_to_id or not message.contact_id:
        return None
    target = Message.all_objects.filter(pk=message.reply_to_id,
        organization_id=message.organization_id, contact_id=message.contact_id,
        channel_account_id=message.channel_account_id).only(
            'external_message_id', 'direction', 'status').first()
    if target is None or not valid_provider_id(target.external_message_id):
        return None
    if target.direction == 'out' and target.status not in ('sent', 'delivered', 'read'):
        return None
    return target.external_message_id
