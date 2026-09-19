"""Independent PostgreSQL preparation/race/crash probe. Test databases only."""
import json
import os
import sys
from uuid import UUID
from unittest.mock import patch


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B7A process requires isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import operations, durable
    from apps.agent.models import ConversationOperation, ContactIdentity, Conversation
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    witness = args.pop('witness')
    witness['lease_token'] = UUID(witness['lease_token'])
    args['witness'] = durable.OwnershipWitness(**witness)
    print('B7A_READY', flush=True)
    sys.stdin.readline()
    original = ConversationOperation.save
    def before_save(obj, *a, **kw):
        print('B7A_VALIDATED', flush=True)
        sys.stdin.readline()
        return original(obj, *a, **kw)
    try:
        if mode == 'identity':
            contact = ContactIdentity.objects.get(conversations__pk=witness['conversation_id'])
            contact.auto_rematch_blocked = True
            contact.save(update_fields=['auto_rematch_blocked'])
            result = {'changed': True}
        elif mode == 'takeover':
            with transaction.atomic():
                conv = Conversation.objects.select_for_update().get(pk=witness['conversation_id'])
                durable.invalidate_ownership(conv, reason='test_takeover')
                conv.state = Conversation.STATE_HUMAN_ACTIVE
                conv.save(update_fields=['state'])
            result = {'changed': True}
        else:
            if mode in ('before_persist', 'hold_preparation'):
                with patch.object(ConversationOperation, 'save', before_save):
                    operation = operations.prepare_operation(**args)
            else:
                operation = operations.prepare_operation(**args)
            if mode == 'after_persist':
                print('B7A_COMMITTED', flush=True)
                sys.stdin.readline()
            result = {'pk': operation.pk}
    except (operations.PreparationDenied, durable.OwnershipLost) as exc:
        result = {'denied': str(exc)}
    print('B7A_RESULT ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
