"""Seal exact unique tests, browser cleanup, dependencies and final sources."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out / 'manifest.json'
assert not destination.exists(), 'Never overwrite evidence'


def read(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


results = {}
for receipt_name, expected_count in [('new-directed.json', 44), ('affected-directed.json', 83),
                                      ('retry-hidden-highlight.json', 1)]:
    receipt = read(receipt_name)
    assert receipt['exit_code'] == 0 and not receipt['working_database_migrated']
    assert receipt['passed'] == expected_count and receipt['failed'] == 0
    report_name = receipt['vitest_report']
    observed = {}
    for suite in read(report_name)['testResults']:
        source = Path(suite['name']).relative_to(root).as_posix()
        for case in suite['assertionResults']:
            if case['status'] in ['passed', 'failed']:
                identity = source + '::' + case['fullName']
                assert identity not in observed and case['status'] == 'passed'
                observed[identity] = dict(status=case['status'], receipt=report_name)
    assert len(observed) == expected_count and not set(results).intersection(observed)
    results.update(observed)
assert len(results) == 128
for name in ['lint-directed.json', 'lint-final.json', 'build-final.json']:
    assert read(name)['exit_code'] == 0
browser = read('browser.json')
cleanup = read('browser-run.json')
assert browser['status'] == 'PASS' and browser['synthetic_api'] and not browser['page_errors']
assert cleanup['exit_code'] == 0 and not cleanup['temporary_server_listening']
assert {row['viewport'] for row in browser['measurements']} == {'desktop', 'mobile'}
for row in browser['measurements']:
    assert row['local_without_get'] and row['target_in_viewport'] and row['discarded_media']
    assert row['before_chain_preserved'] and row['deduplicated'] and row['draft_preserved']
    assert row['switch_cancels'] and not row['horizontal_overflow']
for label in ['desktop', 'mobile']:
    assert [item['params'] for item in browser['requests'] if item['viewport'] == label
            and 'around' in item['params']] == [dict(around=['10']), dict(around=['30'])]
    assert [item['params'] for item in browser['requests'] if item['viewport'] == label
            and 'before' in item['params']] == [dict(before=['151'])]
    for name in ['quotes', 'jump']:
        assert (out / f'{name}-{label}.png').stat().st_size > 0

preserved = {}
for folder, paths in [
    ('inbox-rpl-03-2026-10-21', ['backend/apps/agent/views.py', 'backend/apps/agent/serializers.py',
                              'backend/apps/agent/inbox_sync.py']),
    ('inbox-rpl-05-2026-10-21', ['frontend/src/api/inbox.js']),
]:
    prior = json.loads((out.parent / folder / 'manifest.json').read_text(encoding='utf-8'))
    assert prior['status'] == 'PASS'
    for path in paths:
        actual = sha(root / path)
        assert actual == prior['source_sha256'][path], f'Unchanged dependency differs: {path}'
        preserved[path] = dict(sha256=actual, prior_manifest=f'../{folder}/manifest.json')

paths = [
    *['frontend/src/pages/inbox/' + name for name in ['index.jsx', 'useThreadHistory.js', 'ReplyQuote.jsx',
       'inbox.module.css', 'ReplyQuote.test.jsx', 'useThreadHistory.jump.test.jsx', 'index.jump.test.jsx']],
    'docs/modules/frontend.md', 'docs/CIERRE-INBOX-WHATSAPP.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md',
    *[f'docs/evals/inbox-rpl-06-04-2026-10-22/{name}' for name in
      ['README.md', 'run_checks.py', 'check_browser.py', 'run_browser.py', 'verify.py']],
]
for path in paths:
    if path.endswith('.py'):
        ast.parse((root / path).read_text(encoding='utf-8'))
assert (root / 'docs/modules/frontend.md').read_text(encoding='utf-8').count(
    '### WhatsApp Inbox: citas y salto al original (WA-RPL-06 + WA-RPL-04)') == 1
assert (root / 'CHANGELOG.md').read_text(encoding='utf-8').count('- Inbox, WA-RPL-06/04:') == 1
check = subprocess.run(['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths],
                       cwd=root, capture_output=True, text=True, encoding='utf-8')
assert check.returncode == 0, check.stdout + check.stderr
artifacts = [path for path in out.iterdir() if path.suffix in ['.json', '.log', '.png']]
manifest = dict(
    status='PASS', scope=['WA-RPL-06', 'WA-RPL-04'], unique_pass=len(results), new_cases=45,
    affected_cases=83, results=results, preserved_dependencies=preserved,
    source_sha256={path: sha(root / path) for path in paths},
    artifact_sha256={path.name: sha(path) for path in artifacts},
    working_database_migrated=False, backend_changed=False, synthetic_browser_api=True,
    native_provider_citation='IMPLEMENTATION_PENDING', real_meta='POSTPONED_PENDING', next_task='WA-RPL-07',
    diff_check=dict(exit_code=check.returncode, stdout=check.stdout, stderr=check.stderr),
)
destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: 128 unique frontend cases (45 new, 83 affected), build, lint, Chromium, cleanup and source hashes')
