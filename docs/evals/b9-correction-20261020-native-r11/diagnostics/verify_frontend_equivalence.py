"""Extract the immutable prior fixture and parse old/new JSX; never run app tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from native_support import NODE, REPO, RTK, TREE, environment

OLD_TREE = 'b271e314817da51e99811cb18921fd7c9f59e58a'
NEW_TREE = 'f5f18d71847a46d66644775cd90d30268f072e3b'
TARGET = 'frontend/src/pages/inbox/index.test.jsx'
OLD_SHA = '8a98f6857430d5dee656e3b3ddc57a1bcecfd1f98a3c28f72cd328681d03961f'
NEW_SHA = '21de54d2d3d1b1ad629b76aca48242249c22889c1cfb0962cabc529956a2ecd2'
PATCH_SHA = '3d94186cda394428dc02e633b6b8d7478a3ad3b07382b5970645fcd0fdea1bf9'
PARSER_SHA = '201724d1415df7749087d9d6e88af50f2bcafe2eb68dfbe9347f49d3361ff426'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def invoke(argv):
    return subprocess.run(list(map(str, argv)), cwd=REPO, env=environment(), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    original_path = HERE / 'diagnostics/frontend-fixture-original.jsx'
    output_path = HERE / 'diagnostics/frontend-fixture-ast-check.json'
    node_helper = HERE / 'diagnostics/verify_frontend_equivalence.cjs'
    parser = TREE / 'frontend/node_modules/@babel/parser/lib/index.js'
    assert not (HERE / 'evaluation-seal.json').exists(), 'Fixture parsing must precede the formal seal'
    assert not (HERE / 'invocation-formal.json').exists(), 'No parser mutation during a formal invocation'
    assert not output_path.exists() and not original_path.exists(), 'No diagnostic evidence overwrite'
    assert read('candidate.json')['candidate_tree'] == NEW_TREE
    authorization = read('frontend-resumption-authorization.json')
    assert authorization['user_answer'] == 'Sí, ajustar ese armado y continuar sin repetir PASS'
    assert authorization['previous_candidate_tree'] == OLD_TREE and authorization['candidate_tree'] == NEW_TREE
    assert authorization['eight_assertions_and_original_5000ms_timeout_unchanged'] is True
    equivalent = read('frontend-equivalence.json')
    assert equivalent['normalized_complete_module_AST_identical'] is True
    assert equivalent['original_sha256'] == OLD_SHA and equivalent['corrected_sha256'] == NEW_SHA
    assert digest((HERE / 'frontend-correction.diff').read_bytes()) == authorization['patch_sha256'] == PATCH_SHA
    private_raw, repo_raw = (TREE / TARGET).read_bytes(), (REPO / TARGET).read_bytes()
    private_source, repo_source = private_raw.replace(b'\r\n', b'\n'), repo_raw.replace(b'\r\n', b'\n')
    assert private_source == repo_source and digest(private_source) == NEW_SHA
    assert digest(parser.read_bytes()) == PARSER_SHA
    git_argv = [RTK, 'proxy', 'git', 'show', OLD_TREE + ':' + TARGET]
    original = invoke(git_argv)
    assert original.returncode == 0, original.stderr.decode('utf-8', errors='replace')
    assert digest(original.stdout) == OLD_SHA
    original_path.parent.mkdir(parents=True, exist_ok=True)
    with original_path.open('xb') as stream:
        stream.write(original.stdout)
    node_argv = [RTK, 'proxy', NODE, node_helper, parser, original_path, TREE / TARGET]
    result = invoke(node_argv)
    stdout, stderr = result.stdout.decode('utf-8'), result.stderr.decode('utf-8', errors='replace')
    try:
        parsed = json.loads(stdout)
    except ValueError:
        parsed = {'state': 'INVALID_PARSER_RECEIPT', 'stdout': stdout}
    passed = result.returncode == 0 and parsed.get('state') == 'PASS'
    passed = passed and parsed.get('normalized_complete_module_AST_identical') is True
    passed = passed and parsed.get('only_two_input_setup_statements_changed') is True
    passed = passed and parsed.get('test_expect_calls') == 8 and parsed.get('target_test_argument_count') == 2
    passed = passed and parsed.get('application_source_executed') is False
    passed = passed and parsed.get('application_tests_executed') is False
    receipt = {'state': 'PASS' if passed else 'NONPASS', 'candidate_tree': NEW_TREE,
        'previous_candidate_tree': OLD_TREE, 'source_path': TARGET, 'parse_only': True,
        'application_tests_executed': False, 'application_source_executed': False,
        'original_extraction': {'argv': list(map(str, git_argv)), 'actual_exit_code': original.returncode,
            'artifact': original_path.relative_to(HERE).as_posix(), 'sha256': digest(original.stdout)},
        'node_parsing': {'argv': list(map(str, node_argv)), 'actual_exit_code': result.returncode,
            'stderr': stderr, 'receipt': parsed},
        'hashes': {'original_canonical': OLD_SHA, 'corrected_private_raw': digest(private_raw),
            'corrected_private_canonical': digest(private_source), 'corrected_checkout_raw': digest(repo_raw),
            'corrected_checkout_canonical': digest(repo_source), 'parser': PARSER_SHA,
            'python_helper': digest(Path(__file__).read_bytes()), 'node_helper': digest(node_helper.read_bytes())},
        'normalized_complete_module_AST_identical': bool(passed),
        'only_two_input_setup_statements_changed': bool(passed), 'test_expect_calls': parsed.get('test_expect_calls'),
        'eight_assertions_and_original_5000ms_timeout_unchanged': bool(passed)}
    with output_path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    print('FRONTEND_FIXTURE_AST_' + receipt['state'], flush=True)
    raise SystemExit(0 if passed else result.returncode or 1)


if __name__ == '__main__':
    main()
