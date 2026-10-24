"""Directed assignment checks, unique receipts and a disposable local PostgreSQL DB."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

out = Path(__file__).resolve().parent
root = out.parents[2]
kind, tag, *labels = sys.argv[1:]
assert kind in ('frontend', 'backend', 'build', 'lint')
assert tag.replace('-', '').isalnum()
receipt = out/f'{kind}-{tag}.json'
assert not receipt.exists(), 'Never overwrite a receipt'
start = time.monotonic()
code = 1
result = dict(kind=kind, labels=labels, working_database_migrated=False)
with (out/f'{kind}-{tag}.log').open('w', encoding='utf-8') as log:
    if kind == 'backend':
        sys.path.insert(0, str(root/'backend'))
        os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        os.environ['SENTRY_DSN'] = ''
        import django
        from django.conf import settings
        database = settings.DATABASES['default']
        assert database['HOST'] in ('127.0.0.1', 'localhost')
        assert database['ENGINE'] == 'django.db.backends.postgresql'
        assert settings.CACHES['default']['BACKEND'] == 'django.core.cache.backends.locmem.LocMemCache'
        database.setdefault('TEST', {})['NAME'] = name = 'test_inbox_asn01_'+uuid4().hex[:12]
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                django.setup()
                from django.core.management import call_command
                call_command('test', *labels, verbosity=2, interactive=False, keepdb=False, failfast=False)
                code = 0
            except SystemExit as error:
                code = error.code or 0
            except Exception:
                import traceback
                traceback.print_exc()
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)', [name])
            remains = cursor.fetchone()[0]
        connection.close()
        result.update(test_database=name, test_database_remains=remains)
        code = code or int(remains)
    else:
        command = ['rtk', 'proxy', 'node']
        if kind == 'frontend':
            command += ['node_modules/vitest/vitest.mjs', 'run', *labels, '--fileParallelism=false',
                '--reporter=default', '--reporter=json', '--outputFile='+str(out/f'vitest-{tag}.json')]
        elif kind == 'build':
            command += ['node_modules/vite/bin/vite.js', 'build']
        else:
            command += ['node_modules/eslint/bin/eslint.js', 'src/pages/inbox/index.jsx',
                'src/pages/inbox/ThreadAssignment.jsx', 'src/pages/inbox/index.assignment.test.jsx',
                'src/pages/inbox/ThreadAssignment.test.jsx', 'src/api/inbox.js',
                '--format=json', '--output-file='+str(out/f'lint-report-{tag}.json')]
        env = os.environ.copy()
        env.pop('SENTRY_AUTH_TOKEN', None)
        process = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, env=env, timeout=300)
        code = process.returncode
        result.update(command=command, sentry_upload_disabled=True)
result.update(exit_code=code, elapsed_s=time.monotonic()-start)
receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((out/f'{kind}-{tag}.log').read_text(encoding='utf-8').splitlines()[-18:]))
raise SystemExit(code)
