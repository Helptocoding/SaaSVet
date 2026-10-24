"""Seal the directed test receipts, query plan and final source hashes once."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out / 'manifest.json'
assert not destination.exists(), 'Never overwrite a manifest'

drift = json.loads((out / 'drift-final.json').read_text(encoding='utf-8'))
assert drift['exit_code'] == 0 and not drift['working_database_migrated']
results = {}
counts = {}
for filename, expected_count in [('backend-new.json', 25), ('backend-affected.json', 17)]:
    path = out / filename
    receipt = json.loads(path.read_text(encoding='utf-8'))
    assert receipt['exit_code'] == 0
    assert not receipt['working_database_migrated']
    assert not receipt['test_database_remains']
    expected = set()
    for label in receipt['labels']:
        module = '.'.join(label.split('.')[:4])
        source = root / 'backend' / Path(*module.split('.')).with_suffix('.py')
        for cls in ast.parse(source.read_text(encoding='utf-8')).body:
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                        candidate = f'{module}.{cls.name}.{method.name}'
                        if candidate == label or candidate.startswith(label + '.'):
                            expected.add(candidate)
    observed = {}
    current = None
    for line in path.with_suffix('.log').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^test_\w+ \(([^)]+)\)(?: \.\.\.\s*(.*))?$', line)
        if match:
            current, line = match[1], match[2] or ''
        verdict = re.search(r'(?:^|\.\.\. )(ok|FAIL|ERROR)$', line.strip())
        if current and verdict:
            assert current not in observed, f'Duplicate result: {current}'
            observed[current] = dict(
                status='passed' if verdict[1] == 'ok' else 'failed', receipt=filename,
            )
            current = None
    assert expected == set(observed), (filename, expected - set(observed), set(observed) - expected)
    assert len(observed) == expected_count, (filename, len(observed))
    assert all(item['status'] == 'passed' for item in observed.values())
    assert not set(results).intersection(observed), 'Directed selections must not overlap'
    results.update(observed)
    counts[filename] = len(observed)
assert len(results) == 42

plan = json.loads((out / 'query-plan-affected.json').read_text(encoding='utf-8'))
assert plan['synthetic'] and plan['total_messages'] == 6001 and plan['loaded_messages'] == 50
assert 0 < plan['stable_delta_bytes'] < plan['full_payload_bytes'] / 10
indexes = set()


def collect_indexes(value):
    if isinstance(value, dict):
        if 'Index Name' in value:
            indexes.add(value['Index Name'])
        for child in value.values():
            collect_indexes(child)
    elif isinstance(value, list):
        for child in value:
            collect_indexes(child)


collect_indexes(plan['explain'])
assert 'channels_me_organiz_c00b67_idx' in indexes
paths = [
    'backend/apps/agent/serializers.py',
    'backend/apps/agent/views.py',
    'backend/apps/agent/inbox_sync.py',
    'backend/apps/agent/tests/test_inbox_replies.py',
    'backend/apps/channels/replies.py',
    'docs/CIERRE-INBOX-WHATSAPP.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md',
    'docs/modules/agent.md',
    'CHANGELOG.md',
    'docs/evals/inbox-rpl-03-2026-10-21/README.md',
    'docs/evals/inbox-rpl-03-2026-10-21/run_checks.py',
    'docs/evals/inbox-rpl-03-2026-10-21/verify.py',
]
for path in paths:
    if path.endswith('.py'):
        ast.parse((root / path).read_text(encoding='utf-8'))
check = subprocess.run(
    ['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths],
    cwd=root, capture_output=True, text=True, encoding='utf-8',
)
assert check.returncode == 0, check.stdout + check.stderr
manifest = dict(
    status='PASS', scope='WA-RPL-03 quoted send API and transcript projection',
    unique_pass=len(results), new_cases=counts['backend-new.json'],
    affected_cases=counts['backend-affected.json'], results=results,
    source_sha256={path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths},
    drift='drift-final.json', working_database_migrated=False, new_migrations=False,
    query_plan=dict(
        artifact='query-plan-affected.json', total_messages=plan['total_messages'],
        loaded_messages=plan['loaded_messages'], full_payload_bytes=plan['full_payload_bytes'],
        stable_delta_bytes=plan['stable_delta_bytes'], domain_queries=plan['domain_queries'],
        execution_time_ms=plan['explain'][0]['Execution Time'], indexes=sorted(indexes),
    ),
    native_provider_citation='IMPLEMENTATION_PENDING', real_meta='POSTPONED_PENDING',
    next_task='WA-RPL-05',
    diff_check=dict(exit_code=check.returncode, stdout=check.stdout, stderr=check.stderr),
)
destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: 42 unique PostgreSQL cases (25 new, 17 affected), drift, cleanup, plan and final hashes')
