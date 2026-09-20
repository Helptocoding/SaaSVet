"""Historical fixture writer, deliberately unavailable in production."""
import uuid
from django.utils import timezone
from apps.agent import confirmations, matter_binding
from apps.agent.turn_changes import save_local


def legacy_is_confirmable(conversation, pending):
    """Retired pre-B7B matcher, exclusively for opted-in inactive components."""
    from apps.channels.models import Message
    if not confirmations.binding_is_current(conversation, pending):
        return False
    return bool((pending or {}).get('proposal_id') and (pending or {}).get('proposal_message_id')
        and Message.objects.filter(pk=pending['proposal_message_id'], conversation=conversation,
            direction='out', semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=pending['proposal_id']).exclude(status__in=('discarded', 'failed')).exists())


def seed_pending(conversation, *, tool, args, paraphrase):
    flow = dict(conversation.flow or {})
    flow['pending_action'] = {
        'proposal_id': uuid.uuid4().hex, 'tool': tool,
        'operation_family': confirmations.operation_family(tool), 'args': args,
        'paraphrase': paraphrase,
        'idempotency_key': args.get('idempotency_key') or uuid.uuid4().hex,
        'proposed_at': timezone.now().isoformat(),
        'expires_at': (timezone.now() + confirmations.PENDING_TTL).isoformat(),
    }
    goal = matter_binding.current_goal(conversation)
    if goal and matter_binding.metadata(goal):
        flow['pending_action']['binding'] = matter_binding.snapshot(goal)
    conversation.flow = flow
    save_local(conversation, update_fields=['flow'])
    return paraphrase
