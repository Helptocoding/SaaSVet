"""Check evaluator-only patch inverses and preserved validators before formal seal."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent.parent
PRIOR = HERE.with_name('b9-correction-20261020-native-r8')
sys.path.insert(0, str(HERE))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    assert not (HERE / 'evaluation-seal.json').exists()
    output = HERE / 'diagnostics/composite-validator-checks.json'
    assert not output.exists()
    import composite_evidence as c
    import case_resumption as cases
    assembly = json.loads((HERE / 'assembly.json').read_text(encoding='utf-8'))
    tree = Path(assembly['tree'])
    baseline = (tree / c.BASELINE_PATH).read_bytes()
    snapshot = (tree / c.SNAPSHOT_PATH).read_bytes()
    checks = {
        'exact_baseline_inversion': c._baseline_transform(baseline)['original_sha256'] == c.OLD_BASELINE_SHA,
        'baseline_authorization': c._baseline_declaration()['candidate_tree'] == assembly['candidate_sha'],
        'exact_snapshot_inversion': c._snapshot_transform(snapshot)['original_sha256'] == c.OLD_SNAPSHOT_SHA,
        'historical_snapshot_authorization': c._snapshot_declaration()['candidate_tree'] == c.SNAPSHOT_TREE_SHA,
        'historical_clock_authorization': bool(c._authorization()),
        'exact_clock_fixture_inversion': c._fixture_transform((tree / c.FIXTURE_PATH).read_bytes())['body_AST_identical'],
        'normalized_candidate_3332_map': len(c._candidate(HERE, current=True)) == 3332,
        'case_reference_partition': cases.validate_case_references()['new_selected_ids'] == 1,
    }
    for label, transform, changed in [
        ('baseline_extra_byte_rejected', c._baseline_transform, baseline + b' '),
        ('baseline_weakened_assertion_rejected', c._baseline_transform,
         baseline.replace(b'self.assertFalse(msg,', b'self.assertTrue(msg,', 1)),
        ('snapshot_extra_byte_rejected', c._snapshot_transform, snapshot + b' '),
        ('snapshot_weakened_assertion_rejected', c._snapshot_transform,
         snapshot.replace(b'self.assertEqual(fields, [', b'self.assertIn(fields, [', 1)),
    ]:
        try:
            transform(changed)
        except (AssertionError, RuntimeError, ValueError):
            checks[label] = True
        else:
            checks[label] = False
    def functions(path):
        return {n.name: ast.dump(n, include_attributes=False)
                for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
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
    result = {'state': 'PASS_VALIDATOR_CHECKS' if all(checks.values()) else 'FAIL',
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'scope': 'Evaluator-only static and pure checks; no application tests/services executed',
        'application_tests_executed': False, 'services_changed': False,
        'candidate_tree': assembly['candidate_sha'], 'checks': checks,
        'historical_protected_validator_functions': protected, 'source_sha256': sources,
        'prior_validator_receipt_sha256': digest((PRIOR / 'diagnostics/composite-validator-checks.json').read_bytes())}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    assert all(checks.values()), checks
    print('EVALUATOR_CONTRACT_PASS_NO_APPLICATION_TESTS', len(checks), flush=True)


if __name__ == '__main__':
    main()
