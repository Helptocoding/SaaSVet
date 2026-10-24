"""Verify directed receipts and preserve one final manifest of current sources."""
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
assert not (out/'final-checks.json').exists(), 'Use a fresh receipt for a repetition'


def read(name):
    return json.loads((out/name).read_text(encoding='utf-8'))


backend = read('backend-directed.json')
assert backend['exit_code'] == 0 and not backend['test_database_remains']
log = (out/'backend-directed.log').read_text(encoding='utf-8')
count = int(re.search(r'^Ran (\d+) tests? in ', log, re.M)[1])
assert re.search(r'^OK\s*$', log, re.M)
backend_ids = re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.M)
assert len(backend_ids) == len(set(backend_ids)) == count
assert sum('.test_inbox_filters.' in name for name in backend_ids) == 14

frontend = {}
for tag in ('new', 'retry-selector', 'affected'):
    for file in read(f'vitest-{tag}.json')['testResults']:
        for case in file['assertionResults']:
            if case['status'] in ('passed', 'failed'):
                key = str(Path(file['name']).relative_to(root/'frontend'))+' :: '+case['fullName']
                frontend[key] = case['status']
assert len(frontend) == 119 and set(frontend.values()) == {'passed'}
assert sum('index.filters.test.jsx' in name for name in frontend) == 10

assert read('build-final.json')['exit_code'] == 0
assert read('lint-complete.json')['exit_code'] == 0
lint = read('lint-report-complete.json')
assert sum(item['errorCount']+item['warningCount'] for item in lint) == 0
browser = read('browser.json')
assert browser['status'] == 'PASS' and browser['page_errors'] == []
assert len(browser['measurements']) == 2
assert all(item['draft_preserved'] and item['empty_segment'] and not item['horizontal_overflow']
    and all(button['height'] >= 44 for button in item['chip_sizes']) for item in browser['measurements'])
assert read('browser-run.json')['exit_code'] == 0 and not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0

files = ['backend/apps/agent/views.py', 'backend/apps/agent/tests/test_inbox_filters.py',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/index.filters.test.jsx',
    'frontend/src/pages/inbox/inbox.module.css', 'docs/modules/agent.md', 'docs/modules/frontend.md',
    'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md',
    *[str(path.relative_to(root)).replace('\\', '/') for path in out.glob('*.py')],
    str((out/'README.md').relative_to(root)).replace('\\', '/')]
check = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *files], cwd=root, text=True,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8')
assert check.returncode == 0, check.stdout
hashes = {file: hashlib.sha256((root/file).read_bytes()).hexdigest() for file in files}
(out/'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
(out/'executed-tests.json').write_text(json.dumps(dict(backend=backend_ids, frontend=frontend), indent=2), encoding='utf-8')
result = dict(status='PASS', backend_unique_pass=count, backend_new_pass=14,
    frontend_unique_pass=len(frontend), frontend_new_pass=10, build='PASS', lint='PASS',
    browser='PASS (synthetic API)', diff_check='PASS', test_database_remains=False,
    temporary_server_listening=False, schema_changed=False, working_database_migrated=False,
    deployment=False, activation=False)
(out/'final-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
