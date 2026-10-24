"""Verify only evaluator syntax, frozen selections, AST preservation and references."""
import ast
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent.parent
PRIOR = HERE.with_name('b9-correction-20261020-native-r9')


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def functions(path):
    return {node.name: node for node in ast.parse(path.read_text(encoding='utf-8')).body
            if isinstance(node, ast.FunctionDef)}


def main():
    output = HERE / 'diagnostics/composite-validator-checks.json'
    assert not output.exists() and not (HERE / 'evaluation-seal.json').exists()
    manifest = read('completed-reference-manifest.json')
    bundle = HERE / manifest['bundle_relative']
    backend = read('backend-reference-validation.json')
    frontend = read('frontend-resumption-validation.json')
    fixture = read('diagnostics/frontend-fixture-ast-check.json')
    assert fixture['state'] == 'PASS'
    protected = ['_audit_block', '_audit_source', '_whitelist', '_resources', '_retained_seal',
        '_seal', '_absence', '_configuration', '_pg_configuration', '_package_versions', '_python_files', '_pg_files']
    old = functions(PRIOR / 'composite_evidence.py')
    retained = functions(bundle / 'composite_evidence.py')
    legacy_unchanged = all(ast.dump(old[name], include_attributes=False) ==
        ast.dump(retained[name], include_attributes=False) for name in protected)
    original_loop = next(n for n in ast.walk(functions(PRIOR / 'run_campaign.py')['run_all'])
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'scenario')
    current_loop = next(n for n in ast.walk(functions(HERE / 'run_campaign.py')['run_all'])
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'scenario')
    checks = {
        'retained_backend_and_build_validation_PASS': backend['state'] == 'PASS',
        'frontend_case_reference_validation_PASS': frontend['state'] == 'PASS',
        'frontend_exact_two_statement_AST_receipt_PASS': fixture['state'] == 'PASS',
        'frontend_selection_354_retained': len(read('frontend-retained-pass-selected.json')) == 354,
        'frontend_selection_one_new': len(read('frontend-remainder-selected.json')) == 1,
        'frontend_selection_full_355': len(read('frontend-full-selected.json')) == 355,
        'no_current_test_execution_yet': not (HERE / 'invocation-formal.json').exists(),
        'twelve_legacy_validator_ASTs_preserved': legacy_unchanged,
        'entire_PROFILE_loop_AST_preserved': ast.dump(original_loop, include_attributes=False) ==
            ast.dump(current_loop, include_attributes=False),
        'backend_complete_reference_is_old_candidate': manifest['source_candidate_tree'] ==
            'b271e314817da51e99811cb18921fd7c9f59e58a',
        'original_frontend_timeout_json_retained': sha(bundle / 'blocks/frontend-tests.json') ==
            manifest['files']['blocks/frontend-tests.json']['sha256'],
        'original_frontend_exit_1_retained': json.loads((bundle / 'blocks/frontend-test.command.json').read_text())['exit_code'] == 1,
    }
    paths = [*HERE.glob('*.py'), *HERE.glob('diagnostics/*.py')]
    source_hashes = {}
    for path in paths:
        text = path.read_text(encoding='utf-8')
        compile(text, str(path), 'exec')
        assert all(line == line.rstrip() for line in text.splitlines()), path
        source_hashes[path.relative_to(HERE).as_posix()] = sha(path)
    checks['source_syntax_and_whitespace'] = True
    receipt = {'state': 'PASS_VALIDATOR_CHECKS' if all(checks.values()) else 'FAIL',
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'candidate_tree': read('candidate.json')['candidate_tree'],
        'scope': 'Static evaluator and existing reference receipts only; no application tests executed',
        'application_tests_executed': False, 'services_changed': False,
        'checks': checks, 'source_sha256': source_hashes,
        'historical_protected_validator_functions': protected,
        'frontend_fixture_ast_receipt_sha256': sha(HERE / 'diagnostics/frontend-fixture-ast-check.json'),
        'backend_reference_validation_sha256': sha(HERE / 'backend-reference-validation.json'),
        'frontend_reference_validation_sha256': sha(HERE / 'frontend-resumption-validation.json')}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    assert all(checks.values()), checks
    print('EVALUATOR_CONTRACT_PASS_NO_APPLICATION_TESTS', len(checks), flush=True)


if __name__ == '__main__':
    main()
