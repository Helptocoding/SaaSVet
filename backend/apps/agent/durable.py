"""B3 local authority. Claim: Organization -> Conversation -> TurnWork -> Message.

No network calls inside these transactions. The sender's remote uncertainty
and durable dispatch lifecycle belong to B4.
"""
import logging
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.db.models import F, Q
from django.db.models.functions import Now

from apps.channels.models import Message
from .models import Conversation, TurnWork
from .turn_context import build_turn_context, MessageCursor
from . import claim_diagnostics as claim_trace

logger = logging.getLogger('agent.events')
MAX_ATTEMPTS = 3  # Existing worker policy.
RETRY_DELAY = timedelta(seconds=30)
LEASE = timedelta(minutes=15)
TURN_DEADLINE = timedelta(minutes=12)
# B9 §7 change 3: one authoritative planner work per organization. This is
# a release contract, not a per-replica setting or a provider/rate limit.
ORG_ACTIVE_WORK_LIMIT = 1


class OwnershipLost(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OwnershipWitness:
    organization_id: int
    conversation_id: int
    turn_work_id: int
    lease_token: UUID
    ownership_epoch: int


@claim_trace.database_clock
def db_now():
    with connection.cursor() as cursor:
        cursor.execute('SELECT statement_timestamp()')
        return cursor.fetchone()[0]


def _event(name, work=None, **extra):
    if work is not None:
        extra.update(turn_work_id=work.pk, conversation_id=work.conversation_id,
                     organization_id=work.organization_id, attempts=work.attempts)
    # Avoid reporting transitions that subsequently rolled back.
    transaction.on_commit(lambda: logger.info('AGENT_TURN_' + name.upper(), extra={
        'event': 'AGENT_TURN_' + name.upper(), **extra}))


def witness_query(witness):
    return TurnWork.objects.filter(
        pk=witness.turn_work_id, organization_id=witness.organization_id,
        conversation_id=witness.conversation_id, lease_token=witness.lease_token,
        ownership_epoch=witness.ownership_epoch,
        conversation__organization_id=witness.organization_id,
        conversation__ownership_epoch=witness.ownership_epoch,
        status=TurnWork.PROCESSING, lease_expires_at__gt=Now())


def _reject(witness):
    logger.warning('AGENT_TURN_FENCING_REJECT', extra={
        'event': 'AGENT_TURN_FENCING_REJECT', 'turn_work_id': witness.turn_work_id,
        'conversation_id': witness.conversation_id})
    raise OwnershipLost('TurnWork authority is no longer valid')


def assert_witness(witness):
    if not witness_query(witness).exists():
        _reject(witness)


def check_turn_deadline(witness):
    assert_witness(witness)
    if not witness_query(witness).filter(claimed_at__gt=Now() - TURN_DEADLINE).exists():
        raise TimeoutError('B3 turn deadline exceeded')


def lock_witness(witness):
    """Caller owns atomic; CAS callers retain these locks through their write."""
    conv = Conversation.objects.select_for_update().filter(
        pk=witness.conversation_id, organization_id=witness.organization_id,
        ownership_epoch=witness.ownership_epoch).first()
    if conv is None:
        _reject(witness)
    work = witness_query(witness).select_for_update(of=('self',)).first()
    if work is None:
        _reject(witness)
    return conv, work


def active_org_work(organization_id):
    """DB-derived capacity; no counter or second ownership authority.

    organization_id may be an OuterRef for the poller's candidate query.
    Expiry/epoch revocation invalidates local authority, not remote HTTP.
    """
    return TurnWork.objects.filter(
        organization_id=organization_id, status=TurnWork.PROCESSING,
        lease_expires_at__gt=Now(),
        conversation__organization_id=F('organization_id'),
        conversation__ownership_epoch=F('ownership_epoch'))


def _concurrency_event(outcome):
    # Closed, low-cardinality vocabulary. Telemetry cannot undo a committed
    # claim or become the capacity authority.
    def emit():
        try:
            logger.info('AGENT_CONCURRENCY_' + outcome.upper(), extra={
                'event': 'AGENT_CONCURRENCY_' + outcome.upper(),
                'scope': 'organization', 'limit': ORG_ACTIVE_WORK_LIMIT})
        except Exception:
            pass
    transaction.on_commit(emit)


@claim_trace.observed('claim')
def claim_turn(conversation_id, *, eligible_at=None):
    """Create fixed membership or reclaim the same work with a fresh token.

    eligible_at is the existing polling/test drain clock; it NEVER decides
    lease validity, retries, CAS or ownership.
    """
    from apps.organizations.models import Organization
    with transaction.atomic():
        org_id = Conversation.objects.filter(pk=conversation_id).values_list(
            'organization_id', flat=True).first()
        if org_id is None:
            return None
        # No KEY UPDATE: inbound/domain FK checks must not wait for a quota
        # lock. SKIP LOCKED means defer to another poll, never lose the input.
        org = Organization.objects.select_for_update(
            no_key=True, skip_locked=True).filter(pk=org_id).first()
        if org is None:
            _concurrency_event('deferred')
            return None
        if not org.is_active:
            return None
        conv = (Conversation.objects.select_for_update(skip_locked=True, of=('self',))
                .select_related('organization', 'channel_account', 'contact')
                .filter(pk=conversation_id, organization_id=org_id).first())
        if conv is None:
            return None
        # All claimers hold this org row. Concurrent release can only reduce
        # occupancy; it cannot create an N+1 race. Check before any membership,
        # attempt, lease or budget mutation, including expired-work reclaim.
        if active_org_work(org_id).exists():
            _concurrency_event('saturated')
            return None
        witness = _claim_turn_locked(conv, eligible_at=eligible_at)
        if witness is not None:
            _concurrency_event('admitted')
        return witness


@claim_trace.observed('claim_locked')
def _claim_turn_locked(conv, *, eligible_at=None):
    """B3 primitive; caller holds Conversation in an atomic transaction.

    Planners enter through claim_turn and its organizational admission.
    B5 receipt uses this only inside atomic safety completion: it never commits
    PROCESSING or dispatches a planner/provider and cannot acquire planner quota.
    """
    if not connection.in_atomic_block:
        raise RuntimeError('Claim requires a Conversation transaction')
    now = db_now()
    work = (TurnWork.objects.select_for_update().filter(conversation=conv,
                organization_id=conv.organization_id,
                status__in=TurnWork.NON_TERMINAL).first())
    reclaimed = False
    member_ids = None
    claim_trace.existing_work(work)
    if work:
        if work.ownership_epoch != conv.ownership_epoch:
            _terminal_failure(work, conv, 'ownership_changed', now)
            return None
        if work.status == TurnWork.PROCESSING:
            if work.lease_expires_at > now:
                return None
            _event('lease_expired', work)
            reclaimed = True
        elif work.next_attempt_at and work.next_attempt_at > now:
            return None
        if work.attempts >= MAX_ATTEMPTS:
            _terminal_failure(work, conv, 'attempts_exhausted', now)
            return None
    else:
        members = list(Message.objects.for_organization(conv.organization_id)
            .filter(conversation=conv, direction='in', status='pending',
                    turn_work__isnull=True)
            .filter(Q(available_at__isnull=True) |
                    Q(available_at__lte=eligible_at or now))
            .order_by('created_at', 'id'))
        if not members:
            return None
        claim_trace.members(members)
        context = build_turn_context(conv, members, now=now)
        member_ids = context.inbound_ids
        work = TurnWork.objects.create(
            organization_id=conv.organization_id, conversation=conv,
            anchor_message=members[-1], anchor_created_at=context.anchor.created_at,
            cursor_message_id=context.history_before.message_id,
            cursor_created_at=context.history_before.created_at,
            context_at=now, clinic_timezone=context.clinic_timezone,
            ownership_epoch=conv.ownership_epoch)
        Message.objects.for_organization(conv.organization_id).filter(
            pk__in=context.inbound_ids, conversation=conv, turn_work__isnull=True
        ).update(turn_work=work)
        _event('created', work, oldest_pending_age_seconds=max(
            0, (now - members[0].created_at).total_seconds()))
    old_token, old_status = work.lease_token, work.status
    token = uuid4()
    count = TurnWork.objects.filter(pk=work.pk, lease_token=old_token,
        status=old_status, ownership_epoch=conv.ownership_epoch,
        organization_id=conv.organization_id).update(
            status=TurnWork.PROCESSING, lease_token=token,
            lease_expires_at=now + LEASE, claimed_at=now,
            attempts=F('attempts') + 1, next_attempt_at=None)
    if count != 1:
        raise OwnershipLost('Claim CAS failed')
    Message.objects.for_organization(conv.organization_id).filter(
        turn_work=work, direction='in').update(process_attempts=F('process_attempts') + 1)
    Conversation.objects.filter(pk=conv.pk).update(processing_until=now + LEASE)
    work.attempts += 1
    claim_trace.bound(work, token, now, now + LEASE, member_ids)
    _event('reclaimed' if reclaimed else 'claimed', work)
    return OwnershipWitness(conv.organization_id, conv.pk, work.pk,
                            token, conv.ownership_epoch)


def context_for_work(witness):
    assert_witness(witness)
    work = witness_query(witness).select_related(
        'conversation__organization', 'conversation__contact',
        'conversation__channel_account').get()
    members = list(Message.objects.for_organization(witness.organization_id).filter(
        turn_work=work, conversation_id=witness.conversation_id, direction='in'
    ).order_by('created_at', 'id'))
    context = build_turn_context(work.conversation, members, now=work.context_at)
    if (context.anchor != MessageCursor(work.anchor_created_at, work.anchor_message_id)
            or context.history_before != MessageCursor(work.cursor_created_at, work.cursor_message_id)):
        raise ValueError('TurnWork causal membership changed')
    return replace(context, clinic_timezone=work.clinic_timezone,
                   clinic_now=work.context_at.astimezone(ZoneInfo(work.clinic_timezone)))


def has_new_input(work):
    return Message.objects.for_organization(work.organization_id).filter(
        conversation_id=work.conversation_id, direction='in'
    ).exclude(status='discarded').filter(
        Q(created_at__gt=work.anchor_created_at) |
        Q(created_at=work.anchor_created_at, id__gt=work.anchor_message_id)).exists()


def finalize_turn(witness, *, outputs=(), changes=None, outcome='completed', proposal_operation=None,
                  evaluate_consent=False):
    """Atomic local changes + final PENDING messages + completion, under CAS."""
    if changes is not None and changes.witness != witness:
        raise ValueError('Local changes belong to another ownership witness')
    with transaction.atomic():
        conv, work = lock_witness(witness)
        check_turn_deadline(witness)
        # B5 consolidates a bounded safety case even if another message arrived.
        # No normal output/changes may use this completion-only exception.
        safety_completion = outcome == 'safety_handoff' and not outputs and changes is None
        deferred = has_new_input(work) and not safety_completion
        if deferred:
            outputs = ()
            outcome = 'deferred_to_new_input'
        if changes is not None:
            changes.flush(deferred=deferred)
            proposal_operation = getattr(changes, 'proposal_operation', None)
            if not deferred and getattr(changes, 'consent_correction_unresolved', False):
                from .operation_consent import Evaluation, reply_text
                outputs = [{'body': reply_text(Evaluation('AMBIGUOUS', 'correction'))}]
        if not deferred and evaluate_consent:
            from .operation_consent import evaluate_turn, reply_text
            consent = evaluate_turn(witness)
            outputs = (() if consent.reason in ('human_ownership', 'safety', 'disabled')
                       else [{'body': reply_text(consent)}])
            # B9 harness integration: the worker reaches the existing B8A
            # boundary while its B3 witness is still live. Closed releases keep
            # the historical consent-only response. No provider IO here.
            from .operation_execution import consent_execution_output
            execution_output = consent_execution_output(witness, consent)
            if execution_output is not None:
                outputs = [execution_output]
            outcome = 'consent_' + consent.decision.lower()
        if not deferred and proposal_operation is not None and not proposal_operation.proposal_message_id:
            # One canonical output; never mix a free-form planner question with
            # the proposal that the next response could authorize.
            from .operation_proposals import publish_proposal
            message = publish_proposal(witness, proposal_operation, ordinal=0)
            if message is not None:
                outputs = ()
        for ordinal, output in enumerate(outputs):
            Message.objects.create(
                organization_id=conv.organization_id, conversation=conv,
                channel_account_id=conv.channel_account_id, contact_id=conv.contact_id,
                direction='out', status='pending', turn_work=work,
                origin_epoch=witness.ownership_epoch, output_ordinal=ordinal,
                body=output['body'], author_type=output.get('author_type', Message.AUTHOR_SYSTEM),
                semantic_type=output.get('semantic_type', ''),
                operation_key=output.get('operation_key', ''))
        check_turn_deadline(witness)
        if witness_query(witness).update(status=TurnWork.COMPLETED,
                completed_at=Now(), outcome_code=outcome, lease_expires_at=None) != 1:
            _reject(witness)
        Message.objects.for_organization(conv.organization_id).filter(
            turn_work=work, conversation=conv, direction='in', status='pending'
        ).update(status='processed')
        Conversation.objects.filter(pk=conv.pk, ownership_epoch=witness.ownership_epoch
        ).update(processing_until=None, **({'last_activity_at': Now()} if outputs else {}))
        transaction.on_commit(lambda: _event(outcome if deferred else 'completed', work))
    return outcome


def _terminal_failure(work, conv, reason, now):
    TurnWork.objects.filter(pk=work.pk, status__in=TurnWork.NON_TERMINAL).update(
        status=TurnWork.FAILED, outcome_code=reason, completed_at=now,
        lease_expires_at=None, next_attempt_at=None)
    # Preserve inbound status and membership: FAILED is never PROCESSED.
    Conversation.objects.filter(pk=conv.pk).update(processing_until=None)
    _event('failed', work, outcome_code=reason)
    if reason == 'attempts_exhausted':
        from .worker import _escalate_after_failure
        _escalate_after_failure(conv, work=work)


def fail_turn(witness, reason='turn_error'):
    with transaction.atomic():
        conv, work = lock_witness(witness)
        terminal = work.attempts >= MAX_ATTEMPTS
        count = witness_query(witness).update(
            status=TurnWork.FAILED if terminal else TurnWork.PENDING,
            next_attempt_at=None if terminal else db_now() + RETRY_DELAY * work.attempts,
            lease_expires_at=None, outcome_code=reason,
            completed_at=db_now() if terminal else None)
        if count != 1:
            _reject(witness)
        Conversation.objects.filter(pk=conv.pk).update(processing_until=None)
        if terminal:
            from .worker import _escalate_after_failure
            _escalate_after_failure(conv, work=work)
        _event('failed' if terminal else 'retry_scheduled', work, outcome_code=reason)


def invalidate_ownership(conversation, *, reason):
    """Requires Conversation lock in caller's atomic. No remote cancellation."""
    if not connection.in_atomic_block:
        raise RuntimeError('Ownership change requires a Conversation transaction')
    current = Conversation.objects.select_for_update().get(
        pk=conversation.pk, organization_id=conversation.organization_id)
    conversation.ownership_epoch = current.ownership_epoch + 1
    Conversation.objects.filter(pk=conversation.pk,
        organization_id=conversation.organization_id).update(
            ownership_epoch=conversation.ownership_epoch, processing_until=None)
    from .operations import invalidate_pending
    invalidate_pending(organization_id=conversation.organization_id,
                       conversation_id=conversation.pk, reason='ownership_changed')
    work_rows = TurnWork.objects.select_for_update().filter(
        conversation=conversation, organization_id=conversation.organization_id,
        status__in=TurnWork.NON_TERMINAL)
    for work in work_rows:
        from .safety_handoff import retain_interrupted_safety
        retain_interrupted_safety(conversation, work)
        _terminal_failure(work, conversation, reason, db_now())
    discarded_pending = Message.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, direction='out', status='pending',
        author_type__in=(Message.AUTHOR_AGENT, Message.AUTHOR_SYSTEM)
    ).update(
        status='discarded', failure_reason='ownership_invalidated')
    # B4: only claims without logical HTTP admission can be discarded.
    # An admitted request may still complete after takeover; preserve its token.
    discarded_claims = Message.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, direction='out', status='sending',
        send_admitted_at__isnull=True,
    ).update(status='discarded', failure_reason='ownership_invalidated')
    _event('ownership_changed', conversation_id=conversation.pk,
           ownership_epoch=conversation.ownership_epoch, outcome_code=reason,
           discarded_outbounds=discarded_pending + discarded_claims)
