"""Independent B8A PostgreSQL processes and explicit failure boundaries."""
import json
import os
import sys
from dataclasses import asdict
from uuid import UUID, uuid4
from unittest.mock import patch


def barrier(name):
    print('B8A_' + name, flush=True)
    if sys.stdin.readline().strip() != 'go':
        # EOF/launcher termination must NEVER release an effect boundary.
        os._exit(86)


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections, transaction
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B8A probes require an isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    settings.AGENT_B7B_CONSENT_ENABLED = True
    from apps.agent import durable, operation_execution as execution, matter_binding
    from apps.agent.models import Conversation, ConversationGoal
    from apps.agent.services import ingest_inbound_message
    from .b8a_support import LocalTestAdapter, enabled_test_adapter
    mode, raw = sys.argv[1:]
    args = json.loads(raw)
    if django.get_version() != args['django_version']:
        raise RuntimeError('Probe dependencies differ from coordinator')
    witness = args['witness']
    witness['lease_token'] = UUID(witness['lease_token'])
    witness = durable.OwnershipWitness(**witness)
    context = execution.ExecutionContext(witness, args['contact_id'], 'create_appointment')
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT set_config(%s, %s, false)', ['application_name', 'b8a_' + str(os.getpid())])
    barrier('READY')
    result = {}
    try:
        if mode in ('correction', 'hold_correction', 'revocation', 'hold_revocation', 'takeover', 'hold_takeover'):
            with transaction.atomic():
                conv = Conversation.objects.select_for_update().get(pk=witness.conversation_id)
                if mode.endswith('correction'):
                    from apps.agent.turn_context import build_turn_context
                    incoming = ingest_inbound_message(conv.channel_account, wamid='wamid.' + uuid4().hex,
                        wa_id=conv.contact.external_id, body='Mejor para Max', raw={})
                    goal = ConversationGoal.objects.get(pk=args['goal_id'])
                    matter_binding.change(goal, conv, {'pet': args['max_id']},
                        context=build_turn_context(conv, [incoming]), message_id=incoming.pk,
                        expected_revision=goal.binding_revision, correction=True)
                elif mode.endswith('takeover'):
                    durable.invalidate_ownership(conv, reason='test_takeover')
                    conv.state = Conversation.STATE_HUMAN_ACTIVE
                    conv.save(update_fields=['state'])
                else:
                    ingest_inbound_message(conv.channel_account, wamid='wamid.' + uuid4().hex,
                        wa_id=conv.contact.external_id, body='No, olvida la propuesta', raw={})
                if mode.startswith('hold_'):
                    barrier('CHANGED')
            result = {'changed': True}
        else:
            adapter = LocalTestAdapter()
            original_execute = adapter.execute
            def effect(operation, ctx):
                if mode == 'before_effect':
                    barrier('BEFORE_EFFECT')
                if mode in ('external_commit_crash', 'timeout_after_commit'):
                    # Deliberate out-of-contract failure injection, NOT a real
                    # supported external adapter. It reproduces committed domain
                    # evidence surviving the worker's uncommitted local ledger.
                    import psycopg
                    with psycopg.connect(dbname=config['NAME'], host=config['HOST'], port=config['PORT'],
                            user=config['USER'], password=config['PASSWORD']) as external:
                        external.execute('INSERT INTO b8a_test_effect VALUES (%s, %s, %s, %s, statement_timestamp())',
                            [operation.operation_key, operation.parameters_digest, operation.organization_id, uuid4()])
                    if mode == 'external_commit_crash':
                        barrier('EFFECT_COMMITTED')
                    else:
                        raise TimeoutError('Injected loss after independently committed test effect')
                if mode == 'timeout_absent':
                    raise TimeoutError('Injected unknown result')
                return original_execute(operation, ctx)
            adapter.execute = effect
            original_record = execution._record
            def record(operation, status, *a, **kw):
                if status == 'SUCCEEDED' and mode == 'db_error':
                    with connections['default'].cursor() as cursor:
                        cursor.execute('SELECT 1 / 0')
                original_record(operation, status, *a, **kw)
                if status == 'SUCCEEDED' and mode == 'hold_effect':
                    barrier('EFFECT_PENDING')
            if mode == 'before_lock':
                barrier('BEFORE_LOCK')
            print('B8A_ATTEMPTING', flush=True)
            with enabled_test_adapter(adapter), patch.object(execution, '_record', record):
                result = asdict(execution.execute_authorized_operation(UUID(args['operation_key']), context))
            if mode == 'after_commit':
                barrier('COMMITTED')
    except Exception as exc:
        result = {'error': type(exc).__name__}
    print('B8A_RESULT ' + json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
