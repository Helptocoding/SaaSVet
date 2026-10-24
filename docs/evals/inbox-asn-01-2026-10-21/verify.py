"""Build a reproducible composite manifest without changing prior receipts."""
import ast
import hashlib
import json
from pathlib import Path
import re

out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out/'manifest.json'
assert not destination.exists(), 'Never overwrite a manifest'

backend = {}
for tag in ('new', 'remaining', 'pending', 'uuid'):
    receipt = json.loads((out/f'backend-{tag}.json').read_text(encoding='utf-8'))
    assert receipt['test_database_remains'] is False
    assert receipt['working_database_migrated'] is False
    current = None
    for line in (out/f'backend-{tag}.log').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^test_\w+ \(([^)]+)\) \.\.\.\s*(.*)', line)
        if match:
            current = match[1]
            line = match[2]
        if current and line.strip() in ('ok', 'FAIL', 'ERROR'):
            backend[current] = {'status': 'passed' if line.strip() == 'ok' else 'failed',
                'receipt': f'backend-{tag}.log'}
            current = None

source = root/'backend/apps/agent/tests/test_inbox_assignment.py'
expected = {f'apps.agent.tests.test_inbox_assignment.{cls.name}.{method.name}'
    for cls in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(cls, ast.ClassDef)
    for method in cls.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_')}
assert set(backend) == expected, (len(backend), len(expected), expected-set(backend))
assert len(backend) == 20
assert all(value['status'] == 'passed' for value in backend.values())

frontend = {}
for tag in ('new', 'turn', 'affected', 'selector-final', 'unmount'):
    data = json.loads((out/f'vitest-{tag}.json').read_text(encoding='utf-8'))
    for file in data['testResults']:
        for result in file['assertionResults']:
            if result['status'] in ('passed', 'failed'):
                frontend[result['fullName']] = {'status': result['status'], 'receipt': f'vitest-{tag}.json'}
assert len(frontend) == 25, len(frontend)
assert all(value['status'] == 'passed' for value in frontend.values())
for kind in ('build', 'lint'):
    assert json.loads((out/f'{kind}-final2.json').read_text(encoding='utf-8'))['exit_code'] == 0
browser = json.loads((out/'browser-check.json').read_text(encoding='utf-8'))
assert browser['status'] == 'PASS'
assert browser['mobile']['selector']['insideViewport']
assert browser['mobile']['draft'] == 'Borrador sintético conservado al asignar'

paths = [
    'backend/apps/agent/inbox_assignment.py', 'backend/apps/agent/views.py',
    'backend/apps/agent/urls.py', 'backend/apps/agent/tests/test_inbox_assignment.py',
    'frontend/src/api/inbox.js', 'frontend/src/pages/inbox/index.jsx',
    'frontend/src/pages/inbox/inbox.module.css', 'frontend/src/pages/inbox/ThreadAssignment.jsx',
    'frontend/src/pages/inbox/ThreadAssignment.test.jsx',
    'frontend/src/pages/inbox/index.assignment.test.jsx',
]
for path in paths:
    if path.endswith('.py'):
        ast.parse((root/path).read_text(encoding='utf-8'))
manifest = dict(status='PASS', scope='WA-ASN-01 local implementation',
    composite=True, backend_unique_pass=len(backend), frontend_unique_pass=len(frontend),
    backend=backend, frontend=frontend, browser='browser-check.json',
    build='build-final2.json', lint='lint-final2.json', working_database_migrated=False,
    new_migrations=False, real_reception_meta='POSTPONED_PENDING',
    source_sha256={path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in paths},
    applicability='Final UUID route correction changes acceptance of numeric IDs only; '
        'happy path and foreign/malformed cases retested. Earlier UUID-based permissions, '
        'fencing, audit and race results remain applicable. Selector event/loading change '
        'covered by all eight component tests; unmount guard covered separately.')
destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: manifest[key] for key in ('status', 'backend_unique_pass', 'frontend_unique_pass', 'composite')}))
