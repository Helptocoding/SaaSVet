"""Directed tests in a disposable local PostgreSQL database; never migrate the working DB."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

out = Path(__file__).resolve().parent
root = out.parents[2]
sys.path.insert(0, str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
from django.conf import settings

database = settings.DATABASES['default']
assert database['HOST'] in ('localhost', '127.0.0.1')
assert database['ENGINE'] == 'django.db.backends.postgresql'
name = 'test_inbox_win01_' + uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = name
labels = [
    'apps.agent.tests.test_inbox_session_window',
    'apps.agent.tests.test_inbox_threads.AgentProcessingTests',
    'apps.agent.tests.test_inbox_threads.ArchivedThreadTests',
    'apps.agent.tests.test_inbox_thread_around.ThreadAroundTests.test_regular_payload_and_current_metadata_remain_compatible',
    'apps.agent.tests.test_inbox_thread_around.ThreadAroundTests.test_window_queries_and_materialization_are_bounded',
    'apps.agent.tests.test_inbox_retry.InboxRetryTests.test_window_closed_or_unknown_returns_call_without_changes',
    'apps.agent.tests.test_b4_sender.B4SenderTests.test_window_closed_after_claim_blocks_admission',
]
start, code = time.monotonic(), 0
with (out/'backend.log').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            import django
            django.setup()
            from django.core.management import call_command
            call_command('test', *labels, verbosity=2, interactive=False, keepdb=False)
        except SystemExit as error:
            code = error.code or 0
        except Exception:
            import traceback
            traceback.print_exc()
            code = 1
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)', [name])
    remains = cursor.fetchone()[0]
connection.close()
result = dict(exit_code=code, labels=labels, elapsed_s=time.monotonic()-start,
              test_database=name, test_database_remains=remains)
(out/'backend.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((out/'backend.log').read_text(encoding='utf-8').splitlines()[-22:]))
raise SystemExit(code or int(remains))
