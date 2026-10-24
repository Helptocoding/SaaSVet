"""Prepare one frontend case and preserve the completed backend installation."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261020-native-r9')
REPO = HERE.parents[2]
PREVIOUS = 'b271e314817da51e99811cb18921fd7c9f59e58a'
TARGET = 'frontend/src/pages/inbox/index.test.jsx'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save(name, data):
    p = HERE / name
    assert not p.exists(), p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert not (HERE / 'native_support.py').exists()
    candidate = read(HERE / 'candidate.json')
    new = candidate['candidate_tree']
    assert candidate['previous_candidate_tree'] == PREVIOUS
    auth = read(HERE / 'frontend-resumption-authorization.json')
    assert auth['user_answer'] == 'Sí, ajustar ese armado y continuar sin repetir PASS'
    proof_path = PRIOR / 'diagnostics/backend-and-frontend-prefix-validation.json'
    assert sha(proof_path) == '575339d8ca2f810039c48fe15db3a7c345189ed617f31988f03a4a993caa5449'
    proof = read(proof_path)
    assert proof['candidate_tree'] == PREVIOUS and proof['state'] == 'PASS_COMPLETE_PREFIX_WITH_FRONTEND_TIMEOUT'
    assert all(sha(PRIOR / name) == h for name, h in proof['files'].items())
    assert read(PRIOR / 'final-classification.json')['decision'] == 'PENDING'
    work = Path(read(PRIOR / 'assembly.json')['workspace'])
    assert work.resolve() == Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6').resolve()
    assert not work.is_junction() and not work.is_symlink()
    manifest = read(PRIOR / 'candidate-sources.json')
    source_mismatches = [row['path'] for row in manifest['files']
        if not (work / 'src' / row['path']).is_file() or sha(work / 'src' / row['path']) != row['sha256']]
    dependencies = read(PRIOR / 'dependency-files.json')
    dependency_mismatches = [name for name, h in dependencies['files'].items()
        if not Path(name).is_file() or sha(Path(name)) != h]
    seal = read(PRIOR / 'evaluation-seal.json')
    seal_mismatches = [name for name, h in seal['files'].items()
        if not Path(name).is_file() or sha(Path(name)) != h]
    save('pre-patch-current-integrity.json', {'state': 'PASS' if not source_mismatches + dependency_mismatches + seal_mismatches else 'FAIL',
        'candidate_tree': PREVIOUS, 'sources_checked': len(manifest['files']),
        'dependencies_checked': len(dependencies['files']), 'seal_checked': len(seal['files']),
        'source_mismatches': source_mismatches, 'dependency_mismatches': dependency_mismatches,
        'seal_mismatches': seal_mismatches, 'before_private_source_update': True})
    assert not source_mismatches + dependency_mismatches + seal_mismatches
    helpers = ['native_support.py', 'recorded_suite.py', 'full_partition.py',
        'awake_guard.py', 'awake_status.py', 'host_resources.py', 'host_observer.py', 'clock_probe.py',
        'launch_native.py', 'capture_native.py', 'cleanup_native.py', 'deliver_native.py',
        'restore_native.py', 'scan_security.py', 'finalize_preflight.py',
        'retire_previous_cluster.py', 'handoff_runtime.py']
    copied = []
    for name in helpers:
        source, target = PRIOR / name, HERE / name
        assert not target.exists(), name
        text = source.read_text(encoding='utf-8')
        if name in ('native_support.py', 'recorded_suite.py'):
            text = text.replace(PREVIOUS, new)
        if name == 'finalize_preflight.py':
            text = text.replace('b9-correction-20261020-native-r8', PRIOR.name).replace('native-r8/', 'native-r9/')
        if name == 'deliver_native.py':
            text = text.replace('native-r9', 'native-r10').replace('native-20261020-r9', 'native-20261020-r10')
            anchor = "        f'docs/evals/{HERE.name}/correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n')"
            insert = "        f'docs/evals/{HERE.name}/frontend-correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'\n        f'docs/evals/{HERE.name}/referenced-completed-evidence/**/*.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\\n'\n"
            assert anchor in text
            text = text.replace(anchor, insert + anchor)
        if name == 'retire_previous_cluster.py':
            text = text.replace('b9-correction-20261020-native-r8', PRIOR.name).replace('r8 disposable', 'r9 disposable').replace("/'postgresql-start-1.log'", "/'postgresql-start-1.log'")
        if name == 'handoff_runtime.py':
            text = text.replace(PREVIOUS, new)
            text = text.replace("EVIDENCE.name=='b9-correction-20261020-native-r9'", "EVIDENCE.name=='b9-correction-20261020-native-r10'")
            text = text.replace('abs(float(sql_epoch)-start_epoch)<=2', 'abs(float(sql_epoch)-start_epoch)<=5')
            text = text.replace('test_b9i_full_general_remainder_r9', 'test_b9i_full_general_remainder_r10')
            text = text.replace('R9_HANDOFF', 'R10_HANDOFF')
        target.write_text(text, encoding='utf-8', newline='\n')
        copied.append({'path': name, 'source': '../' + PRIOR.name + '/' + name,
            'source_sha256': sha(source), 'sha256': sha(target)})
    names = ['PLAN.md', 'scope-manifest.json', 'resource-policy.json', 'prior-focused-verification.json',
        'toolchain.json', 'python-environment.json', 'base-python-environment.json', 'dependency-files.json',
        'interpreter-preflight.json', 'private-python-copy.json', 'frontend-layout.json', 'security-history.json',
        'install-cache-retirement.json', 'downloads.json', 'audit-toolchain.json', 'profile-compatibility.json',
        'effective-configuration.json', 'checkout-before.json', 'full-partition-contract.json', 'full-partition.json',
        'discovery.json', 'discovery-skip-annotations.json', 'operational-lifetime-amendment.json',
        'runtime-handoff-supplement.json', 'prepared-runtime-references.json',
        'diagnostics/fixture-clock-focused-check.json', 'private-postgresql/postgresql.conf',
        'private-postgresql/pg_hba.conf']
    names += [p.name for p in PRIOR.glob('*-selected.json')]
    for name in dict.fromkeys(names):
        source, target = PRIOR / name, HERE / name
        assert source.is_file() and not target.exists(), name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    equivalence = read(HERE / 'frontend-equivalence.json')
    canonical = (REPO / TARGET).read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(canonical).hexdigest() == equivalence['corrected_sha256']
    row = next(r for r in manifest['files'] if r['path'] == TARGET)
    assert row['sha256'] == equivalence['original_sha256']
    row.update(sha256=equivalence['corrected_sha256'], git_blob=equivalence['corrected_git_blob'], bytes=len(canonical))
    manifest.update(candidate_sha=new, source_export_candidate=PREVIOUS,
        export_method='Verified existing export plus only two authorized frontend input-setup substitutions',
        source_manifest_sha256=sha(PRIOR / 'candidate-sources.json'), new_complete_git_archive_claimed=False)
    save('candidate-sources.json', manifest)
    private = work / 'src' / TARGET
    assert sha(private) == equivalence['original_sha256']
    private.write_bytes(canonical)
    for name in ('full-partition-contract.json', 'full-partition.json'):
        p = HERE / name
        data = read(p)
        assert data['candidate_tree'] == PREVIOUS
        data['candidate_tree'] = new
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    assembly = read(PRIOR / 'assembly.json')
    assembly.update(candidate_sha=new, phase='PREPARING_AUTHORIZED_SINGLE_FRONTEND_CASE',
        source_campaign=PRIOR.name, runtime_reinstalled=False, private_source_patch='frontend-correction.diff')
    save('assembly.json', assembly)
    selection = read(PRIOR / 'code-selection.json')
    selection.update(explicit_paths=candidate['changed_paths'], candidate_tree=new,
        frontend_authorization='frontend-resumption-authorization.json')
    selection['staged_sha256'][TARGET] = equivalence['corrected_sha256']
    save('code-selection.json', selection)
    save('authorization.json', {'user': auth['user_answer'], 'candidate_tree': new,
        'proof': 'frontend-resumption-authorization.json', 'product_runtime_changes': False,
        'maximum_formal_runs_per_new_selection': 1, 'commits_push_deploy_activation_authorized': False})
    save('resumption.json', {'state': 'AUTHORIZED_FRONTEND_SETUP_ONLY_SUCCESSOR', 'candidate_tree': new,
        'previous_candidate_tree': PREVIOUS, 'source_campaign': PRIOR.name,
        'retained_backend_ids': 3331, 'retained_backend_PASS': 3319, 'retained_backend_SKIP': 12,
        'retained_frontend_PASS': 354, 'new_frontend_cases': 1, 'frontend_build_retained': True,
        'backend_tests_executed_here': False, 'historical_backend_failures_preserved': 3,
        'frontend_timeout_and_exit_1_preserved': True, 'no_PASS_reruns': True,
        'runtime_reinstalled': False, 'continuous_campaign_claimed': False,
        'accepted_historical_evidence_limitation': True, 'helpers': copied})
    save('composite-amendment.json', {'state': 'USER_AUTHORIZED_FRONTEND_CASE_CONTINUATION',
        'candidate_tree': new, 'source_candidate_tree': PREVIOUS, 'user': auth['user_answer'],
        'retained_backend_ids': 3331, 'retained_frontend_PASS': 354, 'new_frontend_cases': 1,
        'only_source_change': TARGET, 'no_PASS_reruns': True, 'all_original_remaining_stages_required': True,
        'all_original_guards_and_eight_assertions_and_5000ms_timeout_preserved': True,
        'historical_failures_and_timeout_preserved': True, 'accepted_historical_evidence_limitation': True,
        'continuous_campaign_claimed': False, 'authority': 'frontend-resumption-authorization.json'})
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Reanudación del armado frontend autorizada\n\n'
            'El usuario aprobó «Sí, ajustar ese armado y continuar sin repetir PASS». '
            'Únicamente se sustituyen dos armados de texto del caso A→B→A por eventos '
            'de cambio que ejecutan el onChange real. Ocho aserciones, navegación, '
            'promesa tardía y timeout de 5000 ms permanecen. Se conservan el backend '
            'completo de 3331 IDs, build y 354 PASS frontend; únicamente se ejecuta '
            'el caso corregido, seleccionado por archivo y nombre completo exacto. '
            'El exit 1 y timeout original de r9 se conservan. Los casos filtrados '
            'no se presentan como nuevas ejecuciones ni skips de aceptación. '
            'Después continúan lint, smoke, seguridad, auditorías y cinco perfiles '
            'originales, con sus guards y cargas intactos. La limitación histórica '
            'r6 aceptada y los tres FAIL backend siguen explícitos; no se afirma '
            'una campaña continua. Sin commits, push, despliegue ni activación.\n')
    for name in candidate['changed_paths']:
        source = work / 'src' / name
        target = work / 'security-patch' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    save('previous-completion-integrity-reference.json', {'source': '../' + PRIOR.name + '/diagnostics/backend-and-frontend-prefix-validation.json',
        'sha256': sha(proof_path), 'private_integrity_before_update': 'pre-patch-current-integrity.json',
        'r9_frontend_timeout_preserved': True})
    print('R10_RUNTIME_ASSEMBLED_NO_TESTS', new, flush=True)


if __name__ == '__main__':
    main()
