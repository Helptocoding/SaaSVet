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
test_name = 'test_inbox_hist03_' + uuid4().hex[:12]
database.setdefault('TEST', {})['NAME'] = test_name

labels = ['apps.agent.tests.test_inbox_thread_around', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_the_transcript_crosses_sessions', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_a_failed_outbound_is_shown_with_failed_status', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_pending_outbound_from_own_and_other_staff_is_shown', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_pending_agent_and_system_outbound_are_shown_as_queued', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_discarded_outbound_is_shown_with_history', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_b4_uncertain_is_visible_without_acceptance_claim_or_token', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_b4_sent_without_wamid_is_legacy_unknown', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_transcript_shows_pending_message_immediately_after_send', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_client_message_id_is_null_for_non_human_or_unkeyed_messages', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_the_cursor_walks_backwards', 'apps.agent.tests.test_inbox_threads.ThreadDetailTests.test_another_org_gets_404']
start = time.monotonic()
exit_code = 0
with (output / 'backend.log').open('w', encoding='utf-8') as log:
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
(output / 'backend.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
print('\n'.join((output / 'backend.log').read_text(encoding='utf-8').splitlines()[-22:]))
raise SystemExit(exit_code or int(test_database_remains))
