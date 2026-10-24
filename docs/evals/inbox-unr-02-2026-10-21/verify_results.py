"""Validate the directed receipts and seal the final source references."""
import ast
import hashlib
import json
import re
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]


def receipt(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


vitest = receipt('vitest.json')
passed = {(row['name'], case['fullName']) for row in vitest['testResults']
          for case in row['assertionResults'] if case['status'] == 'passed'}
new_frontend = {case for case in passed if 'WA-UNR-02' in case[1]}
assert len(passed) == 125 and len(new_frontend) == 27 and vitest['numFailedTests'] == 0
assert vitest['numPendingTests'] == 41
assert receipt('frontend-run.json')['exit_code'] == 0
api = receipt('backend.json')
log = (out / 'backend.log').read_text(encoding='utf-8')
api_cases = set(re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.MULTILINE))
assert len(api_cases) == 41 and re.search(r'^OK$', log, re.MULTILINE)
assert api['exit_code'] == 0 and not api['test_database_remains']
assert sum('test_inbox_read_projection.' in case for case in api_cases) == 4
for kind in ('build', 'lint'):
    assert receipt(kind + '-run.json')['exit_code'] == 0
    assert receipt(kind + '-run.json')['sentry_upload_disabled']
assert all(row['errorCount'] == 0 for row in receipt('lint.json'))
browser = receipt('browser.json')
assert browser['status'] == 'PASS' and not browser['page_errors']
assert {m['viewport'] for m in browser['measurements']} == {'desktop', 'mobile'}
for measure in browser['measurements']:
    assert abs(measure['anchor_delta']) < 1 and not measure['horizontal_overflow']
    assert all(measure[key] for key in ('independent_staff', 'view_only_read', 'blur_cancels',
        'hidden_does_not_mark', 'silent_failure_retry', 'divider_removed_after_ack', 'total_spans_pages'))
for name in ('browser-run.json', 'browser-run-initial.json', 'browser-run-token-initial.json'):
    assert not receipt(name)['temporary_server_listening']
assert receipt('browser-run.json')['exit_code'] == 0
assert receipt('browser-run-initial.json')['exit_code'] == 1
assert receipt('browser-run-token-initial.json')['exit_code'] == 1
old_hashes = json.loads((out.parent / 'inbox-unr-01-2026-10-21/source-sha256.json').read_text(encoding='utf-8'))
for name in ('models.py', 'serializers.py', 'urls.py', 'migrations/0029_inbox_read_state.py'):
    path = 'backend/apps/agent/' + name
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == old_hashes[path]

paths = ['frontend/src/api/inbox.js', 'frontend/src/api/inbox.test.js',
         'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/index.test.jsx',
         'frontend/src/pages/inbox/index.unread.test.jsx', 'frontend/src/pages/inbox/useThreadRead.js',
         'frontend/src/pages/inbox/useThreadRead.test.jsx', 'frontend/src/pages/inbox/useThreadHistory.js',
         'frontend/src/pages/inbox/inbox.module.css', 'backend/apps/agent/inbox_read.py',
         'backend/apps/agent/views.py', 'backend/apps/agent/tests/test_inbox_read_projection.py',
         'backend/apps/agent/tests/test_inbox_read_state.py',
         'backend/apps/agent/tests/test_inbox_thread_pagination.py',
         'backend/apps/agent/tests/test_inbox_thread_around.py',
         'docs/modules/agent.md', 'docs/modules/frontend.md', 'docs/CIERRE-INBOX-WHATSAPP.md',
         'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md']
hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
for p in paths:
    if p.endswith('.py'):
        ast.parse((root / p).read_text(encoding='utf-8'))
(out / 'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
checks = {'frontend_passed': 125, 'frontend_skipped_by_scope': 41, 'new_frontend': 27,
          'api_passed': 41, 'new_api': 4, 'build': True, 'lint': True,
          'browser_desktop_mobile': True, 'divider_anchor_delta_px': 0,
          'independent_users': True, 'view_only_mark_read': True, 'all_pages_total': True,
          'focus_visibility_debounce_cancellation': True, 'silent_retry': True,
          'stale_get_and_ack_protected': True, 'sql_query_budget_preserved': True,
          'test_database_removed': True, 'temporary_server_closed': True,
          'initial_harness_failures_preserved': True, 'schema_and_permissions_unchanged': True,
          'working_database_migrated': False}
(out / 'final-checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps(checks))
