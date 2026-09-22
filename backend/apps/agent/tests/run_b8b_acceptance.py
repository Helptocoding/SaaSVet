"""Run from backend with an explicitly configured local PostgreSQL DATABASE_URL.

python -m apps.agent.tests.run_b8b_acceptance --suite b8b --database test_b8b_final --output /tmp/b8b
No production gates are opened by this runner; individual fixtures scope them.
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', required=True, choices=('baseline', 'b8b', 'agenda', 'checks'))
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.database.startswith('test_b8b_') or not os.environ.get('DATABASE_URL'):
        parser.error('Explicit DATABASE_URL and isolated test_b8b_ database required')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.core.management import call_command
    from .b8b_runner import baseline_ids
    if connection.vendor != 'postgresql' or connection.settings_dict['HOST'] not in ('127.0.0.1', 'localhost'):
        parser.error('Acceptance is restricted to local PostgreSQL')
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = args.database
    # Fixture passwords only: no production setting or operation digest changes.
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher', *settings.PASSWORD_HASHERS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ['B8B_RESULTS_PATH'] = str(args.output.with_suffix('.results.json'))
    os.environ['B8B_SUITE'] = args.suite
    labels = {
        'b8b': ['apps.agent.tests.test_b8b_create', 'apps.agent.tests.test_b8b_corpus',
                'apps.agent.tests.test_b8b_processes', 'apps.appointments.tests.test_creation_domain'],
        'agenda': ['apps.appointments.tests'],
    }
    started, code = time.monotonic(), 0
    with args.output.with_suffix('.log').open('w', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        for logger in [logging.getLogger()] + list(logging.Logger.manager.loggerDict.values()):
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
                with connection.cursor() as cursor:
                    cursor.execute('SELECT version()')
                    print(cursor.fetchone()[0])
                    cursor.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid='appointments_appointment'::regclass ORDER BY conname")
                    print(json.dumps(cursor.fetchall()))
            else:
                modules = sorted(baseline_ids()) if args.suite == 'baseline' else labels[args.suite]
                call_command('test', *modules, keepdb=True, interactive=False, verbosity=2, parallel=1,
                    testrunner='apps.agent.tests.b8b_runner.CriticalB8BRunner')
        except SystemExit as exc:
            code = exc.code or 0
        except BaseException:
            import traceback
            traceback.print_exc()
            code = 1
        outcome = {'suite': args.suite, 'database': args.database, 'exit_code': code,
                   'seconds': time.monotonic() - started}
        print('B8B_RUN_RESULT ' + json.dumps(outcome))
        args.output.with_suffix('.exit.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
