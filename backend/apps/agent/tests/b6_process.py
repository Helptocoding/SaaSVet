"""B6 process crash/CAS probe restricted to PostgreSQL test databases."""
import json
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B6 probe requires a test database')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import matter_binding as binding
    from apps.agent.models import Conversation, ConversationGoal
    from apps.agent.turn_context import build_turn_context
    from apps.channels.models import Message
    mode, conv_id, goal_id, revision, message_id, pet_id = sys.argv[1:]
    conv = Conversation.objects.select_related('contact', 'organization', 'channel_account').get(pk=conv_id)
    goal = ConversationGoal.objects.get(pk=goal_id)
    context = build_turn_context(conv, [Message.objects.get(pk=message_id)])
    print('B6_READY', flush=True)
    sys.stdin.readline()
    def correct():
        binding.change(goal, conv, {'pet': int(pet_id)}, context=context,
            message_id=int(message_id), expected_revision=int(revision), correction=True)
    if mode == 'before_commit':
        with transaction.atomic():
            correct()
            print('B6_CHANGED', flush=True)
            sys.stdin.readline()  # parent kills this process before COMMIT
        raise RuntimeError('Crash barrier unexpectedly released')
    try:
        correct()
        if mode == 'after_commit':
            print('B6_COMMITTED', flush=True)
            sys.stdin.readline()
            raise RuntimeError('Crash barrier unexpectedly released')
        result = {'won': True, 'revision': goal.binding_revision}
    except binding.BindingConflict:
        result = {'won': False}
    print('B6_RESULT ' + json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
