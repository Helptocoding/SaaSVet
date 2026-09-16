"""Authenticated webhook status reconciliation, scoped and row-serialized."""
from django.db import transaction

from apps.agent.durable import db_now
from apps.agent.sender import event, _lock_conv, _scope
from .delivery import DELIVERY_RANK, apply_evidence
from .models import ChannelAccount, Message
from .providers import valid_provider_id


def record_status(channel, provider_id, status):
    if not valid_provider_id(provider_id) or status not in (*DELIVERY_RANK, 'failed'):
        event('webhook_unknown')
        return None
    if not ChannelAccount.objects.filter(pk=channel.pk,
            organization_id=channel.organization_id).exists():
        event('webhook_scope_rejected')
        return None
    candidates = list(Message.objects.filter(organization_id=channel.organization_id,
        channel_account_id=channel.pk, direction='out', external_message_id=provider_id
    ).values('pk', 'conversation_id')[:2])
    # Legacy may contain duplicate outbound IDs: never choose an arbitrary row.
    if len(candidates) != 1:
        event('webhook_unmatched', ambiguous=len(candidates) > 1)
        return None
    candidate = candidates[0]
    with transaction.atomic():
        conv = _lock_conv(candidate['conversation_id'], channel.organization_id)
        message = Message.objects.select_for_update().filter(pk=candidate['pk'],
            organization_id=channel.organization_id, channel_account_id=channel.pk,
            conversation_id=candidate['conversation_id'],
            external_message_id=provider_id, direction='out').first()
        # Legacy orphan outbounds still have an exact account/org/wamid. They
        # can receive evidence without inventing a conversation or dispatch.
        scope_ok = message is not None and (
            _scope(message, conv) or (message.conversation_id is None
                and (message.contact_id is None or
                     message.contact.organization_id == channel.organization_id)))
        if not scope_ok:
            event('webhook_scope_rejected')
            return None
        now = db_now()
        if status == 'failed':
            # Failure of downstream delivery does not disprove prior acceptance.
            # Preserve lifecycle/evidence and expose a diagnostic; no retry.
            if message.status in (*DELIVERY_RANK, 'uncertain', 'sending'):
                if 'provider_delivery_failed' not in message.failure_reason:
                    # Keep prior uncertainty diagnostics when reconciling later.
                    prior = message.failure_reason if message.uncertain_at else ''
                    message.failure_reason = (prior[:170] + ';' if prior else '') + 'provider_delivery_failed'
                    message.save(update_fields=['failure_reason'])
                    event('delivery_failed', message_id=message.pk)
            return message
        fields = apply_evidence(message, status, now)
        if fields:
            message.save(update_fields=fields)
            metrics = {}
            if status == 'sent' and message.send_admitted_at is not None:
                metrics['provider_acceptance_latency_seconds'] = max(
                    0, (now - message.send_admitted_at).total_seconds())
            elif status in ('delivered', 'read') and message.provider_accepted_at is not None:
                metrics[('delivery' if status == 'delivered' else 'read') + '_latency_seconds'] = max(
                    0, (now - message.provider_accepted_at).total_seconds())
            event('webhook_' + status, message_id=message.pk, **metrics)
        return message
