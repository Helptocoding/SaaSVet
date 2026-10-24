"""Verify composite executed test IDs, cleanup and unchanged B4 authority."""
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
for report_name in ('vitest.json', 'vitest-cap.json', 'vitest-cap-fixed.json'):
    for suite in read(report_name)['testResults']:
        for test in suite['assertionResults']:
            if test['status'] in ('passed', 'failed'):
                statuses[(suite['name'], test['fullName'])] = test['status']
assert len(statuses) == 84 and set(statuses.values()) == {'passed'}
assert sum('WA-WIN-01' in key[1] for key in statuses) == 18
assert read('frontend-run.json')['exit_code'] == 1
assert read('frontend-cap-run.json')['exit_code'] == 1
assert read('frontend-cap-fixed-run.json')['exit_code'] == 0
backend = read('backend.json')
assert backend['exit_code'] == 0 and not backend['test_database_remains']
assert re.search(r'Ran 19 tests.*?\nOK\n', (out/'backend.log').read_text(encoding='utf-8'), re.S)
assert read('build-run.json')['exit_code'] == 0
assert read('lint-run.json')['exit_code'] == 0
assert all(row['errorCount'] == 0 and row['warningCount'] == 0 for row in read('lint.json'))
assert read('browser.json')['status'] == 'PASS'
assert len(read('browser.json')['measurements']) == 2
assert all(row['sent_while_closed'] == 0 and row['sent_after_renewal'] == 1
           for row in read('browser.json')['measurements'])
assert read('browser-run.json')['exit_code'] == 0
assert not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0

sources = [
    'backend/apps/agent/serializers.py', 'backend/apps/agent/tests/test_inbox_session_window.py',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/sessionWindow.js',
    'frontend/src/pages/inbox/SessionWindowNotice.jsx', 'frontend/src/pages/inbox/inbox.module.css',
    'frontend/src/pages/inbox/index.window.test.jsx', 'frontend/src/pages/inbox/index.test.jsx',
    'frontend/src/pages/inbox/index.retry.test.jsx',
    'backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py',
    'backend/apps/agent/inbox_retry.py',
]
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
previous = json.loads((root/'docs/evals/inbox-retry-01-2026-10-21/source-sha256.json').read_text(encoding='utf-8'))
authority = ['backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py', 'backend/apps/agent/inbox_retry.py']
assert all(hashes[name] == previous[name] for name in authority)
(out/'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
docs = ['CHANGELOG.md', 'docs/modules/agent.md', 'docs/modules/frontend.md',
        'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md']
diff = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *sources, *docs],
                      cwd=root, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
guide = (root/'docs/CIERRE-INBOX-WHATSAPP.md').read_text(encoding='utf-8')
assert '**Siguiente tarea: WA-CTX-01**' in guide
result = dict(status='PASS', backend_pass=19, new_backend_pass=9, frontend_unique_pass=84,
    new_frontend_pass=18, frontend_composite=True, initial_timeouts_retained=2,
    build='PASS', lint='PASS', browser='PASS', diff_check='PASS', b4_authority_unchanged=True,
    temporary_server_listening=False, test_database_remains=False,
    new_migration=False, working_database_migrated=False, deployment=False, activation=False)
(out/'final-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
