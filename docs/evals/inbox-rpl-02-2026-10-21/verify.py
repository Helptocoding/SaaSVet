"""Verify the finite test selection, final sources, drift and cleanup receipts."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out/'manifest.json'
assert not destination.exists(), 'Never overwrite a manifest'
drift = json.loads((out/'drift-final.json').read_text(encoding='utf-8'))
assert drift['exit_code'] == 0 and not drift['working_database_migrated']
initial = json.loads((out/'backend-directed.json').read_text(encoding='utf-8'))
expected = set()
for label in initial['labels']:
    module = '.'.join(label.split('.')[:4])
    source = root/'backend'/Path(*module.split('.')).with_suffix('.py')
    for cls in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(cls, ast.ClassDef):
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                    candidate = f'{module}.{cls.name}.{method.name}'
                    if candidate == label or candidate.startswith(label+'.'):
                        expected.add(candidate)
results = {}
for path in sorted(out.glob('backend-*.json'), key=lambda item: item.stat().st_mtime_ns):
    receipt = json.loads(path.read_text(encoding='utf-8'))
    assert not receipt['working_database_migrated'] and not receipt['test_database_remains']
    current = None
    for line in path.with_suffix('.log').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^test_\w+ \(([^)]+)\)(?: \.\.\.\s*(.*))?$', line)
        if match:
            current, line = match[1], match[2] or ''
        verdict = re.search(r'(?:^|\.\.\. )(ok|FAIL|ERROR)$', line.strip())
        if current and verdict:
            results[current] = dict(status='passed' if verdict[1] == 'ok' else 'failed', receipt=path.name)
            current = None
assert expected == set(results), (len(expected), len(results), expected-set(results))
assert len(results) == 40
assert all(item['status'] == 'passed' for item in results.values())
paths = ['backend/apps/channels/replies.py', 'backend/apps/channels/views.py',
    'backend/apps/agent/services.py', 'backend/apps/channels/tests/test_replies_webhook.py',
    'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md',
    'docs/modules/agent.md', 'CHANGELOG.md']
for path in paths:
    if path.endswith('.py'):
        ast.parse((root/path).read_text(encoding='utf-8'))
command = ['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths]
check = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
assert check.returncode == 0, check.stdout+check.stderr
manifest = dict(status='PASS', scope='WA-RPL-02 signed inbound citations',
    unique_pass=len(results), new_cases=21, affected_cases=19, results=results,
    source_sha256={path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in paths},
    drift='drift-final.json', working_database_migrated=False, new_migrations=False,
    real_meta='POSTPONED_PENDING', next_task='WA-RPL-03',
    diff_check=dict(exit_code=check.returncode, stdout=check.stdout, stderr=check.stderr))
destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: 40 unique PostgreSQL cases, drift, cleanup, diff check and final source hashes')
