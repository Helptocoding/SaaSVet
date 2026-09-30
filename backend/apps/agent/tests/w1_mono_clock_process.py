"""Independent ingest with a deliberately stale app clock and real DB time."""
import json
import os
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connection, connections
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('Local test PG only')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import durable, services
    from apps.agent.models import Conversation
    conv = Conversation.objects.select_related('channel_account', 'contact').get(pk=int(sys.argv[1]))
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        backend_pid = cursor.fetchone()[0]
    stale = durable.db_now() - timedelta(seconds=7)
    print('B9A_READY ' + json.dumps(dict(pid=os.getpid(), backend_pid=backend_pid,
        stale_app_time=stale.isoformat())), flush=True)
    sys.stdin.readline()
    fresh = []
    real_now = services.db_now

    def now():
        value = real_now()
        fresh.append(value)
        return value

    with patch.object(services, 'timezone', SimpleNamespace(now=lambda: stale)), patch.object(services, 'db_now', now):
        msg = services.ingest_inbound_message(conv.channel_account, wamid='clock-wait-B',
            wa_id=conv.contact.external_id, body='ordinary')
    print('B9A_RESULT ' + json.dumps(dict(pid=os.getpid(), backend_pid=backend_pid,
        message=msg.pk, fresh_db_time=fresh[-1].isoformat())), flush=True)
    connections.close_all()


if __name__ == '__main__':
    main()
