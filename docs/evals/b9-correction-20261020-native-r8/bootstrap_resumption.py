"""Assemble only the authorized 323-case continuation; preserve the existing installation."""
import ast
import hashlib
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261019-native-r7')
REPO = HERE.parents[2]
OLD_TREE = '68dffd746793700071f577a58528b0f9636930db'
PATH = 'backend/apps/agent/tests/test_contracts.py'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(name, value):
    target = HERE / name
    assert not target.exists(), target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'native_support.py').exists()
    candidate = read(HERE / 'candidate.json')
    new = candidate['candidate_tree']
    assert candidate['previous_candidate_tree'] == OLD_TREE
    proof_path = PRIOR / 'diagnostics/resumption-after-r7/prefix-validation.json'
    proof = read(proof_path)
    assert proof['candidate_tree'] == OLD_TREE
    assert proof['state'] == 'PASS_INTEGRITY_WITH_RECORDED_FAILURES'
    assert all(not proof['current_byte_integrity'][key]['mismatches'] and not proof['current_byte_integrity'][key]['missing']
               for key in ('sources', 'dependencies', 'evaluation_seal'))
    assert all(proof['original_inputs_unchanged_during_audit'].values())
    assert not proof['audit_problems'] and not proof['guard_coverage_problems']
    auth_path = HERE / 'snapshot-resumption-authorization.json'
    auth = read(auth_path)
    assert auth['user_answer'] == 'Sí, corregir esos snapshots y continuar sin repetir PASS'
    auth['candidate_tree'] = new
    auth_path.write_text(json.dumps(auth, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    copied = []
    helpers = ['native_support.py', 'run_campaign.py', 'recorded_suite.py', 'full_partition.py',
        'awake_guard.py', 'awake_status.py', 'host_resources.py', 'host_observer.py', 'clock_probe.py',
        'launch_native.py', 'capture_native.py', 'cleanup_native.py', 'deliver_native.py',
        'restore_native.py', 'scan_security.py', 'finalize_preflight.py']
    for name in helpers:
        source, target = PRIOR / name, HERE / name
        assert not target.exists(), name
        text = source.read_text(encoding='utf-8')
        if name in ('native_support.py', 'recorded_suite.py'):
            text = text.replace(OLD_TREE, new)
        if name == 'run_campaign.py':
            text = text.replace("'formal-preparation-resumption.json','preparation-history-manifest.json','preparation-native-closure.json',",
                "'snapshot-resumption-authorization.json','snapshot-equivalence.json','case-resumption-inputs.json',\n        'snapshot-correction.diff','resumption.json',")
            text = text.replace("    assert json.loads((EVIDENCE/'diagnostics/fixture-clock-focused-check.json').read_text(encoding='utf-8'))['state']=='PASS'", "    assert json.loads((EVIDENCE/'diagnostics/fixture-clock-focused-check.json').read_text(encoding='utf-8'))['state']=='PASS'")
        if name == 'finalize_preflight.py':
            text = text.replace('b9-correction-20261017-native-r6', PRIOR.name).replace("'native-r6/'", "'native-r7/'")
        if name == 'deliver_native.py':
            text = text.replace('native-r7', 'native-r8').replace('native-20261017-r5', 'native-20261020-r8')
        target.write_text(text, encoding='utf-8', newline='\n')
        copied.append({'path': name, 'source': '../' + PRIOR.name + '/' + name,
            'source_sha256': sha(source.read_bytes()), 'sha256': sha(target.read_bytes())})
    names = ['PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json',
        'candidate-input.json', 'candidate-sources.json', 'toolchain.json', 'python-environment.json',
        'base-python-environment.json', 'dependency-files.json', 'interpreter-preflight.json',
        'private-python-copy.json', 'frontend-layout.json', 'security-history.json',
        'install-cache-retirement.json', 'fixture-clock-authorization.json', 'fixture-resumption-amendment.json',
        'downloads.json', 'audit-toolchain.json', 'profile-compatibility.json', 'effective-configuration.json',
        'checkout-before.json', 'full-partition-contract.json', 'full-partition.json', 'discovery.json',
        'discovery-skip-annotations.json', 'operational-lifetime-amendment.json', 'runtime-handoff-supplement.json',
        'prepared-runtime-references.json', 'RESUMPTION-PROPOSAL.md', 'case-resumption-authorization.json',
        'diagnostics/verify_fixture_clock.py', 'diagnostics/fixture-clock-focused-check.json',
        'diagnostics/verify_preserved_contract.py', 'private-postgresql/postgresql.conf', 'private-postgresql/pg_hba.conf']
    names += [p.name for p in PRIOR.glob('*-selected.json') if p.name != 'full-general-remainder-selected.json']
    for name in dict.fromkeys(names):
        source, target = PRIOR / name, HERE / name
        assert source.exists() and not target.exists(), name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    manifest = read(HERE / 'candidate-sources.json')
    corrected = (REPO / PATH).read_bytes().replace(b'\r\n', b'\n')
    equivalence = read(HERE / 'snapshot-equivalence.json')
    assert sha(corrected) == equivalence['corrected_sha256']
    target_row = next(row for row in manifest['files'] if row['path'] == PATH)
    target_row.update(sha256=sha(corrected), git_blob=equivalence['corrected_git_blob'], bytes=len(corrected))
    manifest.update(candidate_sha=new, source_export_candidate=OLD_TREE,
        export_method='Existing verified Git export plus only the exact authorized test snapshot replacement',
        source_manifest_sha256=sha((PRIOR / 'candidate-sources.json').read_bytes()),
        new_complete_git_archive_claimed=False)
    if 'archive_sha256' in manifest:
        manifest['previous_candidate_archive_sha256'] = manifest.pop('archive_sha256')
    (HERE / 'candidate-sources.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    work = Path(read(PRIOR / 'assembly.json')['workspace'])
    private = work / 'src' / PATH
    assert sha(private.read_bytes()) == equivalence['original_sha256']
    private.write_bytes(corrected)
    for name in ('full-partition-contract.json', 'full-partition.json'):
        path = HERE / name
        data = read(path)
        assert data['candidate_tree'] == OLD_TREE
        data['candidate_tree'] = new
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    assembly = read(PRIOR / 'assembly.json')
    assembly.update(candidate_sha=new, phase='PREPARING_AUTHORIZED_SNAPSHOT_CONTINUATION',
        source_campaign=PRIOR.name, runtime_reinstalled=False,
        private_source_patch='snapshot-correction.diff')
    save('assembly.json', assembly)
    selection = read(PRIOR / 'code-selection.json')
    selection.update(explicit_paths=candidate['changed_paths'], candidate_tree=new,
        snapshot_authorization='snapshot-resumption-authorization.json')
    selection['staged_sha256'][PATH] = sha(corrected)
    save('code-selection.json', selection)
    save('authorization.json', {'user': auth['user_answer'], 'candidate_tree': new,
        'proof': 'snapshot-resumption-authorization.json', 'product_runtime_changes': False,
        'maximum_formal_runs_per_new_selection': 1, 'commits_push_deploy_activation_authorized': False})
    save('resumption.json', {'state': 'AUTHORIZED_SNAPSHOT_ONLY_CASE_SUCCESSOR', 'candidate_tree': new,
        'previous_candidate_tree': OLD_TREE, 'source_campaign': PRIOR.name,
        'retained_r6_PASS': 2483, 'retained_r6_SKIP': 2, 'retained_r7_PASS': 405,
        'old_r7_FAILs_preserved': 2, 'new_missing_cases': 321, 'corrected_failed_cases': 2,
        'new_selected_total': 323, 'no_PASS_reruns': True, 'reused_complete_PASS_blocks': 13,
        'runtime_reinstalled': False, 'candidate_other_3331_blobs_changed': False,
        'continuous_campaign_claimed': False, 'accepted_historical_evidence_limitation': True,
        'new_authorization': 'snapshot-resumption-authorization.json', 'helpers': copied})
    amendment = read(PRIOR / 'composite-amendment.json')
    amendment.update(candidate_tree=new, source_candidate_tree=OLD_TREE,
        user=auth['user_answer'], snapshot_authorization='snapshot-resumption-authorization.json',
        new_selected_general_cases=323, retained_r7_PASS=405,
        valid_failure_discarded=False, old_failures_preserved=2,
        prior_amendment='../' + PRIOR.name + '/composite-amendment.json')
    save('composite-amendment.json', amendment)
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Reanudación de snapshots autorizada\n\n'
            'El usuario aprobó «Sí, corregir esos snapshots y continuar sin repetir PASS». '
            'Únicamente se actualizan las dos listas exactas esperadas de campos en '
            'test_contracts.py conforme a los contratos B2/B6 ya vigentes. Se conservan '
            '2888 PASS y dos skips del grupo general. Se ejecutan 321 IDs sin resultado '
            'más los dos métodos corregidos, con nuevas fuentes y procedencia explícita. '
            'Los dos FAIL originales de r7, las interrupciones y sus exit desconocidos '
            'permanecen íntegros; no se transforman en PASS ni se atribuyen al nuevo árbol. '
            'La excepción autoriza solo ese cambio, manteniendo exactitud de assertions, '
            'IDs, hooks, cargas, gates y guards; producto y locks no cambian. Todos los '
            'bloques restantes y cinco perfiles siguen requeridos. La limitación de '
            'monitor histórico r6 ya aceptada continúa explícita. Sin commits, push, '
            'despliegue ni activación.\n')
    policy = read(HERE / 'resource-policy.json')
    policy.update(snapshot_resumption_authorization='snapshot-resumption-authorization.json')
    (HERE / 'resource-policy.json').write_text(json.dumps(policy, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    # Baseline eight unchanged execution/partition functions, independent of the new selection.
    for name, names in {'run_campaign.py': ('execute', 'check_suite', 'budget', 'gate', 'create_db'),
                        'full_partition.py': ('build_partition', 'projected_groups', 'validate_partition')}.items():
        def methods(p):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
        old, current = methods(PRIOR / name), methods(HERE / name)
        assert all(old[n] == current[n] for n in names), name
    prior = {}
    for folder in HERE.parent.iterdir():
        if folder.is_dir() and folder != HERE and (folder.name.startswith('b9-correction-') or folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): sha(p.read_bytes()) for p in folder.rglob('*')
                          if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    save('post-reboot-integrity-reference.json', {'source': '../' + PRIOR.name + '/diagnostics/resumption-after-r7/prefix-validation.json',
        'sha256': sha(proof_path.read_bytes()), 'checked_before_private_snapshot_correction': True,
        'scope': 'Current byte integrity after r7 reboot; historical observations keep their own limits'})
    print('R8_ASSEMBLED_323_SELECTED_NO_TESTS', new, len(prior), flush=True)


if __name__ == '__main__':
    main()
