"""Directed API tests in a uniquely named, disposable local PostgreSQL database."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

output = Path(__file__).resolve().parent
root = output.parents[2]
sys.path.insert(0, str(root / 'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
from django.conf import settings

database = settings.DATABASES['default']
assert database['HOST'] in ('localhost', '127.0.0.1'), 'Local database required'
assert database['ENGINE'] == 'django.db.backends.postgresql'
test_name = 'test_inbox_unr01_followup_' + uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = test_name

labels = ['apps.agent.tests.test_inbox_read_state.InboxReadStateTests.test_foreign_missing_and_other_thread_targets_are_404', 'apps.agent.tests.test_inbox_read_state.InboxReadStateTests.test_outbound_and_discarded_inbound_are_rejected_without_write', 'apps.agent.tests.test_inbox_read_state.InboxReadStateTests.test_counts_are_batched_without_loading_message_or_read_state_instances']
start = time.monotonic()
exit_code = 0
with (output / 'backend-followup.log').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            import django
            django.setup()
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
          'test_database_remains': test_database_remains}
(output / 'backend-followup.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((output / 'backend-followup.log').read_text(encoding='utf-8').splitlines()[-22:]))
raise SystemExit(exit_code or int(test_database_remains))
