"""Apply only the two exact expected-list corrections expressly authorized by the user."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-correction-20261019-native-r7')
OLD_TREE = '68dffd746793700071f577a58528b0f9636930db'
TARGET = 'backend/apps/agent/tests/test_contracts.py'
RTK = 'C:/Users/LAP/.local/bin/rtk.exe'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, value):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def run(*args, env=None):
    return subprocess.check_output([RTK, 'proxy', 'git', *map(str, args)], cwd=REPO,
        env=env or os.environ.copy(), stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    assert not (HERE / 'snapshot-resumption-authorization.json').exists()
    patch = PRIOR / 'diagnostics/contract-snapshot-proposal.patch'
    analysis = json.loads((PRIOR / 'diagnostics/contract-snapshot-analysis.json').read_text(encoding='utf-8'))
    assert sha(patch.read_bytes()) == analysis['patch_sha256'] == '6d13efc117f33e26f1701dc568b881a1758adfdfdd3f53bc874b0a9989512a50'
    path = REPO / TARGET
    raw = path.read_bytes()
    assert sha(raw) == analysis['original_source_sha256']
    before = raw.replace(b'\r\n', b'\n')
    assert before == run('show', OLD_TREE + ':' + TARGET)
    source = before.decode('utf-8')
    tree = ast.parse(source)
    replacements = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name not in analysis['before']:
            continue
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'test_fields_match_snapshot')
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'assertEqual')
        expected = call.args[1]
        assert isinstance(expected, ast.List) and ast.literal_eval(expected) == analysis['before'][cls.name]
        after = analysis['after'][cls.name]
        lines = source.splitlines(True)
        start = sum(len(s) for s in lines[:expected.lineno - 1]) + expected.col_offset
        end = sum(len(s) for s in lines[:expected.end_lineno - 1]) + expected.end_col_offset
        if cls.name == 'ToolOutcomeContractTests':
            replacement = "[\n            'client_error', 'completeness', 'cursor', 'data', 'detail',\n            'effects', 'error_kind', 'has_more', 'kind', 'observed_at',\n            'operation_key', 'origin', 'partial_effects', 'retryable',\n            'scope', 'summary', 'validated',\n        ]"
        else:
            replacement = source[start:end].replace(
                "'asked', 'attempts_failed', 'authorization_message', 'blocked_reason', 'closed_at',",
                "'asked', 'attempts_failed', 'authorization_message', 'binding_revision',\n            'blocked_reason', 'bound_appointment', 'bound_owner', 'bound_pet', 'closed_at',")
        assert ast.literal_eval(ast.parse(replacement, mode='eval').body) == after
        replacements.append((start, end, replacement))
    assert len(replacements) == 2
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    corrected = source.encode('utf-8')
    assert sha(corrected) == analysis['proposed_canonical_lf_sha256'] == 'fc2d8f4152c25e41700235330a8411ccc9066c64bc3089eb07c7c352cc366aff'
    normalized = ast.parse(source)
    for module in (tree, normalized):
        for cls in module.body:
            if isinstance(cls, ast.ClassDef) and cls.name in analysis['before']:
                method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'test_fields_match_snapshot')
                call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'assertEqual')
                call.args[1] = ast.Constant(value='AUTHORIZED_EXPECTED_FIELDS_ONLY')
    assert ast.dump(tree, include_attributes=False) == ast.dump(normalized, include_attributes=False)
    save('snapshot-resumption-authorization.json', {'state': 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL',
        'user_answer': 'Sí, corregir esos snapshots y continuar sin repetir PASS',
        'recorded_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'previous_candidate_tree': OLD_TREE, 'allowed_path': TARGET,
        'patch_sha256': sha(patch.read_bytes()), 'retained_general_PASS': 2888,
        'retained_expected_SKIPs': 2, 'new_missing_ids': 321, 'corrected_FAILED_ids': 2,
        'old_FAILs_preserved': True, 'accepted_historical_evidence_limitation': True,
        'product_runtime_locks_changed': False, 'no_PASS_reruns': True,
        'all_new_guards_and_remaining_original_stages_required': True,
        'commits_push_deploy_activation_authorized': False})
    # Preserve every existing staged entry; stage only this newly authorized test file.
    save('index-before-snapshot-correction.json', {'raw_staged_sha256': sha(run('ls-files', '--stage', '-z')),
        'head': run('rev-parse', 'HEAD').decode().strip(), 'branch': run('branch', '--show-current').decode().strip()})
    output = corrected.replace(b'\n', b'\r\n') if b'\r\n' in raw else corrected
    path.write_bytes(output)
    assert path.read_bytes().replace(b'\r\n', b'\n') == corrected
    run('add', '--', TARGET)
    assert run('show', ':' + TARGET) == corrected
    index = HERE / 'candidate-only.index'
    assert not index.exists()
    env = os.environ.copy()
    env['GIT_INDEX_FILE'] = str(index.resolve())
    run('read-tree', OLD_TREE, env=env)
    blob = run('hash-object', '-w', '--', TARGET).decode().strip()
    run('update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + TARGET, env=env)
    candidate = run('write-tree', env=env).decode().strip()
    assert run('diff', '--name-only', OLD_TREE, candidate).decode().splitlines() == [TARGET]
    base = '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    changed = run('diff', '--name-only', base, candidate).decode().splitlines()
    (HERE / 'snapshot-correction.diff').write_bytes(patch.read_bytes())
    (HERE / 'correction.diff').write_bytes(run('diff', base, candidate, '--', *changed))
    save('candidate.json', {'base_commit': base, 'candidate_tree': candidate,
        'previous_candidate_tree': OLD_TREE, 'changed_paths': changed,
        'only_new_change': TARGET, 'commits_created': 0, 'pushes_performed': 0,
        'authorization': 'snapshot-resumption-authorization.json'})
    save('snapshot-equivalence.json', {'state': 'PASS', 'previous_candidate_tree': OLD_TREE,
        'candidate_tree': candidate, 'allowed_path': TARGET,
        'original_sha256': sha(before), 'corrected_sha256': sha(corrected),
        'original_git_blob': run('rev-parse', OLD_TREE + ':' + TARGET).decode().strip(),
        'corrected_git_blob': blob, 'original_bytes': len(before), 'corrected_bytes': len(corrected),
        'patch_sha256': sha(patch.read_bytes()), 'only_two_expected_literal_lists_change_ast': True,
        'assertions_other_AST_unchanged': True, 'all_other_3331_blobs_identical': True,
        'test_ids_imports_hooks_unchanged': True, 'old_FAILs_preserved': True,
        'product_runtime_locks_changed': False, 'private_runtime_not_yet_updated': True})
    print('SNAPSHOT_CORRECTION_APPLIED_AND_STAGED', candidate, flush=True)


if __name__ == '__main__':
    main()
