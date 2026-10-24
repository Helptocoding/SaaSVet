"""Directed schema checks; normal database is read-only, tests use disposable DBs."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

out = Path(__file__).resolve().parent
root = out.parents[2]
kind, tag, *labels = sys.argv[1:]
assert kind in ('generate', 'backend', 'drift')
assert tag.replace('-', '').isalnum()
receipt = out/f'{kind}-{tag}.json'
assert not receipt.exists(), 'Do not overwrite evidence'
sys.path.insert(0, str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
from django.conf import settings
database = settings.DATABASES['default']
assert database['HOST'] in ('127.0.0.1', 'localhost')
assert database['ENGINE'] == 'django.db.backends.postgresql'
assert settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
if kind == 'backend':
    prefix = 'test_channels_compat_' if tag == 'compat' else 'test_inbox_rpl01_'
    database.setdefault('TEST', {})['NAME'] = name = prefix+uuid4().hex[:12]
start = time.monotonic()
code = 1
result = dict(kind=kind, labels=labels, working_database_migrated=False)
with (out/f'{kind}-{tag}.log').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            django.setup()
            from django.core.management import call_command
            if kind == 'backend':
                call_command('test', *labels, verbosity=2, interactive=False, keepdb=False, failfast=False)
            else:
                if kind == 'generate':
                    call_command('makemigrations', 'channels', name='message_reply_to', interactive=False)
                    with (out/f'migration-{tag}.sql').open('w', encoding='utf-8') as sql:
                        call_command('sqlmigrate', 'channels', '0016', stdout=sql)
                call_command('makemigrations', check=True, dry_run=True, interactive=False)
                call_command('check')
            code = 0
        except SystemExit as error:
            code = error.code or 0
        except Exception:
            import traceback
            traceback.print_exc()
if kind == 'backend':
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)', [name])
        remains = cursor.fetchone()[0]
    connection.close()
    result.update(test_database=name, test_database_remains=remains)
    code = code or int(remains)
result.update(exit_code=code, elapsed_s=time.monotonic()-start)
receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((out/f'{kind}-{tag}.log').read_text(encoding='utf-8').splitlines()[-20:]))
raise SystemExit(code)
