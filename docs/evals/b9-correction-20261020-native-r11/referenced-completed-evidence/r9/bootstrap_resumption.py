"""Assemble the authorized one-case successor without reinstalling dependencies."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261020-native-r8')
REPO = HERE.parents[2]
OLD_TREE = '5e11236daabf4ef70ea9d0f08fee52aed5c30ff2'
TARGET = 'backend/apps/core/tests/test_tenant_scoping_audit.py'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, data):
    path = HERE / name
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'native_support.py').exists()
    candidate = read(HERE / 'candidate.json')
    new = candidate['candidate_tree']
    assert candidate['previous_candidate_tree'] == OLD_TREE
    auth = read(HERE / 'baseline-resumption-authorization.json')
    assert auth['user_answer'] == 'Sí, corregir ese baseline y continuar sin repetir PASS'
    proof_path = PRIOR / 'diagnostics/completed-prefix-validation.json'
    proof = read(proof_path)
    assert proof['state'] == 'PASS_INTEGRITY_WITH_RECORDED_FAILURE'
    assert proof['candidate_tree'] == OLD_TREE
    assert all(sha((PRIOR / name).read_bytes()) == h for name, h in proof['files'].items())
    assert read(PRIOR / 'final-classification.json')['decision'] == 'FAIL'
    work = Path(read(PRIOR / 'assembly.json')['workspace'])
    assert work.resolve() == Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6').resolve()
    assert not work.is_junction() and not work.is_symlink()
    old_manifest = read(PRIOR / 'candidate-sources.json')
    source_mismatches = [r['path'] for r in old_manifest['files']
        if not (work / 'src' / r['path']).is_file()
        or sha((work / 'src' / r['path']).read_bytes()) != r['sha256']]
    dependencies = read(PRIOR / 'dependency-files.json')
    dependency_mismatches = [p for p, h in dependencies['files'].items()
        if not Path(p).is_file() or sha(Path(p).read_bytes()) != h]
    old_seal = read(PRIOR / 'evaluation-seal.json')
    seal_mismatches = [p for p, h in old_seal['files'].items()
        if not Path(p).is_file() or sha(Path(p).read_bytes()) != h]
    save('pre-patch-current-integrity.json', {'state': 'PASS' if not source_mismatches + dependency_mismatches + seal_mismatches else 'FAIL',
        'candidate_tree': OLD_TREE, 'sources_checked': len(old_manifest['files']),
        'dependencies_checked': len(dependencies['files']), 'seal_checked': len(old_seal['files']),
        'source_mismatches': source_mismatches, 'dependency_mismatches': dependency_mismatches,
        'seal_mismatches': seal_mismatches, 'before_private_source_update': True})
    assert not source_mismatches + dependency_mismatches + seal_mismatches
    helpers = ['native_support.py', 'run_campaign.py', 'recorded_suite.py', 'full_partition.py',
        'awake_guard.py', 'awake_status.py', 'host_resources.py', 'host_observer.py', 'clock_probe.py',
        'launch_native.py', 'capture_native.py', 'cleanup_native.py', 'deliver_native.py',
        'restore_native.py', 'scan_security.py', 'finalize_preflight.py']
    copied = []
    for name in helpers:
        source, target = PRIOR / name, HERE / name
        assert not target.exists(), name
        text = source.read_text(encoding='utf-8')
        if name in ('native_support.py', 'recorded_suite.py'):
            text = text.replace(OLD_TREE, new)
        if name == 'run_campaign.py':
            text = text.replace("'snapshot-correction.diff','resumption.json',",
                "'snapshot-correction.diff','resumption.json',\n        'baseline-resumption-authorization.json','baseline-equivalence.json',\n        'baseline-correction.diff','baseline-proposal-analysis.json',")
        if name == 'finalize_preflight.py':
            text = text.replace('b9-correction-20261019-native-r7', PRIOR.name).replace('native-r7/', 'native-r8/')
        if name == 'deliver_native.py':
            text = text.replace('native-r8', 'native-r9').replace('native-20261020-r8', 'native-20261020-r9')
            anchor = "        f'docs/evals/{HERE.name}/correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n')"
            replacement = "        f'docs/evals/{HERE.name}/snapshot-correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'\n        f'docs/evals/{HERE.name}/baseline-correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'\n" + anchor
            assert anchor in text
            text = text.replace(anchor, replacement)
        target.write_text(text, encoding='utf-8', newline='\n')
        copied.append({'path': name, 'source': '../' + PRIOR.name + '/' + name,
            'source_sha256': sha(source.read_bytes()), 'sha256': sha(target.read_bytes())})
    names = ['PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json',
        'candidate-input.json', 'candidate-sources.json', 'toolchain.json', 'python-environment.json',
        'base-python-environment.json', 'dependency-files.json', 'interpreter-preflight.json',
        'private-python-copy.json', 'frontend-layout.json', 'security-history.json',
        'install-cache-retirement.json', 'fixture-clock-authorization.json', 'fixture-resumption-amendment.json',
        'snapshot-resumption-authorization.json', 'snapshot-equivalence.json', 'snapshot-correction.diff',
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
    eq = read(HERE / 'baseline-equivalence.json')
    corrected = (REPO / TARGET).read_bytes().replace(b'\r\n', b'\n')
    assert sha(corrected) == eq['corrected_sha256']
    row = next(r for r in old_manifest['files'] if r['path'] == TARGET)
    assert row['sha256'] == eq['original_sha256']
    row.update(sha256=sha(corrected), git_blob=eq['corrected_git_blob'], bytes=len(corrected))
    old_manifest.update(candidate_sha=new, source_export_candidate=OLD_TREE,
        export_method='Existing verified Git export plus only the authorized reviewed baseline tuple',
        source_manifest_sha256=sha((PRIOR / 'candidate-sources.json').read_bytes()),
        new_complete_git_archive_claimed=False)
    (HERE / 'candidate-sources.json').write_text(json.dumps(old_manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    private = work / 'src' / TARGET
    assert sha(private.read_bytes()) == eq['original_sha256']
    private.write_bytes(corrected)
    for name in ('full-partition-contract.json', 'full-partition.json'):
        path = HERE / name
        data = read(path)
        assert data['candidate_tree'] == OLD_TREE
        data['candidate_tree'] = new
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    assembly = read(PRIOR / 'assembly.json')
    assembly.update(candidate_sha=new, phase='PREPARING_AUTHORIZED_BASELINE_CONTINUATION',
        source_campaign=PRIOR.name, runtime_reinstalled=False, private_source_patch='baseline-correction.diff')
    save('assembly.json', assembly)
    selection = read(PRIOR / 'code-selection.json')
    selection.update(explicit_paths=candidate['changed_paths'], candidate_tree=new,
        baseline_authorization='baseline-resumption-authorization.json')
    selection['staged_sha256'][TARGET] = sha(corrected)
    save('code-selection.json', selection)
    save('authorization.json', {'user': auth['user_answer'], 'candidate_tree': new,
        'proof': 'baseline-resumption-authorization.json', 'product_runtime_changes': False,
        'maximum_formal_runs_per_new_selection': 1, 'commits_push_deploy_activation_authorized': False})
    save('resumption.json', {'state': 'AUTHORIZED_BASELINE_ONLY_CASE_SUCCESSOR', 'candidate_tree': new,
        'previous_candidate_tree': OLD_TREE, 'source_campaign': PRIOR.name,
        'retained_r6_PASS': 2483, 'retained_r6_SKIP': 2, 'retained_r7_PASS': 405,
        'retained_r8_PASS': 312, 'retained_r8_SKIP': 10,
        'all_historical_FAILED_attempts_preserved': 3, 'new_missing_cases': 0,
        'corrected_failed_cases': 1, 'new_selected_total': 1, 'no_PASS_reruns': True,
        'reused_complete_PASS_blocks': 13, 'runtime_reinstalled': False,
        'candidate_other_3331_blobs_changed': False, 'continuous_campaign_claimed': False,
        'accepted_historical_evidence_limitation': True,
        'new_authorization': 'baseline-resumption-authorization.json', 'helpers': copied})
    amendment = read(PRIOR / 'composite-amendment.json')
    amendment.update(candidate_tree=new, source_candidate_tree=OLD_TREE, user=auth['user_answer'],
        baseline_authorization='baseline-resumption-authorization.json', new_selected_general_cases=1,
        retained_r8_PASS=312, retained_r8_SKIP=10, retained_general_PASS=3200,
        retained_general_SKIP=12, valid_failure_discarded=False, old_failures_preserved=3,
        prior_amendment='../' + PRIOR.name + '/composite-amendment.json')
    save('composite-amendment.json', amendment)
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Reanudación del baseline autorizada\n\n'
            'El usuario aprobó «Sí, corregir ese baseline y continuar sin repetir PASS». '
            'Se añade únicamente la entrada revisada (agent, services.py, TurnWork, filter) '
            'al BASELINE de test_tenant_scoping_audit.py, con comentario que explica sus dos '
            'consultas por Conversation previamente tenant-validada. Scanner, aserción, '
            'exclusiones, IDs y producto permanecen intactos. Se conservan 3200 PASS y '
            '12 skips no críticos; solo el ID fallido se ejecuta con el nuevo árbol. '
            'Los dos FAIL r7, el FAIL r8 y todos sus exits originales permanecen visibles. '
            'Frontend, seguridad y cinco perfiles originales siguen requeridos completos, '
            'con guards y bases nuevas. La limitación histórica r6 aceptada permanece; '
            'no se afirma una campaña continua. Se conserva la instalación privada '
            'verificada y se retira al cierre final. Sin commits, push ni activación.\n')
    policy = read(HERE / 'resource-policy.json')
    policy['baseline_resumption_authorization'] = 'baseline-resumption-authorization.json'
    (HERE / 'resource-policy.json').write_text(json.dumps(policy, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    for name, names in {'run_campaign.py': ('execute', 'check_suite', 'budget', 'gate', 'create_db'),
                        'full_partition.py': ('build_partition', 'projected_groups', 'validate_partition')}.items():
        def methods(p):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
        old, current = methods(PRIOR / name), methods(HERE / name)
        assert all(old[n] == current[n] for n in names), name
    checker = HERE / 'diagnostics/verify_preserved_contract.py'
    text = checker.read_text(encoding='utf-8').replace(OLD_TREE, new)
    checker.write_text(text, encoding='utf-8', newline='\n')
    save('previous-completion-integrity-reference.json', {'source': '../' + PRIOR.name + '/diagnostics/completed-prefix-validation.json',
        'sha256': sha(proof_path.read_bytes()), 'current_integrity_before_private_update': 'pre-patch-current-integrity.json',
        'r8_failure_preserved': True, 'historical_r6_monitor_limitation_unchanged': True})
    print('R9_ASSEMBLED_SINGLE_SELECTED_NO_TESTS', new, flush=True)


if __name__ == '__main__':
    main()
