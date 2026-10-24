"""Apply only the two input-setup substitutions expressly authorized by the user."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-correction-20261020-native-r9')
OLD_TREE = 'b271e314817da51e99811cb18921fd7c9f59e58a'
TARGET = 'frontend/src/pages/inbox/index.test.jsx'
RTK = 'C:/Users/LAP/.local/bin/rtk.exe'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, data):
    p = HERE / name
    assert not p.exists(), p
    with p.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def run(*args, env=None):
    return subprocess.check_output([RTK, 'proxy', 'git', *map(str, args)], cwd=REPO,
        env=env or os.environ.copy(), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    assert not (HERE / 'candidate.json').exists()
    proposal = PRIOR / 'diagnostics/frontend-draft-proposal'
    analysis = json.loads((proposal / 'analysis.json').read_text(encoding='utf-8'))
    patch = (proposal / 'draft-input-correction.diff').read_bytes()
    assert sha(patch) == analysis['patch_sha256'] == '3d94186cda394428dc02e633b6b8d7478a3ad3b07382b5970645fcd0fdea1bf9'
    path = REPO / TARGET
    raw = path.read_bytes()
    original = raw.replace(b'\r\n', b'\n')
    assert sha(raw) == analysis['source_worktree_sha256']
    assert sha(original) == analysis['original_canonical_lf_sha256']
    assert original == run('show', OLD_TREE + ':' + TARGET)
    source = original.decode('utf-8')
    for composer in ('firstComposer', 'returnedComposer'):
        old = f'        await user.type({composer}, "Texto idéntico, intención nueva");'
        new = f'        fireEvent.change({composer}, {{ target: {{ value: "Texto idéntico, intención nueva" }} }});'
        assert source.count(old) == 1
        source = source.replace(old, new, 1)
    corrected = source.encode('utf-8')
    assert sha(corrected) == analysis['proposed_canonical_lf_sha256'] == '21de54d2d3d1b1ad629b76aca48242249c22889c1cfb0962cabc529956a2ecd2'
    assert ''.join(difflib.unified_diff(original.decode().splitlines(True), source.splitlines(True),
        fromfile='a/' + TARGET, tofile='b/' + TARGET)).encode('utf-8') == patch
    assert analysis['normalized_complete_module_AST_identical'] is True
    assert analysis['exactly_two_awaited_user_type_statements_replaced'] is True
    assert analysis['assertions_imports_timeouts_test_ids_clicks_navigation_promises_confirmations_unchanged'] is True
    assert analysis['test_expect_calls'] == 8
    save('index-before-frontend-correction.json', {'raw_staged_sha256': sha(run('ls-files', '--stage', '-z')),
        'head': run('rev-parse', 'HEAD').decode().strip(), 'branch': run('branch', '--show-current').decode().strip()})
    path.write_bytes(corrected.replace(b'\n', b'\r\n') if b'\r\n' in raw else corrected)
    run('add', '--', TARGET)
    assert run('show', ':' + TARGET) == corrected
    index = HERE / 'candidate-only.index'
    assert not index.exists()
    env = os.environ.copy()
    env['GIT_INDEX_FILE'] = str(index.resolve())
    run('read-tree', OLD_TREE, env=env)
    blob = run('hash-object', '-w', '--', TARGET).decode().strip().splitlines()[-1]
    assert len(blob) == 40 and all(c in '0123456789abcdef' for c in blob)
    run('update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + TARGET, env=env)
    candidate = run('write-tree', env=env).decode().strip()
    assert run('diff', '--name-only', OLD_TREE, candidate).decode().splitlines() == [TARGET]
    base = '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    changed = run('diff', '--name-only', base, candidate).decode().splitlines()
    (HERE / 'frontend-correction.diff').write_bytes(patch)
    (HERE / 'frontend-proposal-analysis.json').write_bytes((proposal / 'analysis.json').read_bytes())
    (HERE / 'correction.diff').write_bytes(run('diff', base, candidate, '--', *changed))
    save('frontend-resumption-authorization.json', {'state': 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL',
        'user_answer': 'Sí, ajustar ese armado y continuar sin repetir PASS',
        'recorded_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'previous_candidate_tree': OLD_TREE, 'candidate_tree': candidate, 'allowed_path': TARGET,
        'patch_sha256': sha(patch), 'retained_backend_ids': 3331, 'retained_backend_PASS': 3319,
        'retained_backend_expected_SKIPs': 12, 'retained_frontend_PASS': 354,
        'new_frontend_selected_ids': 1, 'retained_frontend_build_PASS': True,
        'original_frontend_timeout_and_exit_1_preserved': True,
        'all_three_historical_backend_FAILs_preserved': True,
        'accepted_historical_evidence_limitation': True, 'no_PASS_reruns': True,
        'all_new_guards_and_remaining_original_stages_required': True,
        'eight_assertions_and_original_5000ms_timeout_unchanged': True,
        'product_runtime_locks_changed': False,
        'commits_push_deploy_activation_authorized': False})
    save('candidate.json', {'base_commit': base, 'candidate_tree': candidate,
        'previous_candidate_tree': OLD_TREE, 'changed_paths': changed, 'only_new_change': TARGET,
        'commits_created': 0, 'pushes_performed': 0, 'authorization': 'frontend-resumption-authorization.json'})
    save('frontend-equivalence.json', {'state': 'PASS', 'previous_candidate_tree': OLD_TREE,
        'candidate_tree': candidate, 'allowed_path': TARGET, 'original_sha256': sha(original),
        'corrected_sha256': sha(corrected), 'original_git_blob': run('rev-parse', OLD_TREE + ':' + TARGET).decode().strip(),
        'corrected_git_blob': blob, 'original_bytes': len(original), 'corrected_bytes': len(corrected),
        'patch_sha256': sha(patch), 'normalized_complete_module_AST_identical': True,
        'only_two_input_setup_statements_changed': True,
        'eight_assertions_and_original_5000ms_timeout_unchanged': True,
        'all_other_3331_blobs_identical': True, 'test_ids_imports_hooks_unchanged': True,
        'retained_backend_and_frontend_build_unaffected': True,
        'original_timeout_and_all_historical_FAILs_preserved': True,
        'product_runtime_locks_changed': False, 'private_runtime_not_yet_updated': True,
        'proposal_analysis_sha256': sha((proposal / 'analysis.json').read_bytes())})
    save('temporary-candidate-index-retirement.json', {'state': 'PASS', 'path': str(index.resolve()),
        'sha256_before_removal': sha(index.read_bytes()), 'candidate_tree': candidate,
        'main_index_not_removed': True})
    index.unlink()
    print('FRONTEND_SETUP_CORRECTION_APPLIED_AND_STAGED', candidate, flush=True)


if __name__ == '__main__':
    main()
