"""Independent PostgreSQL consent/crash probes; refuses non-test databases."""
import json
import os
import sys
from dataclasses import asdict
from uuid import UUID
from unittest.mock import patch


def barrier(name):
    print('B7B_' + name, flush=True)
    sys.stdin.readline()


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B7B probes require an isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_B7B_CONSENT_ENABLED = True
    from apps.agent import durable, operation_consent as consent, matter_binding, sender
    from apps.agent.models import ConversationOperation, Conversation, ConversationGoal
    from apps.channels.providers import SendResult
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    witness = args['witness']
    witness['lease_token'] = UUID(witness['lease_token'])
    witness = durable.OwnershipWitness(**witness)
    barrier('READY')
    result = {}
    try:
        if mode in ('correction', 'hold_correction'):
            with transaction.atomic():
                conv, work = durable.lock_witness(witness)
                goal = ConversationGoal.objects.get(pk=args['goal_id'])
                matter_binding.change(goal, conv, {'pet': args['max_id']},
                    context=durable.context_for_work(witness), message_id=work.anchor_message_id,
                    expected_revision=goal.binding_revision, correction=True)
                if mode == 'hold_correction':
                    barrier('CHANGED')
            result = {'changed': True}
        elif mode in ('takeover', 'hold_takeover'):
            with transaction.atomic():
                conv = Conversation.objects.select_for_update().get(pk=witness.conversation_id)
                durable.invalidate_ownership(conv, reason='test_takeover')
                conv.state = Conversation.STATE_HUMAN_ACTIVE
                conv.save(update_fields=['state'])
                if mode == 'hold_takeover':
                    barrier('CHANGED')
            result = {'changed': True}
        elif mode == 'publish':
            op = ConversationOperation.objects.get(pk=args['operation_id'])
            durable.finalize_turn(witness, proposal_operation=op)
            barrier('PUBLISHED')
        elif mode == 'meta_accepted':
            op = ConversationOperation.objects.get(pk=args['operation_id'])
            msg = op.proposal_message
            claim = sender.claim_message(msg.pk, organization_id=op.organization_id,
                                         channel_account_id=msg.channel_account_id)
            sender.admit_dispatch(claim)
            # Controlled provider returned a valid acceptance; killed before
            # B4 finalization. No remote exactly-once guarantee is asserted.
            response = SendResult('accepted', provider_id='wamid.b7b-process')
            barrier('META_ACCEPTED')
            sender.finalize_dispatch(claim, response)
        else:
            original = consent._persist_decision
            def persist(*a, **kw):
                if mode == 'before_persist':
                    barrier('VALIDATED')
                original(*a, **kw)
                if mode in ('before_commit', 'hold_consent'):
                    barrier('UNCOMMITTED')
                if mode == 'db_error':
                    with connections['default'].cursor() as cursor:
                        cursor.execute('SELECT 1 / 0')
            if mode == 'before_evaluate':
                barrier('BEFORE_EVALUATE')
            with patch.object(consent, '_persist_decision', persist):
                result = asdict(consent.evaluate_turn(witness))
            if mode == 'after_commit':
                barrier('COMMITTED')
    except Exception as exc:
        result = {'error': type(exc).__name__, 'reason': str(exc)}
    print('B7B_RESULT ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
