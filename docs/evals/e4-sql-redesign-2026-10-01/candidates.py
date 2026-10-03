"""Diagnostic-only E4 alternatives; never imported by application runtime."""
from datetime import timedelta

from django.db.models import Exists, F, OuterRef, Q, Subquery, Window
from django.db.models.functions import Now, RowNumber

from apps.agent import durable
from apps.agent.models import Conversation, TurnWork
from apps.channels.models import Message
from apps.organizations.models import Organization


def _future_organization_ids(now):
    clock = now or Now()
    return (Message.objects.filter(direction='in', status='pending', turn_work__isnull=True,
            available_at__gt=clock, available_at__lte=clock + timedelta(seconds=1))
            .exclude(semantic_type=Message.SEMANTIC_SAFETY_SIGNAL)
            .order_by().values('organization_id').distinct())


def _selector(now, excluded, future_ids):
    due = (Q(turn_works__status=TurnWork.PROCESSING,
             turn_works__lease_expires_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING,
             turn_works__next_attempt_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING,
             turn_works__next_attempt_at__isnull=True))
    incoming = Message.objects.filter(direction='in', status='pending',
        turn_work__isnull=True).filter(Q(available_at__isnull=True) |
        Q(available_at__lte=now or Now())).values('conversation_id')
    pending_safety = Message.objects.filter(direction='in', status='pending',
        semantic_type=Message.SEMANTIC_SAFETY_SIGNAL).values('conversation_id')
    latest_outer = TurnWork.objects.filter(organization_id=OuterRef('organization_id'),
        claimed_at__isnull=False).order_by('-claimed_at').values('claimed_at')[:1]
    latest_org = TurnWork.objects.filter(organization_id=OuterRef('pk'),
        claimed_at__isnull=False).order_by('-claimed_at').values('claimed_at')[:1]
    future_orgs = (Organization.objects.filter(pk__in=future_ids)
        .exclude(pk=OuterRef('organization_id'))
        .alias(upcoming_busy=Exists(durable.active_org_work(OuterRef('pk'))),
               upcoming_last_claim=Subquery(latest_org))
        .filter(upcoming_busy=False)
        .filter(Q(upcoming_last_claim__isnull=True) |
                Q(upcoming_last_claim__lt=OuterRef('org_last_claim'))))
    return (Conversation.objects.filter(due | Q(pk__in=incoming)).exclude(pk__in=excluded)
        .alias(org_busy=Exists(durable.active_org_work(OuterRef('organization_id'))))
        .filter(org_busy=False)
        .annotate(org_last_claim=Subquery(latest_outer), org_candidate=Window(RowNumber(),
            partition_by=[F('organization_id')],
            order_by=[F('last_activity_at').asc(), F('pk').asc()]))
        .alias(less_served_soon=Exists(future_orgs))
        .filter(Q(pk__in=pending_safety) | Q(org_last_claim__isnull=True) | Q(less_served_soon=False))
        .filter(org_candidate=1)
        .order_by(F('org_last_claim').asc(nulls_first=True), 'last_activity_at', 'pk')
        .values_list('pk', flat=True)[:3])


def selector_one_query(now=None, excluded=()):
    """A: uncorrelated Message organization set inside a correlated Org EXISTS."""
    return _selector(now, excluded, _future_organization_ids(now))


def selector_two_queries(now=None, excluded=()):
    """B: materialize the small future organization ID set before selection."""
    future_ids = list(_future_organization_ids(now).values_list('organization_id', flat=True))
    return _selector(now, excluded, future_ids)
