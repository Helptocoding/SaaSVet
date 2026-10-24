"""Read-only wait diagnosis; no query cancellation or application writes."""
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute('''SELECT state, wait_event_type, wait_event,
        EXTRACT(EPOCH FROM clock_timestamp()-query_start)::int
        FROM pg_stat_activity WHERE datname LIKE %s''', ['test_inbox_fil01_%'])
    print(json.dumps(cursor.fetchall()))
connection.close()
