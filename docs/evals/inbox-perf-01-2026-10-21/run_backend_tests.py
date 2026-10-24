"""Directed API tests in a uniquely named, disposable local PostgreSQL database."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

output = Path(__file__).resolve().parent
capture = 'capture' in sys.argv[1:]
prefix = 'baseline-' if capture else ''
root = output.parents[2]
sys.path.insert(0, str(root / 'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
from django.conf import settings

database = settings.DATABASES['default']
assert database['HOST'] in ('localhost', '127.0.0.1'), 'Local database required'
assert database['ENGINE'] == 'django.db.backends.postgresql'
test_name = 'test_inbox_perf_' + uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = test_name

labels = [
    'apps.agent.tests.test_inbox_thread_performance.ThreadPerformanceTests',
    'apps.agent.tests.test_inbox_threads.GroupingTests',
    'apps.agent.tests.test_inbox_threads.AgentProcessingTests',
    'apps.agent.tests.test_inbox_threads.ArchivedThreadTests.test_it_shows_with_the_explicit_flag_and_offers_no_actions',
    'apps.agent.tests.test_inbox_threads.ArchivedThreadTests.test_an_archived_thread_is_hidden_by_default',
    'apps.agent.tests.test_inbox_threads.UrgentOrderingTests',
]
start = time.monotonic()
exit_code = 0
with (output / f'{prefix}backend.log').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            import django
            django.setup()
            from apps.agent.tests import test_inbox_thread_performance as cases
            if capture:
                # Explicit pre-change capture only; regular verification never updates fixtures.
                assert not cases.FIXTURE.exists(), 'Never overwrite a captured baseline'
                def capture_baseline(self):
                    payload = self.payloads()
                    self.assertEqual(len(payload['active']), 7)
                    self.assertEqual(len(payload['archived']), 8)
                    cases.FIXTURE.parent.mkdir(exist_ok=True)
                    cases.FIXTURE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
                    small = self.query_sample()
                    self.add_thirty_threads()
                    large = self.query_sample()
                    cases.MEASUREMENTS.append({'small': small, 'large': large})
                cases.ThreadPerformanceTests.test_characterization_payload_matches_frozen_baseline = capture_baseline
                labels = ['apps.agent.tests.test_inbox_thread_performance.ThreadPerformanceTests.test_characterization_payload_matches_frozen_baseline']
            from django.core.management import call_command
            call_command('test', *labels, verbosity=2, interactive=False, keepdb=False)
        except SystemExit as error:
            exit_code = error.code or 0
        except Exception:
            import traceback
            traceback.print_exc()
            exit_code = 1

from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)', [test_name])
    test_database_remains = cursor.fetchone()[0]
connection.close()
result = {'exit_code': exit_code, 'labels': labels,
          'elapsed_s': time.monotonic() - start, 'test_database': test_name,
          'test_database_remains': test_database_remains,
          'measurements': cases.MEASUREMENTS if 'cases' in globals() else []}
(output / f'{prefix}backend.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((output / f'{prefix}backend.log').read_text(encoding='utf-8').splitlines()[-22:]))
raise SystemExit(exit_code or int(test_database_remains))
