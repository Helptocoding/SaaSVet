"""Finite phase-3 checks; no ordinary database migration or provider HTTP."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

parser = argparse.ArgumentParser()
parser.add_argument('kind', choices=['backend', 'drift', 'migration', 'frontend', 'build', 'lint'])
parser.add_argument('tag')
parser.add_argument('labels', nargs='*')
args = parser.parse_args()
out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / f'{args.kind}-{args.tag}.json'
assert not receipt.exists() and not receipt.with_suffix('.log').exists(), 'Never overwrite evidence'
result = dict(kind=args.kind, labels=args.labels, working_database_migrated=False)
started, code = time.monotonic(), 1
if args.kind in ('frontend', 'build', 'lint'):
    if args.kind == 'frontend':
        report = out / f'frontend-{args.tag}-vitest.json'
        command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run', *args.labels,
                   '--maxWorkers=1', '--reporter=json', f'--outputFile={report}']
    elif args.kind == 'build':
        command = ['rtk', 'npm', 'run', 'build']
    else:
        command = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js', *args.labels]
    with receipt.with_suffix('.log').open('w', encoding='utf-8') as stream:
        code = subprocess.run(command, cwd=root / 'frontend', stdout=stream, stderr=subprocess.STDOUT).returncode
    result['command'] = command
    if args.kind == 'frontend' and report.exists():
        payload = json.loads(report.read_text(encoding='utf-8'))
        result.update(vitest_report=report.name, passed=payload['numPassedTests'], failed=payload['numFailedTests'])
else:
    sys.path.insert(0, str(root / 'backend'))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    os.environ['SENTRY_DSN'] = ''
    import django
    from django.conf import settings
    database = settings.DATABASES['default']
    assert database['HOST'] in ('127.0.0.1', 'localhost') and database['ENGINE'] == 'django.db.backends.postgresql'
    assert settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
    settings.INBOX_MEDIA_ENABLED = False  # Only explicit test overrides may download.
    settings.MEDIA_BACKEND = 'local'
    settings.INBOX_MEDIA_ALLOW_LOCAL = True
    settings.INBOX_MEDIA_ROOT = str(out / 'runtime' / 'private-media')
    settings.INBOX_MEDIA_SPOOL_ROOT = str(out / 'runtime' / 'saaslyvet-inbox-media-spool')
    if args.kind == 'backend':
        database.setdefault('TEST', {})['NAME'] = name = 'test_inbox_phase3_' + uuid4().hex[:12]
        os.environ['INBOX_SYNC_PLAN_OUTPUT'] = str(out / f'query-plan-{args.tag}.json')
    with receipt.with_suffix('.log').open('w', encoding='utf-8') as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                django.setup()
                from django.core.management import call_command
                if args.kind == 'backend':
                    call_command('test', *args.labels, verbosity=2, interactive=False, keepdb=False, failfast=False)
                elif args.kind == 'migration':
                    call_command('makemigrations', 'channels', name='message_media', interactive=False)
                else:
                    call_command('makemigrations', check=True, dry_run=True, interactive=False)
                    call_command('check')
                code = 0
            except SystemExit as error:
                code = error.code or 0
            except Exception:
                import traceback
                traceback.print_exc()
    if args.kind == 'backend':
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)', [name])
            remains = cursor.fetchone()[0]
        connection.close()
        result.update(test_database=name, test_database_remains=remains)
        code = code or int(remains)
result.update(exit_code=code, elapsed_s=time.monotonic() - started)
receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
print('\n'.join(receipt.with_suffix('.log').read_text(encoding='utf-8').splitlines()[-24:]))
raise SystemExit(code)
