import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.permissions import user_has_permission
from .models import Notification, NotificationReceipt
from .policies import CASH_DIFFERENCE_NOTIFICATION_THRESHOLD

logger = logging.getLogger(__name__)


def on_commit_best_effort(fn):
    def wrapper():
        try:
            fn()
        except Exception:
            logger.exception("notifications: best-effort callback falló (dominio intacto)")
    transaction.on_commit(wrapper)


def _recipients_with_capability(org, capability):
    from apps.users.models import User
    users = list(
        User.objects.filter(organization=org, is_active=True).select_related('organization')
    )
    return [u for u in users if user_has_permission(u, capability)]


def _get_or_create_notification(org, type, dedup_key, entity_type='',
                               entity_public_id=None, payload=None, occurred_at=None):
    notif, created = Notification.objects.for_organization(org).get_or_create(
        organization=org, dedup_key=dedup_key,
        defaults={
            'type': type,
            'entity_type': entity_type,
            'entity_public_id': entity_public_id,
            'payload': payload or {},
            'occurred_at': occurred_at or timezone.now(),
        },
    )
    return notif, created


def _ensure_receipts(org, notification, users):
    receipts = []
    for user in users:
        receipt, _ = NotificationReceipt.objects.for_organization(org).get_or_create(
            organization=org, notification_key=notification.dedup_key, user=user,
            defaults={'notification': notification, 'seen_at': None},
        )
        if receipt.notification_id is None:
            receipt.notification = notification
            receipt.full_clean()
            receipt.save(update_fields=['notification', 'updated_at'])
        receipts.append(receipt)
    return receipts


def handle_stock_transition(organization, product, prev_qty, new_qty,
                            causing_movement_id, actor=None, occurred_at=None):
    prev_qty = Decimal(prev_qty)
    new_qty = Decimal(new_qty)
    min_stock = Decimal(getattr(product, 'min_stock', 0) or 0)
    event_type = None
    if prev_qty > 0 and new_qty == 0:
        event_type = 'stock_out'
    elif prev_qty > min_stock and new_qty <= min_stock and new_qty > 0:
        event_type = 'stock_low_entered'
    if event_type is None:
        return None
    dedup_key = f"{event_type}:{product.pk}:{causing_movement_id}"
    payload = {
        'product_name_snapshot': getattr(product, 'name', ''),
        'stock_quantity': str(new_qty),
        'min_stock': str(min_stock),
        'product_public_id': str(getattr(product, 'public_id', '')),
    }

    def _create():
        notif, created = _get_or_create_notification(
            organization, event_type, dedup_key,
            entity_type='product', entity_public_id=getattr(product, 'public_id', None),
            payload=payload, occurred_at=occurred_at,
        )
        if created:
            users = _recipients_with_capability(organization, 'inventory.view')
            _ensure_receipts(organization, notif, users)
        return notif

    result = {}
    on_commit_best_effort(lambda: result.setdefault('notif', _create()))
    return result


def handle_cash_difference(organization, session, actor=None):
    difference = Decimal(getattr(session, 'difference', 0) or 0)
    if abs(difference) < CASH_DIFFERENCE_NOTIFICATION_THRESHOLD:
        return None
    dedup_key = f"cash_difference:{session.public_id}"
    payload = {
        'difference': str(difference),
        'session_public_id': str(session.public_id),
        'closed_by': getattr(getattr(session, 'closed_by', None), 'username', None),
    }

    def _create():
        notif, created = _get_or_create_notification(
            organization, 'cash_difference', dedup_key,
            entity_type='cash_session', entity_public_id=getattr(session, 'public_id', None),
            payload=payload,
        )
        if created:
            users = _recipients_with_capability(organization, 'cashsession.close')
            _ensure_receipts(organization, notif, users)
        return notif

    result = {}
    on_commit_best_effort(lambda: result.setdefault('notif', _create()))
    return result


def _key_is_visible(organization, user, key):
    persisted = Notification.objects.for_organization(organization).filter(
        dedup_key=key, receipts__user=user,
    ).exists()
    if persisted:
        return True

    # Appointment notifications are derived, so validate against the same
    # builder used by the feed before creating a sparse receipt.
    from .builders import build_appointment_derived
    return any(
        item['key'] == key
        for item in build_appointment_derived(organization, user)
    )


def mark_seen(organization, user, key):
    if not _key_is_visible(organization, user, key):
        raise ValidationError('La notificación no existe o no es visible.')
    try:
        receipt = NotificationReceipt.objects.for_organization(organization).get(
            notification_key=key, user=user,
        )
        if receipt.seen_at is None:
            receipt.seen_at = timezone.now()
            receipt.full_clean()
            receipt.save(update_fields=['seen_at', 'updated_at'])
        return receipt, False
    except NotificationReceipt.DoesNotExist:
        receipt = NotificationReceipt(
            organization=organization, notification=None,
            notification_key=key, user=user, seen_at=timezone.now(),
        )
        receipt.full_clean()
        receipt.save()
        return receipt, True


def mark_all_seen(organization, user, keys):
    marked = 0
    for key in keys:
        receipt, created = mark_seen(organization, user, key)
        if receipt.seen_at is not None:
            marked += 1
    return marked
