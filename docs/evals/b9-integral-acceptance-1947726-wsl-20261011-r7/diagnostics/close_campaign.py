"""Classify and conserve r7 after STOP; no evaluator modification or rerun."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
PRIOR = HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r6')
GIB = 1024**3

def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(name, value):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    assert read('STOP.json') == {'state': 'PENDING', 'phase': 'migrate',
        'cause': 'Clock discontinuity', 'no_rerun': True}
    for name in ('cleanup.json', 'clock-restoration.json', 'resource-observer-closure.json'):
        assert read(name)['state'] == 'PASS'
    assert read('resource-observer-closure.json')['explicit_stop_requested']
    assert read('awake-request-probe/closure.json')['state'] == 'PASS_API_REQUEST_AND_RESTORATION'
    suite = read('blocks/directed.results.json')
    assert suite['tests'] == 87 and suite['exit_code'] == 0
    assert not any(suite[key] for key in ('failures', 'errors', 'skips', 'xfail'))
    assert sorted(suite['test_ids']) == read('directed-selected.json')
    labels = ['directed', 'django-check', 'migration-drift', 'migrate']
    commands = {label: read('blocks/' + label + '.command.json') for label in labels}
    assert len(list((HERE / 'blocks').glob('*.command.json'))) == 4
    for label in labels[:3]:
        assert commands[label]['exit_code'] == 0 and commands[label]['invalidating_incident'] is None
        assert read('blocks/' + label + '.gate.json')['state'] == 'PASS'
    assert commands['migrate']['exit_code'] == -15
    assert commands['migrate']['invalidating_incident'] == 'Clock discontinuity'
    for pattern in ('seal-check-*.json', 'dependency-check-*.json', 'integrity-*.json'):
        for file in HERE.glob(pattern):
            assert not json.loads(file.read_text())['mismatches'], file.name
    prior = read('prior-evidence-before.json')
    drift = [name for name, h in prior.items()
        if not (REPO / name).is_file() or digest((REPO / name).read_bytes()) != h]
    original = read('checkout-before.json')['unrelated']
    unrelated = {name: {'exists': (REPO / name).exists(),
        'sha256': digest((REPO / name).read_bytes()) if (REPO / name).exists() else None} for name in original}
    assert not drift and unrelated == original
    save('preservation-of-prior-work.json', {'prior_campaign_files_checked': len(prior),
        'prior_campaign_mismatches': drift, 'unrelated_unchanged': True, 'unrelated': unrelated})
    rows = {label: read('monitor-' + label + '.json') for label in labels}
    stats = {label: {'samples': len(items),
        'minimum_host_available_bytes': min(r['host']['physical_available'] for r in items),
        'minimum_guest_available_bytes': min(r['guest']['physical_available'] for r in items),
        'minimum_backing_disk_available_bytes': min(r['guest']['disk_available'] for r in items),
        'maximum_absolute_clock_skew_seconds': max(abs(r['wall_minus_monotonic_seconds']) for r in items)}
        for label, items in rows.items()}
    assert all(r['minimum_host_available_bytes'] >= 2*GIB and
        r['minimum_guest_available_bytes'] >= 2*GIB and r['minimum_backing_disk_available_bytes'] >= GIB
        for r in stats.values())
    skew = stats['migrate']['maximum_absolute_clock_skew_seconds']
    assert skew > 1 and all(stats[label]['maximum_absolute_clock_skew_seconds'] <= 1 for label in labels[:3])
    save('monitor-summary.json', {'blocks': stats, 'samples': sum(r['samples'] for r in stats.values()),
        'memory_or_disk_reserve_exhausted': False, 'clock_incident_block': 'migrate',
        'observation_limit': 'No host observations during suspension; retained cached sample is not a fresh measurement'})
    observer = [json.loads(s) for s in (HERE / 'resource-observer/samples.jsonl').read_text().splitlines()]
    gaps = [{'before': a['utc'], 'after': b['utc'], 'seconds': b['utc_epoch_seconds'] - a['utc_epoch_seconds']}
        for a, b in zip(observer, observer[1:]) if b['utc_epoch_seconds'] - a['utc_epoch_seconds'] > 5]
    save('resource-observer-summary.json', {'state': 'CLOSED', 'samples': len(observer),
        'sampling_gaps_over_five_seconds': gaps, 'source': 'Same GlobalMemoryStatusEx persistent private process',
        'memory_fluctuation_cause_established': False, 'application_tests_executed_by_observer': False})
    events = read('windows-clock-power-events.json')['events']
    sleep = next(e for e in events if e['provider'] == 'Microsoft-Windows-Kernel-Power' and e['id'] == 42)
    resume = next(e for e in events if e['provider'] == 'Microsoft-Windows-Kernel-General' and
        e['id'] == 1 and e['data'].get('ProcessID') == '4')
    cause = f'Host suspension and resume-clock adjustment coincide with a {skew:.6f}-second civil-minus-monotonic discontinuity during checks migration'
    remedy = {'prepared_after_stop': True, 'used_in_r7_formal_execution': False,
        'helper': 'diagnostics/awake_guard.py', 'API': 'SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)',
        'API_request_and_restoration': 'PASS', 'probe_duration_seconds': read('awake-request-probe/closure.json')['seconds'],
        'full_duration_sleep_prevention_validated': False, 'maximum_lifetime_seconds': 21600,
        'global_power_policy_changed': False, 'W32Time_changed': False,
        'limits': 'Does not guarantee preventing manual sleep, lid/power button actions or policy overrides',
        'future_campaign_decision_required': True,
        'documentation': 'https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate'}
    save('environment-remediation.json', remedy)
    save('incident-classification.json', {'state': 'PENDING_ENVIRONMENT_CLOCK', 'cause': cause,
        'product_failure_attributed': False, 'raw_stop_preserved': True, 'clock_skew_seconds': skew,
        'original_clock_limit_seconds': 1, 'windows_sleep_event_utc': sleep['utc'],
        'windows_resume_clock_event_utc': resume['utc'],
        'windows_resume_clock_adjustment_ms': int(resume['data']['TimeDeltaInMs']),
        'windows_sleep_and_resume_clock_events_confirmed': True,
        'Power_Troubleshooter_sleep_wake_pair_available_in_query': False,
        'memory_or_disk_reserve_exhausted': False, 'partial_migration_is_not_a_pass': True,
        'termination': 'Controller SIGTERM of its owned process group, exit -15', 'formal_reruns': 0,
        'current_power_policy_post_stop': {'AC_idle_sleep_seconds': 900, 'DC_idle_sleep_seconds': 600},
        'automatic_idle_sleep_proven_to_be_the_event_trigger': False,
        'causality_limit': 'Events confirm suspension and a resume-clock adjustment; current idle policy does not identify the exact sleep initiator',
        'evidence': ['STOP.json', 'monitor-migrate.json', 'blocks/migrate.command.json',
            'windows-clock-power-events.json', 'power-policy-after-stop.json', 'resource-observer/samples.jsonl']})
    remaining = ['billing-schema', 'b0', 'b3', 'b4', 'b5', 'full', 'frontend-build', 'frontend-test',
        'frontend-lint', 'frontend-smoke-urls', 'security', 'pip-audit', 'pnpm-audit', 'profile-base',
        'profile-blocked_llm', 'profile-meta_slow', 'profile-duplicate', 'profile-saturation']
    save('block-status.json', {label: {'state': 'PASS' if label in labels[:3] else
        'INTERRUPTED_PENDING_ENVIRONMENT' if label == 'migrate' else 'NOT_EXECUTED',
        'formal_runs': 1 if label in labels else 0, 'test_ids_completed': 87 if label == 'directed' else 0}
        for label in labels + remaining})
    save('execution-summary.json', {'formal_controller_invocations': 1, 'formal_block_runs': 4,
        'formal_reruns': 0, 'backend_test_id_observations': 87, 'unique_test_ids_completed': 87,
        'unique_test_ids_passed': 87, 'failures': 0, 'errors': 0, 'skips': 0, 'xfail': 0, 'profile_runs': 0,
        'discovered_counts_not_execution': read('discovery.json')['counts'],
        'blocking_gates_passed': labels[:3], 'interrupted_block': 'migrate',
        'remaining_blocks': 'NOT_EXECUTED', 'prior_campaign_results_transferred_to_r7': False})
    decision = json.loads((PRIOR / 'candidate-decision.json').read_text(encoding='utf-8'))
    decision.update(schema='b9i-wsl-r7-candidate-decision-v1', date='2026-10-11',
        cause=cause, cause_evidence=['incident-classification.json', 'windows-clock-power-events.json',
            'power-policy-after-stop.json', 'monitor-migrate.json', 'STOP.json'],
        evaluation_seal=f"{len(read('evaluation-seal.json')['files'])} files plus source/dependency manifests; all completed post-block checks intact",
        clock_incident=f'{skew:.6f}-second discontinuity during migrate; host suspension and resume-clock adjustment confirmed',
        new_campaign='No automatic retry after durable STOP; future campaign must acquire and monitor a bounded owned awake request, revalidate clock/resources, and keep manual sleep/lid actions out of the run',
        environment_remediation=remedy)
    save('candidate-decision.json', decision)
    acta = REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before = acta.read_bytes()
    assert b'WSL2 r7' not in before
    addition = '''

## 2026-10-11 — B9E 1947726: campaña WSL2 r7, continuación

Decisión integral **PENDING por entorno/reloj**. Autorización «continua, estara despierto», conservando la admisión modificada y reserva de 2 GiB. Mismo candidato y contratos. Ambos intérpretes privados validados con el mismo lock; 101 archivos de evaluador/herramientas sellados y 13.508 archivos de dependencias comprobados.

Corpus dirigido **87/87 PASS**, cero fallos/errores/skips/xfail; Django check y drift PASS. Durante la migración de checks, nueva discontinuidad civil−monotónica de **391,458861 s**, con parada del grupo propio y exit -15. Windows registra suspensión a las 04:51:58 UTC y un ajuste civil al reactivarse a las 04:58:29 UTC del 12-10, todavía 11-10 en México. No se registró agotamiento de las reservas de memoria/disco. Migración parcial PENDING; schema Billing, B0/B3/B4/B5/full, frontend, seguridad y cinco PROFILE NOT_EXECUTED. Sin reintentos.

La inspección posterior muestra suspensión automática configurada tras 15 minutos con corriente y 10 con batería; no demuestra por sí sola el iniciador exacto del evento. Se preparó después del STOP una solicitud temporal propia de actividad mediante SetThreadExecutionState, comprobando adquisición y restauración durante 2 s, sin cambios de política global. No se usó en las pruebas r7 ni acredita prevención de suspensión durante una campaña completa.

Cleanup PASS: tres bases propias, PostgreSQL, workspace y sonda Windows retirados. Sincronización WSL restaurada active/running/enabled; W32Time intacto. Conservados 1.163 archivos de las siete campañas anteriores y cambios ajenos. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r7](../b9-integral-acceptance-1947726-wsl-20261011-r7/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r7/candidate-decision.json), [diagnóstico](../b9-integral-acceptance-1947726-wsl-20261011-r7/incident-classification.json) y [preparación de remediación](../b9-integral-acceptance-1947726-wsl-20261011-r7/environment-remediation.json). Sin commits, push, despliegue ni activación.
'''.encode('utf-8')
    acta.write_bytes(before + addition)
    after = acta.read_bytes()
    assert after[:len(before)] == before
    save('acta-update.json', {'state': 'PASS', 'append_only': True,
        'prior_prefix_bytes': len(before), 'prior_prefix_sha256': digest(before),
        'appended_bytes': len(addition), 'appended_sha256': digest(addition), 'final_sha256': digest(after)})
    save('closure-reporting.json', {'state': 'PASS', 'created_after_stop': True,
        'reporting_script_sha256': digest(Path(__file__).read_bytes()), 'sealed_evaluator_changed': False,
        'cleanup': 'PASS', 'clock_restoration': 'PASS', 'resource_observer_cleanup': 'PASS',
        'test_ids_passed': 87, 'awake_probe_after_stop': 'API_REQUEST_AND_RESTORATION_ONLY'})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS', len(prior))

if __name__ == '__main__':
    main()
