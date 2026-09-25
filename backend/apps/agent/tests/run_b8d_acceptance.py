"""Explicit local PostgreSQL acceptance, no production configuration changes."""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('b8d', 'unit', 'processes', 'corpus', 'baseline',
        'targeted', 'baseline-repair', 'checks'), required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ids-file', type=Path)
    args = parser.parse_args()
    prefix = 'test_b8b_' if args.suite in ('baseline', 'baseline-repair') else 'test_b8d_'
    if not args.database.startswith(prefix) or not os.environ.get('DATABASE_URL'):
        parser.error('Explicit DATABASE_URL and isolated database required')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection
    from django.core.management import call_command
    from .b8d_runner import baseline_ids
    if connection.vendor != 'postgresql' or connection.settings_dict['HOST'] not in ('127.0.0.1', 'localhost'):
        parser.error('Local PostgreSQL required')
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = args.database
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher', *settings.PASSWORD_HASHERS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ['B8D_RESULTS_PATH'] = str(args.output.with_suffix('.results.json'))
    os.environ['B8D_SUITE'] = args.suite
    modules = {'unit': ['apps.agent.tests.test_b8d_attendance'],
        'processes': ['apps.agent.tests.test_b8d_processes'], 'corpus': ['apps.agent.tests.test_b8d_corpus']}
    modules['b8d'] = sum(modules.values(), [])
    code, started = 0, time.monotonic()
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
                with connection.cursor() as c:
                    c.execute('SELECT version()')
                    print(c.fetchone()[0])
                    c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid IN ('appointments_appointment'::regclass, "
                        "'appointments_appointmentmutationeffect'::regclass, "
                        "'agent_conversationoperation'::regclass) ORDER BY conname")
                    print(json.dumps(c.fetchall()))
                    c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='appointments_appointmentmutationeffect'::regclass AND NOT tgisinternal")
                    print(json.dumps(c.fetchall()))
            else:
                selected = sorted(baseline_ids()) if args.suite == 'baseline' else modules.get(args.suite)
                if args.suite in ('targeted', 'baseline-repair'):
                    selected = json.loads(args.ids_file.read_text(encoding='utf-8'))
                    if not selected or (args.suite == 'baseline-repair' and not set(selected) <= baseline_ids()):
                        raise ValueError('Invalid repair inventory')
                    if args.suite == 'targeted' and not all(x.startswith('apps.agent.tests.test_b8d_') for x in selected):
                        raise ValueError('Targeted B8D tests only')
                call_command('test', *selected,
                    keepdb=True, interactive=False, verbosity=2, parallel=1,
                    testrunner='apps.agent.tests.b8d_runner.B8DRunner')
        except SystemExit as exc:
            code = exc.code or 0
        except BaseException:
            import traceback
            traceback.print_exc()
            code = 1
        outcome = {'suite': args.suite, 'database': args.database, 'exit_code': code,
                   'seconds': time.monotonic() - started}
        print('B8D_RUN_RESULT ' + json.dumps(outcome))
        args.output.with_suffix('.exit.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
