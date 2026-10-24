"""PERF-03 and directly affected projection/sender tests in a disposable DB."""
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
name = 'test_inbox_perf03_'+uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = name
tag = sys.argv[1] if len(sys.argv) > 1 else 'initial'
assert tag.replace('-', '').isalnum()
suffix = '' if tag == 'initial' else '-'+tag
assert not (out/f'backend{suffix}.json').exists()
assert settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
if tag.startswith('plan'):
    plan_path = out/('query-plan.json' if tag == 'plan' else f'query-{tag}.json')
    assert not plan_path.exists(), 'Never overwrite an earlier plan receipt'
    os.environ['INBOX_SYNC_PLAN_OUTPUT'] = str(plan_path)
labels = sys.argv[2:] or ['apps.agent.tests.test_inbox_sync', 'apps.agent.tests.test_inbox_thread_pagination',
    'apps.agent.tests.test_inbox_thread_performance', 'apps.agent.tests.test_inbox_thread_around',
    'apps.agent.tests.test_inbox_read_projection', 'apps.agent.tests.test_inbox_retry',
    'apps.agent.tests.test_b4_sender']
start, code = time.monotonic(), 0
with (out/f'backend{suffix}.log').open('w', encoding='utf-8') as log:
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
(out/f'backend{suffix}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((out/f'backend{suffix}.log').read_text(encoding='utf-8').splitlines()[-18:]).encode('ascii', errors='backslashreplace').decode())
raise SystemExit(code or int(remains))
