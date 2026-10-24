"""Reuse the unchanged candidate and installation after a zero-case selector stop."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parents[1]
PRIOR = HERE.with_name('b9-correction-20261020-native-r10')
REPO = HERE.parents[2]
CANDIDATE = 'f5f18d71847a46d66644775cd90d30268f072e3b'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert read(PRIOR / 'invocation-formal.json')['exit_code'] == 2
    assert read(PRIOR / 'STOP.json')['phase'] == 'frontend-test-assemble'
    raw = read(PRIOR / 'blocks/frontend-test-remainder.json')
    assert raw['numPassedTests'] == raw['numFailedTests'] == 0 and raw['numPendingTests'] == 26
    assert read(PRIOR / 'blocks/frontend-test-remainder.command.json')['exit_code'] == 0
    assert read(PRIOR / 'blocks/frontend-test-assemble.command.json')['exit_code'] == 1
    assert read(PRIOR / 'awake-request/closure.json')['matches_original_thread_state'] is True
    assert read(PRIOR / 'resource-observer-closure.json')['state'] == 'PASS'
    assert read(PRIOR / 'candidate.json')['candidate_tree'] == CANDIDATE
    work = Path(read(PRIOR / 'assembly.json')['workspace'])
    manifest = read(PRIOR / 'candidate-sources.json')
    deps = read(PRIOR / 'dependency-files.json')
    seal = read(PRIOR / 'evaluation-seal.json')
    source_bad = [r['path'] for r in manifest['files'] if sha(work / 'src' / r['path']) != r['sha256']]
    dep_bad = [p for p, h in deps['files'].items() if not Path(p).is_file() or sha(Path(p)) != h]
    seal_bad = [p for p, h in seal['files'].items() if not Path(p).is_file() or sha(Path(p)) != h]
    save(HERE / 'selector-runtime-integrity.json', {'state': 'PASS' if not source_bad + dep_bad + seal_bad else 'FAIL',
        'candidate_tree': CANDIDATE, 'sources_checked': len(manifest['files']),
        'dependencies_checked': len(deps['files']), 'sealed_inputs_checked': len(seal['files']),
        'source_mismatches': source_bad, 'dependency_mismatches': dep_bad, 'seal_mismatches': seal_bad,
        'source_or_fixture_changed': False, 'dependencies_reinstalled': False})
    assert not source_bad + dep_bad + seal_bad
    excluded = {'frontend_resumption.py', 'retire_previous_cluster.py', 'handoff_runtime.py',
        'apply_frontend_correction.py', 'bootstrap_resumption.py', 'prepare_references.py', 'prepare_scheduler.py'}
    for source in PRIOR.glob('*.py'):
        if source.name in excluded:
            continue
        target = HERE / source.name
        assert not target.exists(), target
        text = source.read_text(encoding='utf-8')
        if source.name in ('deliver_native.py', 'run_campaign.py'):
            text = text.replace('native-r10', 'native-r11').replace('native-20261020-r10', 'native-20261020-r11')
        if source.name == 'finalize_preflight.py':
            text = text.replace('b9-correction-20261020-native-r9', PRIOR.name).replace('native-r9/', 'native-r10/')
        target.write_text(text, encoding='utf-8', newline='\n')
    derived = {'backend-reference-validation.json', 'frontend-resumption-manifest.json',
        'frontend-resumption-validation.json', 'frontend-retained-pass-selected.json',
        'frontend-remainder-selected.json', 'frontend-full-selected.json', 'launcher-validation.json',
        'postgresql-preflight.json', 'campaign-adaptation.json', 'clock-preflight.json',
        'native-preflight.json', 'environment-ready.json', 'receipt-adapter.diff', 'adapter-validation.json'}
    for name in seal['files']:
        source = Path(name)
        if not source.is_relative_to(PRIOR) or source.suffix == '.py':
            continue
        relative = source.relative_to(PRIOR)
        if len(relative.parts) > 1 or relative.name in derived:
            continue
        target = HERE / relative
        assert not target.exists(), target
        shutil.copy2(source, target)
    additional = ['checkout-before.json', 'discovery-skip-annotations.json',
        'private-postgresql/postgresql.conf', 'private-postgresql/pg_hba.conf',
        'diagnostics/fixture-clock-focused-check.json', 'diagnostics/verify_preserved_contract.py',
        'diagnostics/verify_evidence_contract.py', 'diagnostics/verify_frontend_equivalence.py',
        'diagnostics/verify_frontend_equivalence.cjs']
    for relative in additional:
        target = HERE / relative
        assert not target.exists(), target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PRIOR / relative, target)
    save(PRIOR / 'final-classification.json', {'decision': 'PENDING', 'cause': 'HARNESS_SELECTOR_EXECUTED_ZERO_CASES',
        'candidate_tree': CANDIDATE, 'application_test_cases_executed': 0, 'filtered_case_metadata': 26,
        'frontend_command_actual_exit_code': 0, 'assembler_actual_exit_code': 1,
        'formal_controller_actual_exit_code': 2, 'source_change': False,
        'original_STOP_preserved': True, 'historical_limit_accepted': True,
        'awake_actual_exit_code': 0, 'observer_actual_exit_code': 0,
        'runtime_retained_for_owned_handoff': True, 'technical_acceptance_claimed': False})
    save(HERE / 'selector-repair-decision.json', {'state': 'HARNESS_ONLY_REPAIR_APPROVED',
        'candidate_tree': CANDIDATE, 'source_candidate_tree': CANDIDATE, 'source_campaign': PRIOR.name,
        'no_application_source_or_fixture_change': True,
        'original_case_authorization': 'frontend-resumption-authorization.json',
        'user_answer': 'Sí, ajustar ese armado y continuar sin repetir PASS',
        'application_test_cases_executed_in_r10': 0, 'previous_PASS_cases_rerun': False,
        'exact_one_case_discovery_required': True,
        'reason': 'Windows pnpm lifecycle serialization doubled backslashes introduced before spaces by re.escape; anchored literal has no JS regular-expression metacharacters.',
        'selector_only_delta': 'Replace re.escape(TARGET_NAME) with TARGET_NAME after rejecting regexp metacharacters.',
        'formal_execution_limit': 'One first actual execution of the authorized corrected case, followed by original remaining stages.',
        'eight_assertions_5000ms_timeout_guards_workloads_unchanged': True,
        'original_stop_and_zero_case_receipts_preserved': True,
        'continuous_campaign_claimed': False, 'historical_evidence_limitation_accepted': True})
    with (HERE / 'PLAN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n## Reparación del selector sin cambio del candidato\n\n'
            'r10 terminó PENDING porque el selector de pnpm/Windows no seleccionó ningún caso '
            '(0 ejecutados; 26 metadatos filtrados). Se conserva STOP y todos los recibos. '
            'La reparación afecta únicamente el selector del evaluador; se mantiene el árbol '
            'f5f18d71847a46d66644775cd90d30268f072e3b y la autorización del caso aún no ejecutado. '
            'Antes del nuevo sello se exige descubrimiento estático con exactamente una identidad '
            'coincidente y prueba del transporte real del argumento. No se repite ningún PASS; '
            'ocho aserciones, timeout de 5000 ms, guards y etapas restantes siguen intactos.\n')
    for name in ('resumption.json', 'composite-amendment.json'):
        path = HERE / name
        data = read(path)
        data['selector_repair_decision'] = 'selector-repair-decision.json'
        data['zero_case_previous_fragment'] = PRIOR.name
        data['same_candidate_as_zero_case_fragment'] = True
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    print('R11_SAME_CANDIDATE_RUNTIME_VERIFIED_NO_TESTS', flush=True)


if __name__ == '__main__':
    main()
