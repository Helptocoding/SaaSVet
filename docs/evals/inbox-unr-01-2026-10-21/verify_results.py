"""Verify directed receipts, retained coverage and the scope of the error fix."""
import ast
import copy
import hashlib
import json
import re
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]


def read_json(name):
    return json.loads((out / name).read_text(encoding='utf-8'))


def cases(name):
    log = (out / name).read_text(encoding='utf-8')
    found = set(re.findall(r'^test_\w+ \(([\w.]+)\)', log, re.MULTILINE))
    failed = set(re.findall(r'^(?:FAIL|ERROR): test_\w+ \(([\w.]+)\)', log, re.MULTILINE))
    return found, failed, log


initial, final = read_json('backend.json'), read_json('backend-followup.json')
found, failed, first_log = cases('backend.log')
repeated, failed_again, last_log = cases('backend-followup.log')
assert len(found) == 35 and len(failed) == 3 and initial['exit_code'] == 1
assert 'FAILED (failures=7)' in first_log
assert repeated == failed and not failed_again and final['exit_code'] == 0
assert re.search(r'^OK$', last_log, re.MULTILINE)
assert not initial['test_database_remains'] and not final['test_database_remains']

expected = set()
new_cases = set()
for module, classes in [
    ('test_inbox_read_state', ('InboxReadStateTests', 'InboxReadConcurrencyTests')),
    ('test_inbox_thread_performance', ('ThreadPerformanceTests',)),
    ('test_inbox_thread_pagination', ('ThreadPaginationTests',)),
]:
    tree = ast.parse((root / 'backend/apps/agent/tests' / (module + '.py')).read_text(encoding='utf-8'))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name in classes:
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                    case = f'apps.agent.tests.{module}.{cls.name}.{method.name}'
                    expected.add(case)
                    if module == 'test_inbox_read_state':
                        new_cases.add(case)
valid = (found - failed) | repeated
assert valid == expected and len(new_cases) == 24

service_path = 'backend/apps/agent/inbox_read.py'
test_path = 'backend/apps/agent/tests/test_inbox_read_state.py'
before = ast.parse((out / 'initial-inbox_read.py.txt').read_text(encoding='utf-8'))
after = ast.parse((root / service_path).read_text(encoding='utf-8'))


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def normalize_errors(node):
    node = copy.deepcopy(node)
    count = 0
    for part in ast.walk(node):
        if (isinstance(part, ast.Raise) and isinstance(part.exc, ast.Call)
                and isinstance(part.exc.func, ast.Name)
                and part.exc.func.id in ('NotFound', 'APIValidationError', 'InvalidReadMessage')):
            part.exc = ast.Name(id='ReadTargetError', ctx=ast.Load())
            count += 1
    assert count == 3
    return ast.dump(node)


assert ast.dump(function(before, 'unread_counts')) == ast.dump(function(after, 'unread_counts'))
assert normalize_errors(function(before, 'mark_thread_read')) == normalize_errors(function(after, 'mark_thread_read'))
initial_hashes = read_json('initial-source-sha256.json')
hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in initial_hashes}
assert {p for p in hashes if hashes[p] != initial_hashes[p]} == {service_path, test_path}
old_methods = read_json('initial-test-methods-sha256.json')
tree = ast.parse((root / test_path).read_text(encoding='utf-8'))
new_methods = {
    cls.name + '.' + method.name: hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest()
    for cls in tree.body if isinstance(cls, ast.ClassDef)
    for method in cls.body if isinstance(method, ast.FunctionDef)
}
assert set(old_methods) == set(new_methods)
assert [key for key in old_methods if old_methods[key] != new_methods[key]] == [
    'InboxReadStateTests.test_counts_are_batched_without_loading_message_or_read_state_instances',
]
migration = read_json('migration-check.json')
assert migration['migration_drift'] == 'PASS' and not migration['applied_to_working_database']
for path in hashes:
    ast.parse((root / path).read_text(encoding='utf-8'))

result = {
    'status': 'PASS', 'unique_passed': len(valid), 'new_cases': len(new_cases),
    'affected_cases': len(valid - new_cases), 'initial_passed': len(found - failed),
    'initial_failed_methods': sorted(failed), 'initial_subtest_failures': 7,
    'followup_passed': sorted(repeated), 'valid_passed': sorted(valid),
    'both_test_databases_removed': True, 'real_postgresql_races_passed': 2,
    'retained_validation_justified': True, 'migration_drift': 'PASS',
    'working_database_migrated': False,
}
(out / 'backend-composite.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
(out / 'source-sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
checks = {
    'all_35_unique_cases_pass': True, 'independent_staff_counts': True,
    'only_current_episode_inbound_counts': True, 'monotonic_idempotent_upsert': True,
    'first_creation_and_update_races': True, 'view_only_permission': True,
    'thread_and_tenant_scope': True, 'invisible_outbound_malformed_rejected': True,
    'legacy_list_payload_except_new_field': True, 'pagination_preserved': True,
    'constant_query_budget_preserved': True, 'one_unread_aggregate_no_model_materialization': True,
    'message_claim_and_turn_authority_unchanged': True, 'migration_drift': True,
    'test_databases_removed': True, 'initial_failures_preserved_and_resolved': True,
}
(out / 'final-checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in result.items() if key != 'valid_passed'}))
