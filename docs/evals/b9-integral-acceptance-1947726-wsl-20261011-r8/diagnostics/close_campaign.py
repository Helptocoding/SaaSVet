"""Conserve r8 after its durable disk STOP, without evaluating application code."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
GIB = 1024**3


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    path = HERE / name
    assert not path.exists(), name
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def gaps(rows):
    return [{'before': a['utc'], 'after': b['utc'],
             'seconds': b['utc_epoch_seconds'] - a['utc_epoch_seconds']}
            for a, b in zip(rows, rows[1:])
            if b['utc_epoch_seconds'] - a['utc_epoch_seconds'] > 5]


def main():
    assert read('STOP.json') == {'state': 'PENDING', 'phase': 'directed',
                                'cause': 'Backing disk reserve exhausted', 'no_rerun': True}
    for name in ('cleanup.json', 'clock-restoration.json', 'resource-observer-closure.json'):
        assert read(name)['state'] == 'PASS', name
    closure = read('awake-request/closure.json')
    assert closure['state'] == 'PASS_API_REQUEST_AND_RESTORATION'
    assert closure['explicit_stop_requested'] and closure['matches_original_thread_state']
    assert read('resource-observer-closure.json')['explicit_stop_requested']
    command = read('blocks/directed.command.json')
    assert command['exit_code'] == -9 and command['invalidating_incident'] == 'Backing disk reserve exhausted'
    assert len(list((HERE / 'blocks').glob('*.command.json'))) == 1
    assert not (HERE / 'blocks/directed.results.json').exists()
    selected = read('directed-selected.json')
    journal = [json.loads(line) for line in
               (HERE / 'blocks/directed.results.passed.jsonl').read_text().splitlines()]
    ids = [row['test_id'] for row in journal]
    assert len(ids) == len(set(ids)) == 53 and len(selected) == 87
    assert all(row['status'] == 'ok' for row in journal) and set(ids) <= set(selected)
    b2_ids = [name for name in ids if '.test_b2_results.' in name]
    assert len(b2_ids) == 39
    attendance = [name for name in ids if '.test_b8d_attendance.' in name]
    assert len(attendance) == 2
    save('directed-partial-receipt.json', {
        'state': 'INCOMPLETE_INVALID_ENVIRONMENT', 'required_ids': 87,
        'journal_completed_ids': 53, 'journal_status': 'ok', 'test_ids': ids,
        'remaining_ids': sorted(set(selected) - set(ids)), 'remaining_count': 34,
        'b2_journal_ids': b2_ids, 'attendance_negative_journal_ids': attendance,
        'final_runner_receipt_available': False, 'directed_gate_passed': False,
        'final_failure_error_skip_xfail_totals': None,
        'interpretation': 'Partial raw observations only; no complete gate or integral acceptance. '
                          'Journal has no per-ID timestamps; it is not used to prove that every '
                          'recorded completion preceded the invalidating resource sample.'})
    for pattern in ('seal-check-*.json', 'dependency-check-*.json', 'integrity-*.json'):
        for path in HERE.glob(pattern):
            assert not json.loads(path.read_text())['mismatches'], path.name
    assert read('integrity-final-before-cleanup.json')['checked_files'] == 3332
    assert read('dependency-check-after-directed.json')['checked'] == 13508
    assert read('seal-check-after-directed.json')['checked'] == 106
    prior = read('prior-evidence-before.json')
    drift = [name for name, expected in prior.items()
             if not (REPO / name).is_file() or digest((REPO / name).read_bytes()) != expected]
    original = read('checkout-before.json')['unrelated']
    unrelated = {name: {'exists': (REPO / name).exists(),
                       'sha256': digest((REPO / name).read_bytes()) if (REPO / name).exists() else None}
                 for name in original}
    assert not drift and unrelated == original
    save('preservation-of-prior-work.json', {
        'prior_campaign_files_checked': len(prior), 'prior_campaign_count': 8,
        'prior_campaign_mismatches': drift, 'unrelated_unchanged': True, 'unrelated': unrelated})
    rows = read('monitor-directed.json')
    stats = {'samples': len(rows),
             'minimum_host_available_bytes': min(r['host']['physical_available'] for r in rows),
             'minimum_guest_available_bytes': min(r['guest']['physical_available'] for r in rows),
             'minimum_backing_disk_available_bytes': min(r['guest']['disk_available'] for r in rows),
             'maximum_absolute_clock_skew_seconds': max(abs(r['wall_minus_monotonic_seconds']) for r in rows),
             'awake_states': sorted(set(r['awake']['state'] for r in rows)),
             'maximum_checked_awake_heartbeat_age_seconds': max(r['awake']['sample_age_seconds'] for r in rows)}
    assert stats['minimum_host_available_bytes'] >= 2*GIB
    assert stats['minimum_guest_available_bytes'] >= 2*GIB
    assert stats['minimum_backing_disk_available_bytes'] < GIB
    assert stats['maximum_absolute_clock_skew_seconds'] <= 1
    assert stats['awake_states'] == ['ACTIVE_CONFIRMED']
    bad = [row for row in rows if row['guest']['disk_available'] < GIB]
    save('monitor-summary.json', {'blocks': {'directed': stats}, 'samples': len(rows),
        'memory_reserve_exhausted': False, 'disk_reserve_exhausted': True,
        'clock_incident': False, 'awake_request_unavailable': False,
        'first_disk_breach': bad[0], 'disk_breach_samples': len(bad)})
    for folder, target in [('resource-observer', 'resource-observer-summary.json'),
                           ('awake-request', 'awake-request-summary.json')]:
        file = 'samples.jsonl' if folder == 'resource-observer' else 'heartbeat.jsonl'
        samples = [json.loads(line) for line in (HERE / folder / file).read_text().splitlines()]
        result = {'state': 'CLOSED', 'samples': len(samples),
                  'first_utc': samples[0]['utc'], 'last_utc': samples[-1]['utc'],
                  'sampling_gaps_over_five_seconds': gaps(samples),
                  'application_tests_executed_by_monitor': False}
        if folder == 'awake-request':
            result.update(API_request_and_restoration='PASS',
                formal_monitor_checks_all_confirmed=True,
                heartbeat_span_seconds=samples[-1]['utc_epoch_seconds'] - samples[0]['utc_epoch_seconds'],
                API_only_closure_does_not_claim_universal_sleep_prevention=True,
                limits='Does not guarantee preventing manual sleep, lid/button actions or policy overrides',
                global_power_policy_changed=False, W32Time_changed=False)
        save(target, result)
    save('incident-classification.json', {
        'state': 'PENDING_ENVIRONMENT_DISK', 'raw_stop_preserved': True,
        'cause': 'Frozen monitor observed /mnt/c free space below the original 1 GiB reserve',
        'product_failure_attributed': False, 'space_drop_cause_established': False,
        'reserve_bytes': GIB, 'first_breach_utc': bad[0]['guest']['utc'],
        'minimum_backing_disk_available_bytes': stats['minimum_backing_disk_available_bytes'],
        'disk_after_block_bytes': command['resources_after']['guest']['disk_available'],
        'later_recovery_does_not_revalidate_block': True,
        'memory_reserve_exhausted': False, 'clock_incident': False,
        'awake_request_active_through_block': True,
        'termination': 'SIGTERM of owned process group followed by SIGKILL after the original 10-second grace; exit -9',
        'formal_reruns': 0, 'final_runner_receipt_available': False,
        'partial_journal_records_ok': 53, 'partial_records_are_not_a_directed_gate_pass': True,
        'evidence': ['STOP.json', 'monitor-directed.json', 'blocks/directed.command.json',
                     'blocks/directed.results.passed.jsonl', 'disk-after-stop.json']})
    remaining = ['django-check', 'migration-drift', 'migrate', 'billing-schema', 'b0', 'b3', 'b4',
        'b5', 'full', 'frontend-build', 'frontend-test', 'frontend-lint', 'frontend-smoke-urls',
        'security', 'pip-audit', 'pnpm-audit', 'profile-base', 'profile-blocked_llm',
        'profile-meta_slow', 'profile-duplicate', 'profile-saturation']
    save('block-status.json', {'directed': {'state': 'INTERRUPTED_PENDING_ENVIRONMENT',
        'formal_runs': 1, 'journal_completed_ids_ok': 53, 'required_ids': 87, 'gate_passed': False},
        **{label: {'state': 'NOT_EXECUTED', 'formal_runs': 0} for label in remaining}})
    save('execution-summary.json', {'formal_controller_invocations': 1, 'formal_block_runs': 1,
        'formal_reruns': 0, 'backend_test_id_observations': 53, 'unique_journal_ids_ok': 53,
        'complete_backend_block_receipts': 0, 'final_failure_error_skip_xfail_totals': None,
        'profile_runs': 0, 'blocking_gates_passed': [], 'interrupted_block': 'directed',
        'remaining_blocks': 'NOT_EXECUTED', 'discovered_counts_not_execution': read('discovery.json')['counts'],
        'prior_campaign_results_transferred_to_r8': False})
    remedy = {'used_in_r8_formal_execution': True,
        'API': 'SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)',
        'API_request_and_restoration': 'PASS', 'all_formal_samples_active_confirmed': True,
        'clock_discontinuity_observed_in_r8': False, 'maximum_lifetime_seconds': 21600,
        'global_power_policy_changed': False, 'W32Time_changed': False,
        'prior_suspension_reason_now_confirmed': 'System Idle in rendered Kernel-Power 42 messages for r6 and r7',
        'new_diagnostic_source': 'preseal-sleep-event-messages.json',
        'prior_reports_rewritten': False,
        'new_blocker': 'Backing disk reserve exhausted; source of transient free-space drop not established',
        'next_campaign_requirement': 'A new explicit decision and backing volume that maintains at least 1 GiB free throughout execution; keep existing awake, clock and memory guards',
        'automatic_retry_permitted': False,
        'documentation': 'https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate'}
    save('environment-remediation.json', remedy)
    R = {
        'R01': 'PENDING_INTEGRAL; directed block invalidated by backing disk reserve breach',
        'R02': 'PARTIAL_JOURNAL_ONLY; 53 ok records; five WRITE E2E and remaining corpus incomplete',
        'R03': 'PENDING_NOT_EXECUTED; complete cost and operational budget selection',
        'R04': 'PENDING_NOT_EXECUTED; concurrency/process regressions and temporal PROFILE',
        'R05': 'PENDING_NOT_EXECUTED; shared budget and retry without refund selection',
        'R06': 'PENDING_INTEGRAL_CHECKS; no complete directed gate; backend/frontend/security checks NOT_EXECUTED',
        'R07': 'PENDING_NOT_EXECUTED; all five PROFILE variants',
        'R08': 'DECISION_AND_LIMITS_DOCUMENTED; technical PENDING separate from activation',
        'R09': 'PENDING_NOT_EXECUTED; resource monitor is not an application performance result',
        'R10': 'PARTIAL_JOURNAL_ONLY; 53 of 87 exact IDs recorded ok; no complete corpus gate',
        'R11': 'PENDING_NOT_EXECUTED; budget checks and Billing schema',
        'R12': 'PENDING_NOT_EXECUTED; N-minus-one/N/N-plus-one selection',
        'R13': 'PARTIAL_JOURNAL_ONLY; six release authorization negatives recorded ok; operational readiness separate',
        'R14': 'PREPARATION_AND_DOCUMENTATION_RECORDED; exact sources and both locked interpreters validated',
        'R15': 'DECISION_AND_EVIDENCE_CONSERVED; technical PENDING; privacy and operational requirements separate'}
    I = {
        'I01': 'PARTIAL_JOURNAL_ONLY; B2 effect contracts recorded ok; five WRITE E2E incomplete',
        'I02': 'PARTIAL_JOURNAL_ONLY; withdrawal guard recorded ok; correction and stale causal scope incomplete',
        'I03': 'PENDING_NOT_EXECUTED; complete issued proposal and causal reply selection',
        'I04': 'NEGATIVE_JOURNAL_OK; two attendance questions and forced wrong tool recorded ok; no complete corpus gate',
        'I05': 'PARTIAL_JOURNAL_ONLY; unapproved organization negatives recorded ok; remaining integral gates incomplete',
        'I06': 'PARTIAL_JOURNAL_ONLY; B2 typed outcomes and effect distinctions recorded ok; full pipeline incomplete',
        'I07': 'B2_39_JOURNAL_OK; transport, JSON, empty, partial and success cases recorded ok; no complete corpus gate',
        'I08': 'PENDING_NOT_EXECUTED; directed safety and temporal PROFILE',
        'I09': 'PARTIAL_JOURNAL_ONLY; human_active is silent recorded ok; takeover during LLM and B3 incomplete',
        'I10': 'PENDING_NOT_EXECUTED; FI and crash/restart regression',
        'I11': 'PARTIAL_JOURNAL_ONLY; B2 network/write uncertainty recorded ok; full reconciliation and META_SLOW incomplete',
        'I12': 'PARTIAL_JOURNAL_ONLY; identity expiry and personal tool floors recorded ok; personal READ E2E incomplete',
        'I13': 'PARTIAL_JOURNAL_ONLY; tenant negatives recorded ok; independent planner process selection incomplete',
        'I14': 'PENDING_NOT_EXECUTED; correction retires old proposal before effect'}
    save('candidate-decision.json', {'schema': 'b9i-wsl-r8-candidate-decision-v1',
        'date': '2026-10-11', 'candidate_sha': read('checkout-before.json')['head'],
        'decision': 'PENDING', 'campaign_state': 'STOPPED_DURING_DIRECTED_BACKING_DISK_RESERVE',
        'cause': 'Backing disk reserve exhausted', 'product_failure_attributed': False,
        'raw_stop_state_preserved': 'PENDING', 'formal_block_runs': 1, 'formal_reruns': 0,
        'backend_unique_journal_ids_ok': 53, 'directed_required_ids': 87,
        'directed_complete_gate': False, 'final_runner_totals': None, 'profile_variants_executed': 0,
        'R01_R15': R, 'I01_I14': I,
        'coverage_definition': 'JOURNAL_OK records are partial observations of this campaign only. '
                               'They do not prove a complete gate or that every completion preceded the incident.',
        'operational_requirements': {'R06_real_promotion_eval': 'PENDING_SEPARATE',
            'R13_real_release_readiness': 'PENDING_SEPARATE', 'R15_P_A_P_B_privacy': 'PENDING_SEPARATE'},
        'activation': 'PENDING_ACTIVATION_REQUIREMENTS',
        'R1-04': 'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX': 'SEPARATE_UNCHANGED_SCOPES',
        'historical_profile_metrics_transferred_to_current_candidate': False,
        'prior_campaign_results_transferred_to_r8': False,
        'resource_policy': 'User-amended 2 GiB admission/execution reserve; 1 GiB disk and 1-second clock guards unchanged',
        'memory_reserve_exhausted': False, 'disk_reserve_exhausted': True, 'clock_incident': False,
        'candidate_sources': '3332 exact Git blobs; final integrity PASS',
        'dependency_files_checked': 13508, 'evaluation_seal_files_checked': 106,
        'dual_interpreter_preflight': 'PASS; same locked dependencies in venv and private base Python',
        'frontend_dependency_install': 'PASS_FROZEN_LOCKFILE; frontend CI checks NOT_EXECUTED',
        'cleanup': 'PASS', 'clock_restoration': 'PASS', 'resource_observer_cleanup': 'PASS',
        'awake_request_and_restoration': 'PASS', 'environment_remediation': remedy,
        'commits_created': 0, 'pushes_performed': 0, 'production_activation_or_deployment': False})
    acta = REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before = acta.read_bytes()
    assert b'WSL2 r8' not in before
    addition = '''

## 2026-10-11 — B9E 1947726: campaña WSL2 r8, solicitud temporal de actividad

Decisión integral **PENDING por entorno/disco**. Autorización «prosigue», conservando la admisión modificada y reserva de 2 GiB, disco de 1 GiB y reloj de 1 s. Mismo candidato y contratos. La nueva lectura de los mensajes completos Kernel-Power 42 confirma System Idle en r6/r7; sus reportes históricos se conservan intactos.

Se adquirió y monitoreó antes del sello una solicitud temporal propia SetThreadExecutionState. Ambos intérpretes privados pasaron con el mismo lock; 106 archivos de evaluador/configuración/herramientas y 13.508 de dependencias verificados; 3.332 fuentes exactas. La campaña formal del 12-10, 05:40:07–05:46:23 UTC, todavía 11-10 en México, se detuvo en el corpus dirigido: /mnt/c registró **908.460.032 bytes (0,85 GiB)** libres, por debajo de 1 GiB. No hubo discontinuidad de reloj ni agotamiento de reserva de memoria en el monitor formal. El espacio volvió a unos 3,8 GiB después del incidente; no se establece la causa de esa caída temporal ni se invalida la parada.

El journal conserva **53/87 IDs con estado ok** (39 B2 y dos negativas de asistencia incluidos), sin recibo final del runner: evidencia parcial, **no PASS del bloque**. El journal no contiene timestamps por ID para demostrar que todas las terminaciones precedieron al incidente. Checks backend, B0/B3/B4/B5/full, frontend, seguridad y cinco PROFILE NOT_EXECUTED. Cero reintentos formales y sin cambios productivos.

Cleanup PASS: dos bases propias, PostgreSQL, puerto y workspace retirados. Observador cerrado, solicitud temporal liberada con estado original restaurado, sincronización WSL active/running/enabled y W32Time intacto. Conservados 1.409 archivos de ocho campañas anteriores y cambios ajenos. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX y aprobaciones operativas/privacidad separados. [Reporte r8](../b9-integral-acceptance-1947726-wsl-20261011-r8/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r8/candidate-decision.json) e [incidente](../b9-integral-acceptance-1947726-wsl-20261011-r8/incident-classification.json). Sin commits, push, despliegue ni activación. Otra campaña requiere decisión nueva y margen estable de disco conservando los guards.
'''.encode('utf-8')
    acta.write_bytes(before + addition)
    assert acta.read_bytes()[:len(before)] == before
    save('acta-update.json', {'state': 'PASS', 'append_only': True,
        'prior_prefix_bytes': len(before), 'prior_prefix_sha256': digest(before),
        'appended_bytes': len(addition), 'appended_sha256': digest(addition),
        'final_sha256': digest(acta.read_bytes())})
    save('closure-reporting.json', {'state': 'PASS', 'created_after_stop': True,
        'reporting_script_sha256': digest(Path(__file__).read_bytes()), 'sealed_evaluator_changed': False,
        'cleanup': 'PASS', 'clock_restoration': 'PASS', 'resource_observer_cleanup': 'PASS',
        'awake_request_and_restoration': 'PASS', 'journal_ids_ok': 53, 'directed_gate_passed': False})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS', len(prior))


if __name__ == '__main__':
    main()
