"""B5 local handoff consolidation. Every guidance is a B3/B4 durable Message."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.channels.models import Message
from . import durable, safety
from .models import Conversation, HumanHandoff, TurnWork


def automation_enabled():
    return getattr(settings, 'AGENT_SAFETY_AUTOMATION_ENABLED', False)


def active_handoff(conversation):
    # New safety case first, otherwise one compatible legacy open case. Never
    # merge/delete historic open cases or impose global active uniqueness.
    rows = HumanHandoff.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, resolved_at__isnull=True)
    return rows.order_by('-priority', '-id').first()


def _event(name, **fields):
    transaction.on_commit(lambda: safety.logger.info('AGENT_SAFETY_' + name,
        extra={'event': 'AGENT_SAFETY_' + name, **fields}))


def _record(conversation, work, assessment):
    handoff = active_handoff(conversation)
    created = handoff is None
    first_safety = created or not handoff.safety_signals
    if created:
        handoff = HumanHandoff(organization_id=conversation.organization_id, conversation=conversation)
    if first_safety:
        handoff.source_turn = work
        handoff.source_message_id = work.anchor_message_id
        handoff.event_key = f'safety:{work.pk}'
    handoff.reason_code = HumanHandoff.REASON_SAFETY
    handoff.reason_detail = safety.CATALOG_VERSION
    handoff.priority = HumanHandoff.PRIORITY_URGENT
    handoff.notification_status = 'NOT_CONFIGURED'
    handoff.safety_signals = sorted(set(handoff.safety_signals) | set(assessment.matched_signals))
    handoff.save()
    _event('HANDOFF_CREATED' if created else 'HANDOFF_REUSED',
        classification=assessment.classification,
        pending_age_seconds=max(0, (timezone.now() - handoff.created_at).total_seconds()))
    return handoff, first_safety


def finalize_safety(witness, assessment):
    """One commit: case + suspended task + work completion + epoch + guidance.

    Completing the source work before invalidate_ownership avoids inventing a
    second takeover. Its immutable causal epoch remains on the output; a narrow
    handoff reference admits this exact output at the resulting epoch only.
    """
    if assessment.classification == safety.NO_SIGNAL:
        raise ValueError('A safety handoff requires a detected signal')
    with transaction.atomic():
        conv, work = durable.lock_witness(witness)
        durable.check_turn_deadline(witness)
        human_owned = bool(conv.claimed_by_id or conv.state == Conversation.STATE_HUMAN_ACTIVE)
        handoff, first_safety = _record(conv, work, assessment)
        if not human_owned:
            from . import confirmations, goals
            from .models import ConversationGoal
            # Existing suspension semantics, no second flow/ownership mechanism.
            confirmations.suspend_pending(conv, reason_code=HumanHandoff.REASON_SAFETY,
                detail=safety.CATALOG_VERSION, priority=HumanHandoff.PRIORITY_URGENT)
            goals.close_task_commitments(conv, ConversationGoal.STATUS_HANDOFF, HumanHandoff.REASON_SAFETY)
            conv.flow['handoff_ack_sent'] = True  # queued copy, NOT human acknowledgement
            conv.save(update_fields=['flow'])
        durable.finalize_turn(witness, outcome='safety_handoff')
        if first_safety and not human_owned:
            durable.invalidate_ownership(conv, reason='safety_handoff')
            from .tier0 import render_safety_guidance
            output = Message.objects.create(organization_id=conv.organization_id,
                conversation=conv, channel_account_id=conv.channel_account_id, contact_id=conv.contact_id,
                direction='out', status='pending', author_type=Message.AUTHOR_SYSTEM,
                turn_work=work, output_ordinal=0, origin_epoch=witness.ownership_epoch,
                semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE, operation_key=f'safety:{work.pk}',
                body=render_safety_guidance(assessment))
            handoff.guidance_message = output
            handoff.guidance_epoch = conv.ownership_epoch
            handoff.save(update_fields=['guidance_message', 'guidance_epoch'])
        if human_owned:
            _event('WHILE_HUMAN_OWNED', classification=assessment.classification)
    return 'safety_handoff'


def guidance_authorized(message, conversation):
    """No generic system/urgent bypass. Another epoch always revokes this grant."""
    if (message.semantic_type != Message.SEMANTIC_SAFETY_GUIDANCE
            or message.author_type != Message.AUTHOR_SYSTEM or message.output_ordinal != 0
            or not message.turn_work_id or message.operation_key != f'safety:{message.turn_work_id}'):
        return False
    from .tier0 import render_safety_guidance
    if message.body not in tuple(render_safety_guidance(safety.SafetyAssessment(
            safety.URGENT, media_uninterpreted=media)) for media in (False, True)):
        return False
    return HumanHandoff.objects.for_organization(message.organization_id).filter(
        conversation=conversation, guidance_message=message,
        guidance_epoch=conversation.ownership_epoch, reason_code=HumanHandoff.REASON_SAFETY,
        source_turn_id=message.turn_work_id, source_message_id=message.turn_work.anchor_message_id,
        source_turn__status=TurnWork.COMPLETED, source_turn__outcome_code='safety_handoff',
        source_turn__ownership_epoch=message.origin_epoch).exists()


def pending_signal(conversation):
    return automation_enabled() and Message.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, direction='in', status='pending',
        semantic_type=Message.SEMANTIC_SAFETY_SIGNAL).exists()


def retain_interrupted_safety(conversation, work):
    """A staff takeover must not lose safety in the work it fences.

    Caller holds B3 ownership lock; this records only Inbox evidence, never
    publishes or revives the cancelled work. Recovery remains B3's authority.
    """
    if not automation_enabled():
        return
    from .turn_context import build_turn_context
    members = Message.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, turn_work=work, direction='in').order_by('created_at', 'id')
    context = build_turn_context(conversation, members, now=work.context_at)
    assessment = safety.assess_context(conversation, context)
    if assessment.classification != safety.NO_SIGNAL:
        _record(conversation, work, assessment)


@transaction.atomic
def receive_safety(message):
    """Webhook fast path under existing Conversation lock; DB only, never LLM/HTTP.

    Active W1 keeps fixed membership. Its finalizer defers and W2 processes the
    signal. B4 refuses commercial admission while that signal is pending.
    """
    if not automation_enabled() or message.status == 'discarded':
        return
    from .turn_context import build_turn_context
    conv = Conversation.objects.select_for_update().get(
        pk=message.conversation_id, organization_id=message.organization_id)
    assessment = safety.assess_context(conv, build_turn_context(conv, [message]))
    if assessment.classification == safety.NO_SIGNAL:
        return
    message.semantic_type = Message.SEMANTIC_SAFETY_SIGNAL
    message.available_at = timezone.now()
    message.save(update_fields=['semantic_type', 'available_at'])
    if TurnWork.objects.filter(conversation=conv, status__in=TurnWork.NON_TERMINAL).exists():
        return
    # B9: this DB/approved-template fast path is not a planner. Reuse the B3
    # membership/token primitive but complete it inside THIS transaction. It
    # cannot leave a second committed PROCESSING work while the org is busy.
    # Do not take Organization after Conversation (the planner lock order).
    witness = durable._claim_turn_locked(conv)
    if witness:
        # Reevaluate the actual fixed membership, not the single-event preview.
        assessment = safety.assess_context(conv, durable.context_for_work(witness))
        finalize_safety(witness, assessment)
        if not TurnWork.objects.filter(pk=witness.turn_work_id,
                status=TurnWork.COMPLETED, outcome_code='safety_handoff').exists():
            raise RuntimeError('Inline safety must complete atomically')


def acknowledge(conversation, actor):
    """Called only by the authenticated/RBAC claim action under its row lock."""
    if actor.organization_id != conversation.organization_id or actor.is_service_account:
        raise ValueError('Handoff acknowledgement requires staff in the same organization')
    handoff = active_handoff(conversation)
    if handoff and handoff.acknowledged_at is None:
        handoff.acknowledged_by = actor
        handoff.acknowledged_at = timezone.now()
        handoff.claimed_by = actor
        handoff.claimed_at = handoff.acknowledged_at
        handoff.save(update_fields=['acknowledged_by', 'acknowledged_at', 'claimed_by', 'claimed_at'])
        _event('ACKNOWLEDGED', acknowledged_latency_seconds=(handoff.acknowledged_at - handoff.created_at).total_seconds())


def observe_handoffs():
    """Low-cardinality snapshot; no transcript, phone, pet or conversation labels."""
    from django.db.models import Count, Min
    now = timezone.now()
    rows = HumanHandoff.objects.filter(resolved_at__isnull=True).values('priority').annotate(
        count=Count('pk'), oldest=Min('created_at'))
    snapshot = {'queue': {row['priority']: {'count': row['count'],
        'oldest_age_seconds': max(0, (now - row['oldest']).total_seconds())} for row in rows},
        'guidance': dict(Message.objects.filter(semantic_type=Message.SEMANTIC_SAFETY_GUIDANCE,
            direction='out').values('status').annotate(count=Count('pk')).values_list('status', 'count'))}
    _event('SNAPSHOT', **snapshot)
    return snapshot
