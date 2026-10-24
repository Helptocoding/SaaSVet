"""Finite directed checks. Never touches the ordinary DB schema or providers."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

out = Path(__file__).resolve().parent
root = out.parents[2]
kind, tag = sys.argv[1:3]
labels = sys.argv[3:]
receipt = out / f'{kind}-{tag}.json'
assert not receipt.exists() and not receipt.with_suffix('.log').exists(), 'Never overwrite evidence'
sys.path.insert(0, str(root / 'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
from django.conf import settings
database = settings.DATABASES['default']
assert database['HOST'] in ('localhost', '127.0.0.1')
assert database['ENGINE'] == 'django.db.backends.postgresql'
settings.MEDIA_BACKEND = 'local'
settings.INBOX_MEDIA_ALLOW_LOCAL = True
settings.INBOX_MEDIA_ENABLED = False
settings.INBOX_MEDIA_ACCESS_HOLD = False
settings.INBOX_MEDIA_REVOCATION_ROOT = ''
settings.INBOX_MEDIA_OPS_OWNER = ''
settings.DISCORD_WEBHOOK_URL = ''
settings.INBOX_MEDIA_ROOT = str(out / 'runtime' / 'private-media')
settings.INBOX_MEDIA_SPOOL_ROOT = str(out / 'runtime' / 'saaslyvet-inbox-media-spool')
if kind == 'test':
    database.setdefault('TEST', {})['NAME'] = name = 'test_inbox_policy_' + uuid4().hex[:12]
started = time.monotonic()
result = dict(kind=kind, labels=labels, ordinary_database_migrated=False, provider_network=False)
code = 1
with receipt.with_suffix('.log').open('x', encoding='utf-8') as stream:
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            django.setup()
            from django.core.management import call_command
            from unittest.mock import patch
            # Nested test mocks can replace these guards; accidental real HTTP cannot.
            with patch('requests.sessions.Session.request', side_effect=AssertionError('Provider HTTP forbidden in local evidence')):
                if kind == 'migration':
                    call_command('makemigrations', 'channels', name='media_retention_policy', interactive=False)
                elif kind == 'test':
                    call_command('test', *labels, interactive=False, verbosity=2, keepdb=False)
                elif kind == 'check':
                    call_command('makemigrations', check=True, dry_run=True, interactive=False)
                    call_command('check')
                else:
                    raise ValueError('Unknown check kind')
            code = 0
        except SystemExit as error:
            code = error.code or 0
        except Exception:
            import traceback
            traceback.print_exc()
if kind == 'test':
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)', [name])
        remains = cursor.fetchone()[0]
    connection.close()
    result.update(test_database=name, test_database_remains=remains)
    code = code or int(remains)
result.update(exit_code=code, elapsed_s=round(time.monotonic()-started, 3))
receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
print('\n'.join(receipt.with_suffix('.log').read_text(encoding='utf-8').splitlines()[-32:]))
raise SystemExit(code)
