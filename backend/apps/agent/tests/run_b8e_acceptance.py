"""Local PostgreSQL only. No production flags or database changes."""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True, choices=('unit', 'processes', 'corpus', 'baseline', 'domains', 'targeted', 'checks'))
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ids-file', type=Path)
    args = parser.parse_args()
    if not args.database.startswith(('test_b8e_', 'test_b8d_', 'test_b8c_', 'test_b8b_')) or not os.environ.get('DATABASE_URL'):
        parser.error('Explicit isolated local database required')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.core.management import call_command
    from .b8e_runner import baseline_ids
    if connection.vendor != 'postgresql' or connection.settings_dict['HOST'] not in ('localhost', '127.0.0.1'):
        parser.error('Local PostgreSQL required')
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = args.database
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher', *settings.PASSWORD_HASHERS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ['B8E_RESULTS_PATH'] = str(args.output.with_suffix('.results.json'))
    # Preserve historical subprocess journals without changing their tests.
    for phase in ('B8B', 'B8C', 'B8D'):
        os.environ[phase + '_RESULTS_PATH'] = str(args.output.with_suffix('.results.json'))
    code, start = 0, time.monotonic()
    with args.output.with_suffix('.log').open('w', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        for logger in [logging.getLogger()]+list(logging.Logger.manager.loggerDict.values()):
            if isinstance(logger, logging.Logger):
                for handler in logger.handlers:
                    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                        handler.setStream(log)
        try:
            if args.suite == 'checks':
                connection.close()
                connection.settings_dict['NAME'] = args.database
                call_command('migrate', interactive=False)
                call_command('check')
                call_command('makemigrations', check=True, dry_run=True)
                call_command('migrate', check=True)
                with connection.cursor() as c:
                    c.execute('SELECT version()')
                    print(c.fetchone()[0])
                    c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='patients_petregistrationeffect'::regclass ORDER BY conname")
                    print(json.dumps(c.fetchall()))
            else:
                selected = {'unit': ['apps.agent.tests.test_b8e_registration'],
                    'processes': ['apps.agent.tests.test_b8e_processes'],
                    'corpus': ['apps.agent.tests.test_b8e_corpus'],
                    'domains': ['apps.patients', 'apps.imports', 'apps.medical_records', 'apps.appointments', 'apps.dashboard']} .get(args.suite)
                if args.suite == 'baseline': selected = sorted(baseline_ids())
                if args.suite == 'targeted': selected = json.loads(args.ids_file.read_text(encoding='utf-8'))
                call_command('test', *selected, keepdb=True, interactive=False, verbosity=2, parallel=1,
                    testrunner='apps.agent.tests.b8e_runner.B8ERunner')
        except SystemExit as exc:
            code = exc.code or 0
        except BaseException:
            import traceback
            traceback.print_exc()
            code = 1
        receipt = {'suite': args.suite, 'database': args.database, 'exit_code': code, 'seconds': time.monotonic()-start}
        print(json.dumps(receipt))
        args.output.with_suffix('.exit.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
