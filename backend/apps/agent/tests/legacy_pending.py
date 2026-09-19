"""Historical fixture writer, deliberately unavailable in production."""
import uuid
from django.utils import timezone
from apps.agent import confirmations, matter_binding
from apps.agent.turn_changes import save_local


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
