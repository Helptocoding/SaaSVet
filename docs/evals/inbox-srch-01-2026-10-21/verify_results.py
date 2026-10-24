"""Validate directed receipts and freeze a manifest of the final search sources."""
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
assert not (out/'final-checks.json').exists(), 'Never overwrite a final manifest'


def read(name):
    return json.loads((out/name).read_text(encoding='utf-8'))


initial = read('backend-directed.json')
assert initial['exit_code'] == 1 and not initial['test_database_remains']
initial_log = (out/'backend-directed.log').read_text(encoding='utf-8')
assert 'Ran 0 tests' in initial_log and 'phone_normalized' in initial_log
backend = read('backend-fixture-fixed.json')
assert backend['exit_code'] == 0 and not backend['test_database_remains']
log = (out/'backend-fixture-fixed.log').read_text(encoding='utf-8')
count = int(re.search(r'^Ran (\d+) tests? in ', log, re.M)[1])
assert re.search(r'^OK\s*$', log, re.M)
backend_ids = re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.M)
assert count == len(backend_ids) == len(set(backend_ids)) == 41
assert sum('.test_inbox_search.' in name for name in backend_ids) == 16

frontend = {}
for tag in ('new', 'affected'):
    assert read(f'frontend-{tag}.json')['exit_code'] == 0
    for file in read(f'vitest-{tag}.json')['testResults']:
        for case in file['assertionResults']:
            if case['status'] in ('passed', 'failed'):
                key = str(Path(file['name']).relative_to(root/'frontend'))+' :: '+case['fullName']
                frontend[key] = case['status']
assert len(frontend) == 134 and set(frontend.values()) == {'passed'}
assert sum('index.search.test.jsx' in name for name in frontend) == 15
for kind in ('build', 'lint'):
    assert read(f'{kind}-final.json')['exit_code'] == 0
assert sum(item['errorCount']+item['warningCount'] for item in read('lint-report-final.json')) == 0

plan = read('query-plan-fixture-fixed.json')
assert plan['threads'] == 1004 and plan['returned'] == plan['list_selects'] == 1
assert plan['plan']['Plan']['Actual Rows'] == 1
browser = read('browser.json')
assert browser['status'] == 'PASS' and browser['page_errors'] == []
assert len(browser['measurements']) == 2
assert all(item['search_ms'] < 1000 and item['draft_preserved'] and item['clear_preserves_segments']
    and item['empty_suggestion'] and not item['horizontal_overflow'] for item in browser['measurements'])
assert read('browser-run.json')['exit_code'] == 0 and not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0

files = ['backend/apps/agent/views.py', 'backend/apps/agent/tests/test_inbox_search.py',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/index.search.test.jsx',
    'frontend/src/pages/inbox/inbox.module.css', 'docs/modules/agent.md', 'docs/modules/frontend.md',
    'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md',
    *[str(path.relative_to(root)).replace('\\', '/') for path in out.glob('*.py')],
    str((out/'README.md').relative_to(root)).replace('\\', '/')]
diff = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *files], cwd=root,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
assert diff.returncode == 0, diff.stdout
(out/'source-sha256.json').write_text(json.dumps({file: hashlib.sha256((root/file).read_bytes()).hexdigest()
    for file in files}, indent=2), encoding='utf-8')
(out/'executed-tests.json').write_text(json.dumps(dict(backend=backend_ids, frontend=frontend), indent=2), encoding='utf-8')
result = dict(status='PASS', backend_unique_pass=count, backend_new_pass=16,
    frontend_unique_pass=len(frontend), frontend_new_pass=15, build='PASS', lint='PASS',
    browser='PASS (synthetic API)', diff_check='PASS', query_plan_execution_ms=plan['plan']['Execution Time'],
    search_ms={item['viewport']:item['search_ms'] for item in browser['measurements']},
    test_database_remains=False, temporary_server_listening=False, schema_changed=False,
    working_database_migrated=False, deployment=False, activation=False,
    real_reception_meta_validation='DEFERRED by user; not accepted')
(out/'final-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
