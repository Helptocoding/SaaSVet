"""Independent process/connection; real claim and B9A controlled provider wire."""
import json
import os
import sys
from dataclasses import asdict

from .b9a_process import emit, barrier


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, connection
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('localhost', '127.0.0.1')
            or config['ENGINE'] != 'django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import durable, worker
    from apps.agent.models import Conversation, TurnWork, LLMCall
    from .b9a_harness import ApplicationHarness, answer
    mode, conversation_id = sys.argv[1:]
    conv = Conversation.objects.select_related('channel_account').get(pk=conversation_id)
    harness = ApplicationHarness(conv.channel_account, llm=[answer()])
    witness, lost = None, False
    with harness.running():
        barrier('READY')
        if mode == 'before_claim': barrier('BOUNDARY')

        def sql_boundary(execute, sql, params, many, context):
            if mode == 'acquire_atomic' and sql.startswith('UPDATE "agent_turnwork"'):
                barrier('BOUNDARY')
            if mode == 'after_response' and sql.startswith('INSERT INTO "channels_message"'):
                barrier('BOUNDARY')
            return execute(sql, params, many, context)

        def wire_boundary(kind, event):
            if mode == 'during_llm' and kind == 'llm':
                barrier('BOUNDARY')
        harness.callback = wire_boundary
        with connection.execute_wrapper(sql_boundary):
            witness = durable.claim_turn(conv.pk)
            if witness is not None:
                if mode == 'after_claim': barrier('BOUNDARY')
                if mode in ('run', 'during_llm', 'after_response'):
                    try:
                        worker._run_turn(witness)
                    except durable.OwnershipLost:
                        lost = True
        emit('RESULT', admitted=witness is not None, lost=lost,
             capacity=harness.capacity,
             witness=json.loads(json.dumps(asdict(witness), default=str)) if witness else None,
             active=durable.active_org_work(conv.organization_id).count(),
             calls=LLMCall.objects.filter(organization_id=conv.organization_id).count(),
             wire=[{k: e.get(k) for k in ('boundary', 'in_atomic', 'admission_observed',
                   'concurrency_active', 'concurrency_observed')} for e in harness.wire])


if __name__ == '__main__':
    main()
