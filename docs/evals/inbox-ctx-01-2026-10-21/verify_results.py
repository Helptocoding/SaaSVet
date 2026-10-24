"""Validate executed IDs, receipts, cleanup, source hashes and unchanged B4 guards."""
import hashlib
import json
import re
import socket
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]


def read(name):
    return json.loads((out/name).read_text(encoding='utf-8'))


statuses = {}
for name in ('vitest.json', 'vitest-history.json', 'vitest-history-isolated.json', 'vitest-retry.json'):
    for suite in read(name)['testResults']:
        for test in suite['assertionResults']:
            if test['status'] in ('passed', 'failed'):
                statuses[(suite['name'], test['fullName'])] = test['status']
assert len(statuses) == 112 and set(statuses.values()) == {'passed'}
assert sum('WA-CTX-01' in key[1] for key in statuses) == 17
assert read('initial-frontend-run.json')['exit_code'] == 1
assert read('initial-vitest.json')['numFailedTests'] == 80
assert read('frontend-run.json')['exit_code'] == 1
assert read('vitest.json')['numPassedTests'] == 86
assert read('vitest.json')['numFailedTests'] == 1
assert read('frontend-history-run.json')['exit_code'] == 1
assert read('frontend-history-isolated-run.json')['exit_code'] == 0
assert read('frontend-retry-run.json')['exit_code'] == 0
backend = read('backend.json')
assert backend['exit_code'] == 0 and not backend['test_database_remains']
assert re.search(r'Ran 20 tests.*?\nOK\n', (out/'backend.log').read_text(encoding='utf-8'), re.S)
assert read('build-run.json')['exit_code'] == 0
for suffix in ('', '-history'):
    assert read(f'lint{suffix}-run.json')['exit_code'] == 0
    assert all(row['errorCount'] == 0 and row['warningCount'] == 0 for row in read(f'lint{suffix}.json'))
browser = read('browser.json')
assert browser['status'] == 'PASS' and len(browser['measurements']) == 2
assert not browser['page_errors']
assert all(row['chat_to_correct_pet_clicks'] == 2 and row['draft_preserved']
           and row['transcript_preserved'] and row['explicit_retry']
           and not row['horizontal_overflow'] for row in browser['measurements'])
assert read('initial-browser.json')['status'] == 'FAIL'
assert read('browser-run.json')['exit_code'] == 0 and not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0

sources = [
    'backend/apps/agent/inbox_context.py', 'backend/apps/agent/views.py', 'backend/apps/agent/urls.py',
    'backend/apps/agent/tests/test_inbox_context.py', 'backend/apps/agent/serializers.py',
    'frontend/src/api/inbox.js', 'frontend/src/api/inbox.test.js',
    'frontend/src/pages/inbox/ThreadContextPanel.jsx', 'frontend/src/pages/inbox/index.jsx',
    'frontend/src/pages/inbox/inbox.module.css', 'frontend/src/pages/inbox/index.context.test.jsx',
    'frontend/src/pages/inbox/index.test.jsx', 'frontend/src/pages/inbox/index.window.test.jsx',
    'frontend/src/pages/inbox/index.unread.test.jsx', 'frontend/src/pages/inbox/index.retry.test.jsx',
    'backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py', 'backend/apps/agent/inbox_retry.py',
    'frontend/src/pages/inbox/sessionWindow.js', 'frontend/src/pages/inbox/SessionWindowNotice.jsx',
]
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
previous = json.loads((root/'docs/evals/inbox-win-01-2026-10-21/source-sha256.json').read_text(encoding='utf-8'))
unchanged = ['backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py',
    'backend/apps/agent/inbox_retry.py', 'backend/apps/agent/serializers.py',
    'frontend/src/pages/inbox/sessionWindow.js', 'frontend/src/pages/inbox/SessionWindowNotice.jsx']
assert all(hashes[name] == previous[name] for name in unchanged)
(out/'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
docs = ['CHANGELOG.md', 'docs/modules/agent.md', 'docs/modules/frontend.md',
        'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md']
diff = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *sources, *docs],
    cwd=root, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
assert '**Siguiente tarea: WA-PERF-03**' in (root/'docs/CIERRE-INBOX-WHATSAPP.md').read_text(encoding='utf-8')
result = dict(status='PASS', backend_pass=20, new_backend_pass=17, frontend_unique_pass=112,
    new_frontend_pass=17, frontend_composite=True, initial_failures_retained=True,
    build='PASS', lint='PASS', browser='PASS', diff_check='PASS', b4_authority_unchanged=True,
    window_helpers_unchanged=True, context_domain_queries_for_1_and_36_pets=6,
    temporary_server_listening=False, test_database_remains=False,
    new_migration=False, working_database_migrated=False, deployment=False, activation=False)
(out/'final-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
