from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.permissions import make_permission
from .builders import build_appointment_derived
from .models import Notification, NotificationReceipt
from .policies import FEED_DEFAULT_LIMIT, FEED_MAX_LIMIT, TYPE_PRIORITY
from .serializers import FeedItemSerializer
from .services import mark_all_seen, mark_seen


def _serialize_persisted(org, user):
    notifs = list(
        Notification.objects.for_organization(org)
        .filter(receipts__user=user)
        .select_related()
        .order_by('-occurred_at')[:FEED_MAX_LIMIT]
    )
    keys = [n.dedup_key for n in notifs]
    receipts = {
        r.notification_key: r
        for r in NotificationReceipt.objects.for_organization(org).filter(
            user=user, notification_key__in=keys,
        )
    }
    items = []
    for n in notifs:
        receipt = receipts.get(n.dedup_key)
        if receipt is None:
            continue
        payload = n.payload or {}
        name = payload.get('product_name_snapshot') or payload.get('difference') or ''
        if n.type == 'stock_low_entered':
            title = f"{name or 'Producto'} entró en stock bajo"
        elif n.type == 'stock_out':
            title = f"{name or 'Producto'} se agotó"
        elif n.type == 'cash_difference':
            title = f"Diferencia de caja por ${payload.get('difference', '')}"
        else:
            title = n.type
        items.append({
            'key': n.dedup_key,
            'source': 'persisted',
            'type': n.type,
            'priority': TYPE_PRIORITY.get(n.type, 'info'),
            'title': title,
            'body': '',
            'occurred_at': n.occurred_at,
            'age_min': 0,
            'seen': receipt.seen_at is not None,
            'active': False,
            'entity': {'type': n.entity_type, 'public_id': str(n.entity_public_id) if n.entity_public_id else None},
        })
    return items


@api_view(['GET'])
@permission_classes([make_permission("notification.list")])
def notification_feed(request):
    user = request.user
    org = user.organization
    if org is None:
        return Response({'code': 'no_organization', 'message': 'Sin organización.'}, status=403)
    try:
        limit = int(request.query_params.get('limit', FEED_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = FEED_DEFAULT_LIMIT
    limit = max(1, min(limit, FEED_MAX_LIMIT))
    now = timezone.now()
    persisted = _serialize_persisted(org, user)
    derived = build_appointment_derived(org, user, now=now)
    unseen_count = Notification.objects.for_organization(org).filter(
        receipts__user=user, receipts__seen_at__isnull=True,
    ).distinct().count() + sum(1 for item in derived if not item['seen'])
    merged = persisted + derived
    for item in merged:
        occurred = item['occurred_at']
        delta = (now - occurred).total_seconds() / 60 if occurred else 0
        item['age_min'] = max(0, int(delta))
    merged.sort(key=lambda i: (i['seen'], -(i['occurred_at'].timestamp() if i['occurred_at'] else 0)))
    merged = merged[:limit]
    data = FeedItemSerializer(merged, many=True).data
    return Response({'items': data, 'unseen_count': unseen_count})


@api_view(['POST'])
@permission_classes([make_permission("notification.seen")])
def notification_seen(request, key):
    user = request.user
    org = user.organization
    if org is None:
        return Response({'code': 'no_organization', 'message': 'Sin organización.'}, status=403)
    try:
        receipt, _ = mark_seen(org, user, key)
    except ValidationError:
        return Response(
            {'code': 'notification_not_found', 'message': 'Notificación no encontrada.'},
            status=404,
        )
    return Response({'key': key, 'seen_at': receipt.seen_at})


@api_view(['POST'])
@permission_classes([make_permission("notification.seen")])
def notification_seen_all(request):
    user = request.user
    org = user.organization
    if org is None:
        return Response({'code': 'no_organization', 'message': 'Sin organización.'}, status=403)
    now = timezone.now()
    persisted = _serialize_persisted(org, user)
    derived = build_appointment_derived(org, user, now=now)
    keys = [i['key'] for i in (persisted + derived) if not i['seen']]
    marked = mark_all_seen(org, user, keys)
    return Response({'marked': marked})
