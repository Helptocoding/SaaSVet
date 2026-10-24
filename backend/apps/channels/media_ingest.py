"""Persist incoming media in the same transaction as its deduplicated Message."""
import logging

from django.db import IntegrityError, transaction

from .models import MessageMedia

logger = logging.getLogger('agent.events')


def persist_inbound_media(message, metadata):
    if not metadata:
        return None
    scope = dict(organization_id=message.organization_id, channel_account_id=message.channel_account_id,
                 provider_media_id=metadata['provider_media_id'])
    existing = MessageMedia.objects.filter(**scope).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            media = MessageMedia(message=message, organization_id=message.organization_id,
                channel_account=message.channel_account, **metadata)
            media.clean()
            # Canonical bounded transport fields, already scoped above. The DB
            # unique resolves competing provider IDs without losing the Message.
            media.save(validate=False)
            return media
    except IntegrityError:
        return MessageMedia.objects.get(**scope)
