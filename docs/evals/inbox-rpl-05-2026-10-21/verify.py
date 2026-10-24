"""Consolidate unique results and seal final evidence without repeating PASS."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out / 'manifest.json'
assert not destination.exists(), 'Never overwrite a sealed manifest'


def read(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


def selected(name):
    result = {}
    report = read(name)
    for suite in report['testResults']:
        source = Path(suite['name']).relative_to(root).as_posix()
        for case in suite['assertionResults']:
            if case['status'] in ['passed', 'failed']:
                identity = source + '::' + case['fullName']
                assert identity not in result
                result[identity] = dict(status=case['status'], receipt=name)
    return result


initial = selected('new-directed-vitest.json')
affected = selected('affected-directed-vitest.json')
correction = selected('boundary-corrected-vitest.json')
initial_failed = {key for key, value in initial.items() if value['status'] == 'failed'}
assert len(initial) == 30 and len(initial_failed) == 1
assert 'si vence la ventana después de seleccionar' in next(iter(initial_failed))
assert set(correction) == initial_failed
assert len(affected) == 31 and not set(initial).intersection(affected)
assert read('new-directed.json')['exit_code'] == 1
for name in ['affected-directed.json', 'boundary-corrected.json', 'lint-directed.json', 'build-final.json']:
    receipt = read(name)
    assert receipt['exit_code'] == 0 and not receipt['working_database_migrated']
results = {**initial, **affected, **correction}
assert len(results) == 61 and all(item['status'] == 'passed' for item in results.values())
new_cases = sum('index.replies.test.jsx::' in key or 'envía reply_to_id' in key
                or 'omite la cita ausente' in key for key in results)
assert new_cases == 27

browser = read('browser.json')
cleanup = read('browser-run.json')
assert browser['status'] == 'PASS' and not browser['page_errors']
assert browser['synthetic_api'] and len(browser['sends']) == 2
assert {item['viewport'] for item in browser['measurements']} == {'desktop', 'mobile'}
assert all(not item['horizontal_overflow'] and item['switch_cancels']
           and item['request_has_reply_id'] and item['optimistic_reply_disabled']
           and item['confirmed_reply_enabled'] for item in browser['measurements'])
assert cleanup['exit_code'] == 0 and not cleanup['temporary_server_listening']
for label in ['desktop', 'mobile']:
    assert (out / f'composer-{label}.png').stat().st_size > 0

fixture_source = root / 'frontend/src/pages/inbox/index.replies.test.jsx'
fixture_hash = hashlib.sha256(fixture_source.read_bytes()).hexdigest()
lint_path = out / 'lint-fixture-final.json'
if lint_path.exists():
    lint = read(lint_path.name)
    assert lint['source_sha256'] == fixture_hash
else:
    command = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js',
               'src/pages/inbox/index.replies.test.jsx']
    checked = subprocess.run(command, cwd=root / 'frontend', capture_output=True, text=True, encoding='utf-8')
    (out / 'lint-fixture-final.log').write_text(checked.stdout + checked.stderr, encoding='utf-8')
    lint = dict(exit_code=checked.returncode, source_sha256=fixture_hash, command=command)
    lint_path.write_text(json.dumps(lint, indent=2), encoding='utf-8')
assert lint['exit_code'] == 0, 'Final fixture lint failed'

paths = [
    'frontend/src/api/inbox.js', 'frontend/src/api/inbox.test.js',
    'frontend/src/pages/inbox/index.jsx', 'frontend/src/pages/inbox/index.replies.test.jsx',
    'frontend/src/pages/inbox/inbox.module.css',
    'docs/modules/frontend.md', 'docs/CIERRE-INBOX-WHATSAPP.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md',
    *[f'docs/evals/inbox-rpl-05-2026-10-21/{name}' for name in
      ['README.md', 'run_checks.py', 'check_browser.py', 'run_browser.py', 'verify.py']],
]
assert (root / 'docs/modules/frontend.md').read_text(encoding='utf-8').count(
    '### WhatsApp Inbox: composer de respuesta citada (WA-RPL-05)') == 1
assert (root / 'CHANGELOG.md').read_text(encoding='utf-8').count('- Inbox, WA-RPL-05:') == 1
for path in paths:
    if path.endswith('.py'):
        ast.parse((root / path).read_text(encoding='utf-8'))
check = subprocess.run(['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths],
                       cwd=root, capture_output=True, text=True, encoding='utf-8')
assert check.returncode == 0, check.stdout + check.stderr
artifacts = [path for path in out.iterdir() if path.suffix in ['.json', '.log', '.png']]
manifest = dict(
    status='PASS', scope='WA-RPL-05 quoted reply composer', unique_pass=len(results),
    new_cases=new_cases, affected_cases=len(results) - new_cases, results=results,
    initial_failure=dict(receipt='new-directed-vitest.json', ids=sorted(initial_failed),
                         cause='Fixture mocked timers without Date; corrected only the clock and reran one case'),
    source_sha256={path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths},
    artifact_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts},
    working_database_migrated=False, backend_changed=False, synthetic_browser_api=True,
    native_provider_citation='IMPLEMENTATION_PENDING', real_meta='POSTPONED_PENDING',
    next_task='WA-RPL-06',
    diff_check=dict(exit_code=check.returncode, stdout=check.stdout, stderr=check.stderr),
)
destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: 61 unique frontend tests (27 new, 34 affected), build, lint, Chromium, cleanup and final hashes')
