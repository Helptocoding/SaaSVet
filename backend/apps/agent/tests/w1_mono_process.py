"""Bounded barriers around real ingest/claim transactions on local test PG."""
import json
import os
import sys
from unittest.mock import patch


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connection, connections
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('Isolated local test PostgreSQL required')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import durable, services
    from apps.agent.models import Conversation
    from apps.channels.models import ChannelAccount, Message
    mode, conv_id, key = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    conv = Conversation.objects.select_related('channel_account', 'contact').get(pk=conv_id)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        backend_pid = cursor.fetchone()[0]

    def emit(kind, **data):
        print('B9A_' + kind + ' ' + json.dumps(
            dict(pid=os.getpid(), backend_pid=backend_pid, **data)), flush=True)

    def barrier(**data):
        emit('BOUNDARY', mode=mode, **data)
        if not sys.stdin.readline():
            raise RuntimeError('Controller closed barrier')

    emit('READY')
    sys.stdin.readline()
    if mode.startswith('ingest'):
        def ingest():
            return services.ingest_inbound_message(conv.channel_account, wamid=key,
                wa_id=conv.contact.external_id, body='mejor el viernes')
        original_save, original_extend = Message.save, services._extend_quiet_window

        def before_save(message, *args, **kwargs):
            if message.direction == 'in':
                barrier(stage='before_persist')
            return original_save(message, *args, **kwargs)

        def extend(conversation, now):
            if mode == 'ingest_after_save':
                barrier(stage='after_persist_before_deadlines')
            original_extend(conversation, now)
            if mode in ('ingest_hold', 'ingest_after_deadlines'):
                barrier(stage='after_deadlines_before_commit')

        with patch.object(Message, 'save', before_save if mode == 'ingest_before_save' else original_save), patch.object(
                services, '_extend_quiet_window', extend):
            msg = ingest()
        if mode == 'ingest_lost_commit':
            barrier(stage='committed_response_lost')
        emit('RESULT', message=msg.pk if msg else None)
    else:
        original = durable._claim_turn_locked

        def locked(conversation, **kwargs):
            if mode == 'claim_locks':
                barrier(stage='after_locks_before_work')
            witness = original(conversation, **kwargs)
            if mode == 'claim_hold':
                barrier(stage='after_claim_before_commit', work=witness.turn_work_id if witness else None)
            return witness

        with patch.object(durable, '_claim_turn_locked', locked):
            witness = durable.claim_turn(conv_id)
        lost = False
        if mode == 'claim_live' and witness:
            barrier(stage='after_claim_commit', work=witness.turn_work_id)
            try:
                durable.finalize_turn(witness, outputs=[{'body': 'worker publication'}])
            except durable.OwnershipLost:
                lost = True
        emit('RESULT', work=witness.turn_work_id if witness else None,
             token=str(witness.lease_token) if witness else None, lost=lost)
    connections.close_all()


if __name__ == '__main__':
    main()
