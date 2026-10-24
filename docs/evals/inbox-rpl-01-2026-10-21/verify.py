"""Verify receipts, additive migration shape and final source hashes."""
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
for kind, tag in (('generate', 'initial'), ('drift', 'final')):
    receipt = json.loads((out/f'{kind}-{tag}.json').read_text(encoding='utf-8'))
    assert receipt['exit_code'] == 0
    assert receipt['working_database_migrated'] is False

results = {}
for receipt_path in sorted(out.glob('backend-*.json'), key=lambda path: path.stat().st_mtime_ns):
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    assert receipt['test_database_remains'] is False
    assert receipt['working_database_migrated'] is False
    current = None
    for line in receipt_path.with_suffix('.log').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^test_\w+ \(([^)]+)\)(?: \.\.\.\s*(.*))?$', line)
        if match:
            current, line = match[1], match[2] or ''
        verdict = re.search(r'(?:^|\.\.\. )(ok|FAIL|ERROR)$', line.strip())
        if current and verdict:
            results[current] = dict(status='passed' if verdict[1] == 'ok' else 'failed', receipt=receipt_path.name)
            current = None
expected = set()
for filename in ('test_replies_model.py', 'test_replies_migration.py', 'test_models.py'):
    source = root/'backend/apps/channels/tests'/filename
    for cls in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(cls, ast.ClassDef):
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                    expected.add(f'apps.channels.tests.{source.stem}.{cls.name}.{method.name}')
assert set(results) == expected, (len(results), len(expected), expected-set(results))
assert len(results) == 19
assert all(value['status'] == 'passed' for value in results.values())

sql = (out/'migration-initial.sql').read_text(encoding='utf-8')
assert 'ADD COLUMN "reply_to_id" bigint NULL' in sql
assert 'CREATE INDEX "message_reply_target"' in sql
assert 'REFERENCES "channels_message"("id")' in sql
assert not re.search(r'\b(UPDATE|DELETE|DROP|DEFAULT)\b', sql)
paths = ['backend/apps/channels/models.py', 'backend/apps/channels/replies.py',
    'backend/apps/channels/migrations/0016_message_reply_to.py',
    'backend/apps/channels/tests/test_replies_model.py',
    'backend/apps/channels/tests/test_replies_migration.py',
    'docs/CIERRE-INBOX-WHATSAPP.md', 'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md',
    'docs/modules/agent.md', 'CHANGELOG.md']
command = ['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths]
check = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
assert check.returncode == 0, check.stdout+check.stderr
destination.write_text(json.dumps(dict(status='PASS', scope='WA-RPL-01 local schema/application validation',
    backend_unique_pass=len(results), new_cases=14, affected_cases=5, results=results,
    source_sha256={path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in paths},
    migration_sql='migration-initial.sql', working_database_migrated=False,
    ordinary_and_preview_database_migration='M2 not applied',
    real_reception_meta='POSTPONED_PENDING', next_task='WA-RPL-02',
    diff_check=dict(exit_code=check.returncode, stdout=check.stdout, stderr=check.stderr)),
    ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: 19 unique backend cases, drift, additive SQL, cleanup and final source hashes')
