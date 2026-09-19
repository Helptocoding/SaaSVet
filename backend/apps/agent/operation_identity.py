"""Revision boundary shared by existing identity writers; no new identity flow."""
from django.core.exceptions import ValidationError
from django.db import transaction

PERMISSION_FIELDS = frozenset({'owner_id', 'verification_level', 'verified_at',
    'linked_via', 'is_ambiguous', 'is_blocked', 'auto_rematch_blocked',
    'external_id', 'phone_normalized', 'organization_id', 'is_active'})


def save_identity(contact, save, args, kwargs):
    if not contact.pk:
        contact.authorization_revision = 0
        return save(*args, **kwargs)
    fields = kwargs.get('update_fields')
    names = {contact._meta.get_field(f).attname for f in fields} if fields else PERMISSION_FIELDS
    if not names & PERMISSION_FIELDS:
        return save(*args, **kwargs)
    with transaction.atomic():
        old = type(contact).all_objects.select_for_update().get(pk=contact.pk)
        if contact.authorization_revision != old.authorization_revision:
            raise ValidationError('Identity revision changed; reload before writing')
        changed = any(getattr(old, f) != getattr(contact, f) for f in names & PERMISSION_FIELDS)
        contact.authorization_revision = old.authorization_revision + int(changed)
        if fields:
            kwargs['update_fields'] = set(fields) | {'authorization_revision'}
        result = save(*args, **kwargs)
        if changed:
            from .operations import invalidate_pending
            invalidate_pending(organization_id=old.organization_id,
                               contact_id=contact.pk, reason='identity_changed')
        return result
