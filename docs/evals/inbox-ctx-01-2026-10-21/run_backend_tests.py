"""Directed context tests in a disposable local PostgreSQL database."""
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
name = 'test_inbox_ctx01_'+uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = name
labels = ['apps.agent.tests.test_inbox_context',
    'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_another_org_gets_404',
    'apps.agent.tests.test_inbox_threads.ArchivedThreadTests.test_it_shows_with_the_explicit_flag_and_offers_no_actions',
    'apps.agent.tests.test_inbox_read_projection.InboxReadProjectionTests.test_opening_projection_excludes_closed_history_discarded_and_outbound']
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
print('\n'.join((out/'backend.log').read_text(encoding='utf-8').splitlines()[-24:]))
raise SystemExit(code or int(remains))
