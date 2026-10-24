"""Check only evaluator syntax, exact patch inversion and historical validator preservation."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent.parent
PRIOR = HERE.with_name('b9-correction-20261019-native-r7')
sys.path.insert(0, str(HERE))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    assert not (HERE / 'evaluation-seal.json').exists()
    output = HERE / 'diagnostics/composite-validator-checks.json'
    assert not output.exists()
    import composite_evidence as c
    import case_resumption as cases
    checks = {}
    assembly = json.loads((HERE / 'assembly.json').read_text(encoding='utf-8'))
    tree = Path(assembly['tree'])
    raw = (tree / c.SNAPSHOT_PATH).read_bytes()
    checks['exact_snapshot_inversion'] = c._snapshot_transform(raw)['original_sha256'] == c.OLD_SNAPSHOT_SHA
    checks['snapshot_authorization'] = c._snapshot_declaration()['candidate_tree'] == assembly['candidate_sha']
    checks['historical_clock_authorization'] = bool(c._authorization())
    checks['exact_clock_fixture_inversion'] = c._fixture_transform((tree / c.FIXTURE_PATH).read_bytes())['body_AST_identical']
    checks['normalized_candidate_3332_map'] = len(c._candidate(HERE, current=True)) == 3332
    checks['case_reference_partition'] = cases.validate_case_references()['new_selected_ids'] == 323
    for label, changed in [('extra_byte_rejected', raw + b' '),
                           ('weakened_assertion_rejected', raw.replace(b'self.assertEqual(fields, [', b'self.assertIn(fields, [', 1))]:
        try:
            c._snapshot_transform(changed)
        except (AssertionError, RuntimeError, ValueError):
            checks[label] = True
        else:
            checks[label] = False
    def functions(path):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
    before, after = functions(PRIOR / 'composite_evidence.py'), functions(HERE / 'composite_evidence.py')
    protected = ['_audit_block', '_audit_source', '_whitelist', '_resources', '_retained_seal',
        '_seal', '_absence', '_configuration', '_pg_configuration', '_package_versions', '_python_files', '_pg_files']
    checks['historical_validator_AST_unchanged'] = all(before[n] == after[n] for n in protected)
    sources = {p.relative_to(HERE).as_posix(): digest(p.read_bytes())
        for p in [*HERE.glob('*.py'), HERE / 'diagnostics/close_acceptance.py', Path(__file__).resolve()]}
    for name in sources:
        source = (HERE / name).read_text(encoding='utf-8')
        compile(source, str(HERE / name), 'exec')
        assert all(line == line.rstrip() for line in source.splitlines()), name
    checks['source_syntax_and_whitespace'] = True
    passed = all(checks.values())
    result = {'state': 'PASS_VALIDATOR_CHECKS' if passed else 'FAIL',
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'scope': 'Evaluator-only static and pure checks; no application tests/services executed',
        'application_tests_executed': False, 'services_changed': False,
        'candidate_tree': assembly['candidate_sha'], 'checks': checks,
        'historical_protected_validator_functions': protected,
        'source_sha256': sources, 'prior_validator_receipt_sha256': digest((PRIOR / 'diagnostics/composite-validator-checks.json').read_bytes())}
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    assert passed, checks
    print('EVALUATOR_CONTRACT_PASS_NO_APPLICATION_TESTS', len(checks), flush=True)


if __name__ == '__main__':
    main()
