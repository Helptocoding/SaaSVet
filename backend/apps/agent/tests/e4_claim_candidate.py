"""DIAGNOSTIC_ONLY bounded yield; no reservation, claim or budget authority."""
from datetime import timedelta


def candidates(now=None, excluded=()):
    from django.db.models import Exists, F, OuterRef, Q, Subquery, Window
    from django.db.models.functions import Now, RowNumber
    from apps.agent import durable
    from apps.agent.models import Conversation, TurnWork
    from apps.channels.models import Message
    clock = now or Now()
    due = (Q(turn_works__status=TurnWork.PROCESSING, turn_works__lease_expires_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__isnull=True))
    incoming = Message.objects.filter(direction='in', status='pending', turn_work__isnull=True).filter(
        Q(available_at__isnull=True) | Q(available_at__lte=clock)).values('conversation_id')
    latest = TurnWork.objects.filter(organization_id=OuterRef('organization_id'),
        claimed_at__isnull=False).order_by('-claimed_at').values('claimed_at')[:1]
    # One existing PROFILE poll, not a new latency gate. Never yield an org
    # without history; preserve the original recency order and candidate bound.
    upcoming = (Message.objects.filter(direction='in', status='pending', turn_work__isnull=True,
        available_at__gt=clock, available_at__lte=clock+timedelta(seconds=1))
        .exclude(organization_id=OuterRef('organization_id'))
        .exclude(semantic_type=Message.SEMANTIC_SAFETY_SIGNAL)
        .alias(upcoming_busy=Exists(durable.active_org_work(OuterRef('organization_id'))),
               upcoming_last_claim=Subquery(latest))
        .filter(upcoming_busy=False)
        .filter(Q(upcoming_last_claim__isnull=True) |
                Q(upcoming_last_claim__lt=OuterRef('org_last_claim'))))
    return (Conversation.objects.filter(due | Q(pk__in=incoming)).exclude(pk__in=excluded)
        .alias(org_busy=Exists(durable.active_org_work(OuterRef('organization_id'))))
        .filter(org_busy=False)
        .annotate(org_last_claim=Subquery(latest), org_candidate=Window(RowNumber(),
            partition_by=[F('organization_id')],
            order_by=[F('last_activity_at').asc(), F('pk').asc()]))
        .alias(less_served_soon=Exists(upcoming))
        .filter(Q(org_last_claim__isnull=True) | Q(less_served_soon=False))
        .filter(org_candidate=1)
        .order_by(F('org_last_claim').asc(nulls_first=True), 'last_activity_at', 'pk')
        .values_list('pk', flat=True)[:3])
