"""Independent PostgreSQL observer/claimer for E4 selector race tests."""
import json
import os
import sys
from datetime import datetime


def emit(kind, **data):
    print('B9A_' + kind + ' ' + json.dumps(data, default=str), flush=True)


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections
    from apps.agent import durable, worker
    from apps.agent.models import Conversation, LLMCall
    from apps.channels.models import Message

    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1', 'localhost')
            or config['ENGINE'] != 'django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all()
    connections.databases['default'].update(config)
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        backend_pid = cursor.fetchone()[0]
    emit('READY', pid=os.getpid(), backend_pid=backend_pid)
    witness = None
    for line in sys.stdin:
        command = json.loads(line)
        action = command['action']
        clock = datetime.fromisoformat(command['now']) if command.get('now') else None
        if action == 'observe':
            ids = list(worker._pending_conversation_candidates(now=clock))
            orgs = dict(Conversation.objects.filter(pk__in=ids).values_list('pk', 'organization_id'))
            emit('OBSERVED', ids=ids, org_ids=[orgs[x] for x in ids],
                 admissions=LLMCall.objects.count(),
                 active={str(o): durable.active_org_work(o).count() for o in orgs.values()})
        elif action == 'claim':
            witness = durable.claim_turn(command['conversation'], eligible_at=clock)
            emit('CLAIMED', claimed=witness is not None,
                 members=list(Message.objects.filter(turn_work_id=witness.turn_work_id)
                              .values_list('pk', flat=True)) if witness else [],
                 admissions=LLMCall.objects.count(),
                 active={str(o): durable.active_org_work(o).count() for o in
                         Conversation.objects.values_list('organization_id', flat=True).distinct()})
        elif action == 'finalize':
            outcome = durable.finalize_turn(witness) if witness else None
            emit('FINALIZED', outcome=outcome, admissions=LLMCall.objects.count())
            witness = None
        elif action == 'exit':
            emit('RESULT', admissions=LLMCall.objects.count())
            break
        else:
            raise RuntimeError(f'Unknown test action {action}')
    connections.close_all()


if __name__ == '__main__':
    main()
