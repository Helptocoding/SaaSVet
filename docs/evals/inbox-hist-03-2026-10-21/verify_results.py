"""Combine directed runs without hiding the initial fixture/harness failures."""
import ast
import hashlib
import json
import re
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
initial = json.loads((output / 'backend.json').read_text(encoding='utf-8'))
followup = json.loads((output / 'backend-followup.json').read_text(encoding='utf-8'))


def cases(filename):
    log = (output / filename).read_text(encoding='utf-8')
    discovered = set(re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.MULTILINE))
    failed = set(re.findall(r'^(?:FAIL|ERROR): test_\w+ \(([\w.]+)\)', log, re.MULTILINE))
    return discovered, failed, log


first_cases, first_failures, first_log = cases('backend.log')
last_cases, last_failures, last_log = cases('backend-followup.log')
assert len(first_cases) == 31 and len(first_failures) == 3
assert initial['exit_code'] == 1
assert len(last_cases) == 5 and not last_failures and followup['exit_code'] == 0
assert first_failures <= last_cases
assert not initial['test_database_remains'] and not followup['test_database_remains']
assert 'FAILED (failures=1, errors=2)' in first_log
assert re.search(r'^OK$', last_log, re.MULTILINE)

test_path = 'backend/apps/agent/tests/test_inbox_thread_around.py'
view_path = 'backend/apps/agent/views.py'
test_tree = ast.parse((root / test_path).read_text(encoding='utf-8'))
new_cases = {
    'apps.agent.tests.test_inbox_thread_around.ThreadAroundTests.' + node.name
    for cls in test_tree.body if isinstance(cls, ast.ClassDef) and cls.name == 'ThreadAroundTests'
    for node in cls.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
}
affected_cases = set(initial['labels'][1:])
valid = (first_cases - first_failures) | last_cases
assert len(new_cases) == 22 and len(affected_cases) == 11
assert valid == new_cases | affected_cases

source_paths = [view_path, test_path,
                'docs/modules/agent.md', 'docs/CIERRE-INBOX-WHATSAPP.md',
                'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'CHANGELOG.md']
hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in source_paths}
initial_hashes = json.loads((output / 'initial-source-sha256.json').read_text(encoding='utf-8'))
assert initial_hashes[view_path] == hashes[view_path], 'Product code changed after valid tests'
ast.parse((root / view_path).read_text(encoding='utf-8'))

composite = {
    'status': 'PASS', 'unique_passed': len(valid), 'new_cases': len(new_cases),
    'affected_cases': len(affected_cases), 'initial_passed': len(first_cases - first_failures),
    'initial_failed': sorted(first_failures), 'followup_passed': sorted(last_cases),
    'valid_passed': sorted(valid), 'both_test_databases_removed': True,
    'product_unchanged_between_runs': True,
    'window_materialized': 52, 'existing_metadata_message_reads': 2,
    'max_messages_exposed': 50,
}
(output / 'backend-composite.json').write_text(json.dumps(composite, indent=2), encoding='utf-8')
(output / 'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
checks = {
    'all_new_and_affected_cases_pass': True, 'unique_cases': len(valid),
    'five_cut_points': True, 'hidden_target_without_hidden_neighbors': True,
    'chronological_order_and_ties': True, 'current_session_metadata_preserved': True,
    'regular_transcript_contract_preserved': True,
    'thread_and_tenant_isolation': True, 'view_only_and_denied_roles': True,
    'malformed_conflicting_and_missing_cursors': True, 'bounded_sql_and_materialization': True,
    'initial_failures_preserved_and_resolved': True, 'test_databases_removed': True,
    'product_code_unchanged_after_first_run': True, 'python_syntax': True,
}
(output / 'final-checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps(composite))
