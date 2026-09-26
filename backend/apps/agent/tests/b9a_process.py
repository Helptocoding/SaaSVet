"""Independent Python/PG process exercising the same B9A application harness."""
import json
import os
import sys


def emit(kind, **values):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        backend = cursor.fetchone()[0]
    print('B9A_' + kind + ' ' + json.dumps({'pid': os.getpid(), 'backend_pid': backend, **values}), flush=True)


def barrier(kind):
    emit(kind)
    if sys.stdin.readline().strip() != 'go':
        os._exit(86)


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
    from apps.channels.models import ChannelAccount
    from .b9a_harness import ApplicationHarness, answer
    mode, channel_id = sys.argv[1:]
    harness = ApplicationHarness(ChannelAccount.objects.get(pk=channel_id), llm=[answer()])
    with harness.running():
        barrier('READY')
        def boundary(kind, event):
            if mode == 'hold_llm' and kind == 'llm':
                barrier('BOUNDARY')
            if mode == 'hold_meta' and kind == 'meta':
                barrier('BOUNDARY')
            if mode == 'accepted_lost' and kind == 'meta':
                # Provider acceptance is outside the killed worker transaction.
                # Parent observes this message before SIGKILL, without marking
                # local Message SENT or inventing a correlation ID in the DB.
                emit('EXTERNAL_ACCEPTED', provider_id='wamid.b9a.external.accepted')
                barrier('BOUNDARY')
        harness.callback = boundary
        def before_publication(execute, sql, params, many, context):
            if mode == 'hold_publication' and sql.startswith('INSERT INTO "channels_message"'):
                barrier('BOUNDARY')
            return execute(sql, params, many, context)
        with connection.execute_wrapper(before_publication):
            if mode in ('sender', 'hold_meta', 'accepted_lost'):
                harness.sender()
            elif mode == 'duplicate_http':
                harness.inbound('Pregunta por los servicios', key='wamid.b9a.process.duplicate')
            else:
                harness.worker()
        emit('RESULT', http=harness.http, calls=harness.calls,
             wire=[{'boundary': e['boundary']} for e in harness.wire])


if __name__ == '__main__':
    main()
