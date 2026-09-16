"""B4 monotonic delivery evidence. Call under Message lock, then persist.

Provider acceptance is not delivery, business success or human attention.
Timestamp policy: first local observation of each event; never synthetic backfill.
"""
from .models import Message
from .providers import valid_provider_id


DELIVERY_RANK = {'sent': 1, 'delivered': 2, 'read': 3}


def apply_evidence(message, status, observed_at, *, provider_id=None):
    """Returns changed fields. No pending/discarded resurrection, ever.

Admitted requests are never discarded by takeover, so no discard exception
is needed. A late result may reconcile its own UNCERTAIN with the same token.
"""
    if status not in DELIVERY_RANK or message.status not in (
            'sending', 'uncertain', 'failed', *DELIVERY_RANK):
        return []
    provider_id = provider_id or message.external_message_id
    if not valid_provider_id(provider_id):
        return []
    if message.external_message_id and message.external_message_id != provider_id:
        return []
    fields = []
    if message.external_message_id != provider_id:
        message.external_message_id = provider_id
        fields.append('external_message_id')
    if DELIVERY_RANK[status] > DELIVERY_RANK.get(message.status, 0):
        message.status = status
        fields.append('status')
    # Later delivery proves acceptance, but does not invent an acceptance time.
    field = {'sent': 'provider_accepted_at', 'delivered': 'delivered_at',
             'read': 'read_at'}[status]
    if getattr(message, field) is None:
        setattr(message, field, observed_at)
        fields.append(field)
    return fields
