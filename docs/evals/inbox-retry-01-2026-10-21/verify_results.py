"""Verify executed IDs, cleanup and final receipts; capture exact source hashes."""
import hashlib
import json
import re
import socket
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
read = lambda name: json.loads((out/name).read_text(encoding='utf-8'))
statuses = {}
for name in ('vitest-initial.json', 'vitest.json'):
    report = read(name)
    for suite in report['testResults']:
        for test in suite['assertionResults']:
            if test['status'] in ('passed', 'failed'):
                statuses[(suite['name'], test['fullName'])] = test['status']
assert len(statuses) == 106 and set(statuses.values()) == {'passed'}
new_frontend = sum('WA-RETRY-01' in key[1] for key in statuses)
assert new_frontend == 27
assert read('frontend-run.json')['exit_code'] == 0
backend = read('backend.json')
assert backend['exit_code'] == 0 and not backend['test_database_remains']
assert re.search(r'Ran 29 tests.*?\nOK\n', (out/'backend.log').read_text(encoding='utf-8'), re.S)
assert read('build-run.json')['exit_code'] == 0
assert read('lint-run.json')['exit_code'] == 0
assert all(row['errorCount'] == 0 and row['warningCount'] == 0 for row in read('lint.json'))
assert read('browser.json')['status'] == 'PASS'
assert all(row['anchor_delta'] == 0 for row in read('browser.json')['measurements'])
assert not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0
sources = [
    'backend/apps/agent/inbox_retry.py', 'backend/apps/agent/tests/test_inbox_retry.py',
    'backend/apps/agent/views.py', 'backend/apps/agent/urls.py', 'backend/apps/agent/serializers.py',
    'backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py',
    'frontend/src/api/inbox.js', 'frontend/src/api/inbox.test.js',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/inbox.module.css',
    'frontend/src/pages/inbox/FailedMessageRetry.jsx', 'frontend/src/pages/inbox/index.retry.test.jsx',
    'frontend/src/pages/inbox/index.test.jsx', 'frontend/src/pages/inbox/index.unread.test.jsx',
]
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
(out/'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
diff = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *sources,
    'CHANGELOG.md', 'docs/modules/agent.md', 'docs/modules/frontend.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md'], cwd=root, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
result = dict(status='PASS', frontend_unique_pass=len(statuses), new_frontend_pass=new_frontend,
              backend_pass=29, frontend_composite=True, initial_failures_retained=True,
              build='PASS', lint='PASS', browser='PASS', diff_check='PASS',
              temporary_server_listening=False, test_database_remains=False,
              working_database_migrated=False, deployment=False, activation=False)
(out/'final-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
