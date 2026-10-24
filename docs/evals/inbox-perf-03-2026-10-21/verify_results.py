"""Consolidate only executed IDs, then verify receipts, cleanup and source guards."""
import hashlib
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]


def read(name):
    return json.loads((out/name).read_text(encoding='utf-8'))


front = {}
for tag in ('initial', 'regressions', 'fixed', 'cadence'):
    for suite in read(f'vitest-{tag}.json')['testResults']:
        for test in suite['assertionResults']:
            if test['status'] in ('passed', 'failed'):
                front[(suite['name'], test['fullName'])] = test['status']
assert len(front) == 259 and set(front.values()) == {'passed'}
assert sum('WA-PERF-03' in key[1] for key in front) == 37
back = {}
back_runs = []
for tag in ('backend', 'backend-api-fixed', 'backend-api-final', 'backend-plan'):
    log = (out/f'{tag}.log').read_text(encoding='utf-8')
    ids = re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.M)
    failed = set(re.findall(r'^(?:FAIL|ERROR): test_\w+ \(([\w.]+)\)', log, re.M))
    skipped = set(re.findall(r'^test_\w+ \(([\w.]+)\) \.\.\. skipped', log, re.M))
    ran = int(re.search(r'Ran (\d+) test', log)[1])
    assert len(set(ids)) == ran, (tag, len(set(ids)), ran)
    back.update({key: 'failed' if key in failed else 'passed' for key in ids if key not in skipped})
    receipt = read(f'{tag}.json')
    assert not receipt['test_database_remains']
    back_runs.append(dict(tag=tag, executed=ran, failures=len(failed), skipped=len(skipped),
                          exit_code=receipt['exit_code']))
assert len(back) == 123 and set(back.values()) == {'passed'}, [key for key, value in back.items() if value != 'passed']
assert sum('test_inbox_sync.' in key for key in back) == 26
summary = dict(status='PASS', backend_unique_pass=len(back), new_backend_pass=26,
    frontend_unique_pass=len(front), new_frontend_pass=37, backend_runs=back_runs,
    frontend_composite=True, backend_composite=True)
if '--counts' in sys.argv:
    print(json.dumps(summary, indent=2))
    raise SystemExit(0)

assert read('frontend-initial-run.json')['exit_code'] == 0
assert read('frontend-regressions-run.json')['exit_code'] == 1
assert read('frontend-fixed-run.json')['exit_code'] == 1
assert read('frontend-cadence-run.json')['exit_code'] == 0
for kind in ('build', 'lint', 'lint-final', 'migration'):
    assert read(f'{kind}-run.json')['exit_code'] == 0
for name in ('lint.json', 'lint-final.json'):
    assert all(row['errorCount'] == 0 and row['warningCount'] == 0 for row in read(name))
assert 'No changes detected' in (out/'migration.log').read_text(encoding='utf-8')
browser = read('browser.json')
assert browser['status'] == 'PASS' and not browser['page_errors']
assert len(browser['measurements']) == 2
assert all(abs(row['scroll_anchor_delta_px']) < 1 and abs(row['recovery_anchor_delta_px']) < 1
    and row['changed_tick'] and row['removed_history'] and row['resumed_delta']
    and row['draft_preserved'] and not row['duplicate_ids'] for row in browser['measurements'])
assert read('browser-run.json')['exit_code'] == 0
assert not read('browser-run.json')['temporary_server_listening']
with socket.socket() as sock:
    sock.settimeout(0.2)
    assert sock.connect_ex(('127.0.0.1', 4178)) != 0
plan = read('query-plan.json')
assert plan['total_messages'] == 6001 and plan['loaded_messages'] == 50
assert plan['stable_delta_bytes'] < plan['full_payload_bytes']/10
assert plan['explain'][0]['Plan']['Actual Rows'] == 50


def walk(node):
    yield node
    for child in node.get('Plans', []):
        yield from walk(child)


indexes = sorted({node['Index Name'] for node in walk(plan['explain'][0]['Plan']) if 'Index Name' in node})
assert 'channels_me_organiz_c00b67_idx' in indexes
assert read('write-audit.json')['status'] == 'PASS'
sources = [
    'backend/apps/core/models.py', 'backend/config/settings.py',
    'backend/apps/agent/models.py', 'backend/apps/channels/models.py',
    'backend/apps/agent/inbox_sync.py', 'backend/apps/agent/views.py',
    'backend/apps/agent/tests/test_inbox_sync.py', 'backend/apps/agent/tests/test_inbox_thread_pagination.py',
    'backend/apps/agent/tests/test_inbox_thread_around.py', 'frontend/src/api/inbox.js',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/index.test.jsx',
    'frontend/src/pages/inbox/inboxSync.js', 'frontend/src/pages/inbox/inboxSync.test.js',
    'frontend/src/pages/inbox/index.sync.test.jsx', 'frontend/src/pages/inbox/useThreadHistory.js',
    'backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py',
    'backend/apps/agent/inbox_retry.py', 'backend/apps/agent/serializers.py', 'backend/apps/agent/urls.py',
    'frontend/src/pages/inbox/sessionWindow.js', 'frontend/src/pages/inbox/SessionWindowNotice.jsx',
]
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
previous = json.loads((root/'docs/evals/inbox-ctx-01-2026-10-21/source-sha256.json').read_text(encoding='utf-8'))
unchanged = ['backend/apps/agent/sender.py', 'backend/apps/channels/delivery.py',
    'backend/apps/agent/inbox_retry.py', 'backend/apps/agent/serializers.py', 'backend/apps/agent/urls.py',
    'frontend/src/pages/inbox/sessionWindow.js', 'frontend/src/pages/inbox/SessionWindowNotice.jsx']
assert all(hashes[name] == previous[name] for name in unchanged)
(out/'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
docs = ['CHANGELOG.md', 'docs/modules/agent.md', 'docs/modules/frontend.md',
    'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md',
    'docs/decisions/2026-10-21-p60-perf03-cursors.md']
diff = subprocess.run(['rtk', 'git', 'diff', '--check', '--', *sources, *docs],
    cwd=root, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
assert '**Siguiente tarea: WA-FIL-01**' in (root/'docs/CIERRE-INBOX-WHATSAPP.md').read_text(encoding='utf-8')
summary.update(build='PASS', lint='PASS', migration_drift='PASS', browser='PASS', diff_check='PASS',
    b4_sources_unchanged=True, window_helpers_unchanged=True, indices=indexes,
    full_payload_bytes=plan['full_payload_bytes'], stable_delta_bytes=plan['stable_delta_bytes'],
    payload_reduction_percent=round(100*(1-plan['stable_delta_bytes']/plan['full_payload_bytes']), 2),
    explain_execution_ms=plan['explain'][0]['Execution Time'],
    temporary_server_listening=False, test_databases_remain=False, new_migration=False,
    working_database_migrated=False, deployment=False, activation=False)
(out/'final-checks.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
(out/'executed-tests.json').write_text(json.dumps(dict(backend=sorted(back),
    frontend=[dict(file=key[0], name=key[1]) for key in sorted(front)]), indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
