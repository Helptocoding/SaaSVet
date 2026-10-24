"""Create the pre-seal contract receipt using static Python inspection only."""
import ast
import hashlib
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent.parent
PRIOR = HERE.with_name('b9-correction-20261017-native-r5')
TREE_SHA = 'b271e314817da51e99811cb18921fd7c9f59e58a'
PROTECTED = {
    'run_campaign.py': ('execute', 'check_suite', 'budget', 'gate', 'create_db'),
    'full_partition.py': ('build_partition', 'projected_groups', 'validate_partition'),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def functions(raw):
    return {node.name: ast.dump(node, include_attributes=False)
            for node in ast.parse(raw.decode('utf-8')).body
            if isinstance(node, ast.FunctionDef)}


def main():
    output = HERE / 'diagnostics/preserved-contract-checks.json'
    if output.exists() or any((HERE / name).exists() for name in
                              ('evaluation-seal.json', 'invocation-formal.json', 'STOP.json')):
        raise RuntimeError('Contract verification requires a new receipt before the formal seal')
    candidate_path = HERE / 'candidate.json'
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    if candidate['candidate_tree'] != TREE_SHA:
        raise RuntimeError('Unexpected current candidate')
    identity, ast_hashes = {}, {}
    for name, protected in PROTECTED.items():
        current = functions((HERE / name).read_bytes())
        previous = functions((PRIOR / name).read_bytes())
        for function in protected:
            key = name + ':' + function
            identity[key] = function in current and function in previous and current[function] == previous[function]
            ast_hashes[key] = {
                'current': sha(current[function].encode()) if function in current else None,
                'prior_r5': sha(previous[function].encode()) if function in previous else None,
            }
    paths = sorted({*HERE.glob('*.py'), HERE / 'diagnostics/close_acceptance.py', Path(__file__).resolve()})
    hashes, issues, checked = {}, [], []
    for path in paths:
        relative = path.relative_to(HERE).as_posix()
        raw = path.read_bytes()
        hashes[relative] = sha(raw)
        try:
            source = raw.decode('utf-8')
            compile(source, str(path), 'exec')
            trailing = [number for number, line in enumerate(source.splitlines(), 1)
                        if line.rstrip() != line]
            if trailing:
                issues.append({'path': relative, 'trailing_whitespace_lines': trailing})
        except (UnicodeError, SyntaxError) as exc:
            issues.append({'path': relative, 'error_type': type(exc).__name__, 'error': str(exc)})
        checked.append(relative)
    changed = [name for name, digest in hashes.items() if sha((HERE / name).read_bytes()) != digest]
    passed = all(identity.values()) and len(identity) == 8 and not issues and not changed
    finalize = (HERE / 'finalize_preflight.py').read_text(encoding='utf-8')
    receipt = {
        'state': 'PASS' if passed else 'FAIL',
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'original_function_AST_identical': identity,
        'source_syntax_and_whitespace': 'PASS' if not issues else 'FAIL',
        'application_tests_executed': False,
        'candidate_tree': TREE_SHA,
        'scope': 'Static preservation of eight r5 functions; authorized fixture equivalence and aggregate provenance are documented separately; no application code is imported or executed',
        'helpers_sha256': hashes,
        'baseline_campaign': PRIOR.name,
        'function_AST_sha256': ast_hashes,
        'compiled_sources': checked,
        'static_issues': issues,
        'source_changes_during_verification': changed,
        'candidate_input_sha256': sha(candidate_path.read_bytes()),
        'finalize_preflight_metadata': {
            'formal_application_tests_executed_field_present': 'formal_application_tests_executed' in finalize,
            'preserved_contract_receipt_reference_present': 'preserved-contract-checks.json' in finalize,
        },
        'services_started': False,
        'application_modules_imported': False,
    }
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    if not passed:
        raise RuntimeError('Preserved contract verification failed; see retained receipt')
    print('PRESERVED_CONTRACT_PASS 8 functions ' + str(len(checked)) + ' sources', flush=True)
    print('FINALIZE_PREFLIGHT_SHA256 ' + hashes['finalize_preflight.py'], flush=True)
    print('RECEIPT_SHA256 ' + sha(output.read_bytes()), flush=True)


if __name__ == '__main__':
    main()
