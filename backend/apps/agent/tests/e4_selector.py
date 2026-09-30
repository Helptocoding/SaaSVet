"""DIAGNOSTIC_ONLY organization selection; never imported by runtime.

One candidate per org, least recently claimed org first, bounded lookahead.
Processing batch, durable claim and all planner semantics stay unchanged.
"""
from django.db.models import Exists, OuterRef, Subquery, Q, F, Window
from django.db.models.functions import Now, RowNumber
from apps.agent.models import Conversation, TurnWork
from apps.channels.models import Message
from apps.agent import durable, worker


def candidates(batch=1, now=None, *, fair=True):
    due = (Q(turn_works__status=TurnWork.PROCESSING, turn_works__lease_expires_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__lte=Now()) |
           Q(turn_works__status=TurnWork.PENDING, turn_works__next_attempt_at__isnull=True))
    incoming = Message.objects.filter(direction='in', status='pending', turn_work__isnull=True).filter(
        Q(available_at__isnull=True) | Q(available_at__lte=now or Now())).values('conversation_id')
    latest = TurnWork.objects.filter(organization_id=OuterRef('organization_id'),
        claimed_at__isnull=False).order_by('-claimed_at').values('claimed_at')[:1]
    query = (Conversation.objects.filter(due | Q(pk__in=incoming))
        .alias(org_busy=Exists(durable.active_org_work(OuterRef('organization_id'))))
        .filter(org_busy=False)
        .annotate(org_last_claim=Subquery(latest), org_candidate=Window(RowNumber(),
            partition_by=[F('organization_id')], order_by=[F('last_activity_at').asc(), F('pk').asc()]))
        .filter(org_candidate=1))
    ordering = ([F('org_last_claim').asc(nulls_first=True)] if fair else []) + ['last_activity_at', 'pk']
    return query.order_by(*ordering).values_list('pk', flat=True)[:max(batch, 3)]


def process_pending_conversations(batch=10, now=None):
    processed = 0
    import os
    for conversation in list(candidates(batch, now, fair=os.environ.get('E4_SELECTOR') == 'fair')):
        if processed >= batch:
            break
        witness = worker._claim_turn(conversation, now)
        if witness is None:
            continue
        try:
            worker._run_turn(witness)
        except durable.OwnershipLost:
            pass
        except Exception as exc:
            worker._handle_turn_failure(witness, exc)
        processed += 1
    return processed
