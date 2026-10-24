"""Close r9 from retained evidence; never run tests or replace original receipts."""
from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
GIB = 1024**3
COMPLETE = ['directed', 'django-check', 'migration-drift', 'migrate', 'billing-schema', 'b0', 'b3', 'b4', 'b5']
SUITES = ['directed', 'b0', 'b3', 'b4', 'b5']
REMAINING = ['frontend-build', 'frontend-test', 'frontend-lint', 'frontend-smoke-urls',
             'security', 'pip-audit', 'pnpm-audit', 'profile-base', 'profile-blocked_llm',
             'profile-meta_slow', 'profile-duplicate', 'profile-saturation']


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, data):
    p = HERE / name
    assert not p.exists(), name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    assert read('STOP.json') == {'state': 'PENDING', 'phase': 'full', 'cause': 'Backing disk reserve exhausted', 'no_rerun': True}
    assert read('cleanup.json')['state'] == read('cleanup-recovery-completion.json')['state'] == 'PASS'
    assert read('clock-restoration.json')['state'] == 'PASS'
    assert read('monitor-closure-after-restart.json')['state'] == 'PASS_CURRENT_PROCESS_ABSENCE'
    command = read('blocks/full.command.json')
    assert command['exit_code'] == -9 and command['invalidating_incident'] == 'Backing disk reserve exhausted'
    assert len(list((HERE / 'blocks').glob('*.command.json'))) == 10
    assert not (HERE / 'blocks/full.results.json').exists()
    completed_ids = []
    statuses = {}
    for label in COMPLETE:
        c, gate = read(f'blocks/{label}.command.json'), read(f'blocks/{label}.gate.json')
        assert c['exit_code'] == 0 and not c.get('invalidating_incident') and gate['state'] == 'PASS'
        statuses[label] = {'state': 'PASS', 'formal_runs': 1, 'seconds': c['seconds'], 'exit_code': 0}
        if label in SUITES:
            result, selected = read(f'blocks/{label}.results.json'), read(f'{label}-selected.json')
            assert result['tests'] == len(selected) == len(result['test_ids'])
            assert set(result['test_ids']) == set(selected)
            assert not any(result.get(k) for k in ['failures', 'errors', 'skips', 'xfail', 'xpass', 'failed_ids'])
            completed_ids.extend(result['test_ids'])
            statuses[label]['test_ids_pass'] = len(selected)
    partial = [json.loads(line) for line in (HERE / 'blocks/full.ids.jsonl').read_text().splitlines()]
    partial_ids = [row['id'] for row in partial]
    assert len(partial_ids) == len(set(partial_ids))
    selected = read('full-selected.json')
    assert set(partial_ids) <= set(selected)
    outcomes = dict(Counter(row['outcome'] for row in partial))
    assert outcomes == {'PASS': 2666, 'FAIL': 10, 'ERROR': 1, 'SKIP': 2}
    bad_ids = [r for r in partial if r['outcome'] in ['FAIL', 'ERROR']]
    skips = [r for r in partial if r['outcome'] == 'SKIP']
    save('full-partial-receipt.json', {'state': 'INCOMPLETE_INVALID_ENVIRONMENT',
         'required_ids': len(selected), 'journal_completed_ids': len(partial_ids), 'outcomes': outcomes,
         'test_ids': partial_ids, 'remaining_ids': sorted(set(selected) - set(partial_ids)),
         'remaining_count': len(set(selected) - set(partial_ids)), 'failed_or_error_records': bad_ids,
         'skips': skips, 'final_runner_receipt_available': False, 'full_gate_passed': False,
         'failure_tracebacks_available': False, 'failure_causes_classified': False,
         'interpretation': 'Raw observations are retained, including every FAIL/ERROR. The incomplete block has no valid final gate. No per-ID timestamps establish precise completion relative to the disk breach; failures are not attributed to disk or dismissed as legacy.'})
    statuses['full'] = {'state': 'INTERRUPTED_PENDING_ENVIRONMENT', 'formal_runs': 1,
         'required_ids': len(selected), 'completed_journal_ids': len(partial_ids), 'raw_outcomes': outcomes,
         'seconds': command['seconds'], 'exit_code': command['exit_code'], 'gate_passed': False}
    statuses.update({n: {'state': 'NOT_EXECUTED', 'formal_runs': 0} for n in REMAINING})
    save('block-status.json', statuses)
    expected_damaged = {'dependency-check-after-full.json', 'seal-check-after-full.json', 'invocation-formal.json'}
    damaged = read('damaged-receipts.json')
    assert {r['path'] for r in damaged['invalid_json']} == expected_damaged
    for row in damaged['files_with_null_bytes']:
        assert digest((HERE / row['path']).read_bytes()) == row['sha256']
    valid_hash_receipts = []
    for pattern in ['seal-check-*.json', 'dependency-check-*.json', 'integrity-*.json']:
        for p in HERE.glob(pattern):
            if p.name in expected_damaged:
                continue
            assert not read(p.name)['mismatches'], p.name
            valid_hash_receipts.append(p.name)
    for kind, count in [('candidate-sources', 3332), ('dependency-files', 13508), ('evaluation-seal', 108)]:
        check = read('recovery-integrity-' + kind + '.json')
        assert check['checked'] == count and not check['mismatches']
    save('integrity-summary.json', {'state': 'PASS_RETAINED_CHECKS_AND_NEW_POST_RESTART_CHECK',
         'valid_original_receipts': valid_hash_receipts,
         'original_post_full_dependency_and_seal_receipts_damaged': True,
         'new_checks_do_not_replace_or_revalidate_interrupted_block': True,
         'sources': 3332, 'dependencies': 13508, 'seal_files': 108, 'mismatches': []})
    prior = read('prior-evidence-before.json')
    drift = [name for name, h in prior.items() if not (REPO / name).is_file() or digest((REPO / name).read_bytes()) != h]
    original = read('checkout-before.json')['unrelated']
    actual = {name: {'exists': (REPO / name).exists(), 'sha256': digest((REPO / name).read_bytes()) if (REPO / name).exists() else None} for name in original}
    assert not drift and actual == original
    save('preservation-of-prior-work.json', {'prior_campaign_files_checked': len(prior),
         'prior_campaign_count': 9, 'prior_campaign_mismatches': drift,
         'unrelated_unchanged': True, 'unrelated': actual})
    stats, all_rows = {}, []
    for label in COMPLETE + ['full']:
        rows = read('monitor-' + label + '.json')
        all_rows.extend(rows)
        stats[label] = {'samples': len(rows), 'first_utc': rows[0]['guest']['utc'], 'last_utc': rows[-1]['guest']['utc'],
             'minimum_host_available_bytes': min(r['host']['physical_available'] for r in rows),
             'minimum_guest_available_bytes': min(r['guest']['physical_available'] for r in rows),
             'minimum_backing_disk_available_bytes': min(r['guest']['disk_available'] for r in rows),
             'maximum_absolute_clock_skew_seconds': max(abs(r['wall_minus_monotonic_seconds']) for r in rows),
             'awake_states': sorted({r['awake']['state'] for r in rows}),
             'maximum_checked_awake_heartbeat_age_seconds': max(r['awake']['sample_age_seconds'] for r in rows)}
        assert stats[label]['minimum_host_available_bytes'] >= 2*GIB
        assert stats[label]['minimum_guest_available_bytes'] >= 2*GIB
        assert stats[label]['maximum_absolute_clock_skew_seconds'] <= 1
        assert stats[label]['awake_states'] == ['ACTIVE_CONFIRMED']
        if label != 'full':
            assert stats[label]['minimum_backing_disk_available_bytes'] >= GIB
    breach = [r for r in read('monitor-full.json') if r['guest']['disk_available'] < GIB]
    assert breach
    save('monitor-summary.json', {'blocks': stats, 'samples': len(all_rows),
         'memory_reserve_exhausted': False, 'disk_reserve_exhausted': True, 'clock_incident': False,
         'awake_request_unavailable': False, 'first_disk_breach': breach[0], 'disk_breach_samples': len(breach),
         'scope': 'Formal monitor samples only; no claim of continuity across host restart'})
    for folder, filename, target in [('resource-observer', 'samples.jsonl', 'resource-observer-summary.json'),
                                     ('awake-request', 'heartbeat.jsonl', 'awake-request-summary.json')]:
        rows = [json.loads(line) for line in (HERE / folder / filename).read_text().splitlines()]
        gaps = [{'before': a['utc'], 'after': b['utc'], 'seconds': b['utc_epoch_seconds'] - a['utc_epoch_seconds']}
                for a, b in zip(rows, rows[1:]) if b['utc_epoch_seconds'] - a['utc_epoch_seconds'] > 5]
        save(target, {'state': 'ABSENT_AFTER_HOST_RESTART', 'samples': len(rows),
             'first_utc': rows[0]['utc'], 'last_utc': rows[-1]['utc'], 'sampling_gaps_over_five_seconds': gaps,
             'normal_closure_receipt_available': False, 'current_process_absence_verified': True,
             'application_tests_executed_by_monitor': False, 'global_power_policy_changed': False,
             'W32Time_changed': False, 'formal_monitor_checks_all_active_confirmed': True})
    save('incident-classification.json', {'state': 'PENDING_ENVIRONMENT_DISK_AND_INCOMPLETE_RECEIPTS',
         'raw_stop_preserved': True, 'cause': 'Frozen monitor observed backing volume below original 1 GiB reserve',
         'reserve_bytes': GIB, 'first_breach_utc': breach[0]['guest']['utc'],
         'minimum_monitor_disk_bytes': stats['full']['minimum_backing_disk_available_bytes'],
         'disk_after_block_bytes': command['resources_after']['guest']['disk_available'],
         'space_drop_cause_established': False, 'product_failure_attributed': False,
         'partial_failures_preserved_and_unclassified': bad_ids, 'failures_attributed_to_disk': False,
         'host_unexpected_restart_observed': True, 'restart_or_storage_damage_causality_established': False,
         'damaged_original_receipts': sorted(expected_damaged), 'formal_controller_exit_code': None,
         'memory_reserve_exhausted': False, 'clock_incident_in_retained_formal_samples': False,
         'termination': 'Owned full-suite group terminated by frozen resource monitor; retained command exit -9',
         'formal_reruns': 0, 'later_resource_recovery_does_not_revalidate_block': True})
    save('execution-summary.json', {'formal_controller_invocations': 1, 'formal_controller_final_receipt_valid': False,
         'formal_block_runs': 10, 'formal_reruns': 0, 'complete_backend_suite_receipts': 5,
         'backend_test_id_observations': len(completed_ids) + len(partial_ids),
         'complete_gate_test_id_observations': len(completed_ids), 'complete_gate_unique_ids': len(set(completed_ids)),
         'unique_ids_across_complete_and_partial_blocks': len(set(completed_ids) | set(partial_ids)),
         'overlapping_observations': len(completed_ids) + len(partial_ids) - len(set(completed_ids) | set(partial_ids)),
         'partial_full_outcomes': outcomes, 'partial_full_unique_ids': len(partial_ids),
         'full_final_totals': None, 'blocking_gates_passed': COMPLETE, 'interrupted_block': 'full',
         'remaining_blocks': 'NOT_EXECUTED', 'profile_runs': 0,
         'discovered_counts_not_execution': read('discovery.json')['counts'],
         'prior_campaign_results_transferred_to_r9': False})
    write_decision_and_report(statuses, stats, bad_ids, skips, prior, breach)


# Reporting functions below use only the validated receipts above.
def write_decision_and_report(statuses, stats, bad_ids, skips, prior, breach):
    canonical = read('scope-manifest.json')['canonical_references']
    complete = set(read('blocks/directed.results.json')['test_ids'])
    def coverage(refs, limit='Aceptación integral pendiente; alcance dirigido solamente'):
        ids = [canonical[r] for r in refs]
        assert set(ids) <= complete
        return {'state': 'PASS_DIRECTED_SCOPE', 'references': refs, 'test_ids': ids, 'limit': limit}
    I = {
        'I01': coverage([f'B9E-E2E-{n:02}' for n in range(3, 8)] + [f'B9E-GATE-{n:02}' for n in range(1, 6)]),
        'I02': coverage(['B9E-E2E-13', 'B9E-FI-05']),
        'I03': coverage(['B9E-E2E-01', 'B9E-E2E-15']),
        'I04': {'state': 'PASS_DIRECTED_SCOPE', 'test_ids': sorted(i for i in complete if '.test_b8d_attendance.' in i or i.endswith('test_query_never_mutates_even_forced_wrong_tool')), 'limit': 'Negativas exactas de pregunta directa/indirecta y herramienta equivocada; no aceptación integral'},
        'I05': coverage([f'B9E-GATE-{n:02}' for n in range(1, 6)] + ['B9E-E2E-09']),
        'I06': coverage(['B9E-E2E-01'] + [f'B9E-E2E-{n:02}' for n in range(3, 8)] + ['B9E-E2E-11']),
        'I07': {'state': 'PASS_DIRECTED_SCOPE', 'test_ids': sorted(i for i in complete if '.test_b2_results.' in i), 'limit': '39 negativas/contratos B2 completos; no aceptación integral'},
        'I08': coverage(['B9E-E2E-14', 'B9E-SCALE-02'], 'Safety dirigida PASS; SATURATION y comprobación temporal NOT_EXECUTED'),
        'I09': coverage(['B9E-FI-04', 'B9E-FI-07', 'B9E-E2E-10']),
        'I10': coverage(['B9E-FI-01', 'B9E-FI-02', 'B9E-FI-10']),
        'I11': coverage(['B9E-FI-03', 'B9E-E2E-11'], 'Incertidumbre/reconciliación dirigida PASS; META_SLOW NOT_EXECUTED'),
        'I12': coverage(['B9E-E2E-00C', 'B9E-E2E-00D', 'B9E-E2E-13', 'B9E-READ-03']),
        'I13': coverage(['B9E-E2E-09', 'B9E-SCALE-01']),
        'I14': coverage(['B9E-E2E-13', 'B9E-FI-05'])}
    R = {
        'R01': 'PENDING_INTEGRAL; full interrumpido, frontend/seguridad/PROFILE sin ejecutar',
        'R02': 'PASS_DIRECTED_SCOPE; READ, cinco WRITE, pipeline y procesos del corpus 87/87',
        'R03': 'PASS_DIRECTED_COST_SCOPE; presupuesto compartido/uso desconocido; sin métricas PROFILE',
        'R04': 'PASS_DIRECTED_SCALE_SCOPE; N=1 y procesos independientes; PROFILE pendiente',
        'R05': 'PASS_DIRECTED_SCOPE; reserva/retry sin refund y FI del corpus',
        'R06': 'PENDING_INTEGRAL_CHECKS; nueve gates PASS; full incompleto y frontend/seguridad NOT_EXECUTED',
        'R07': 'PENDING_NOT_EXECUTED; cinco PROFILE',
        'R08': 'DECISION_AND_LIMITS_DOCUMENTED; PENDING técnico separado de activación',
        'R09': 'PENDING_NOT_EXECUTED; no p95/denominadores temporales del candidato',
        'R10': 'PASS_DIRECTED_SCOPE; EVAL/COST/SCALE, diez FI y 41 negativas adicionales; integral pendiente',
        'R11': 'PASS_SELECTED_SCOPE; COST, Django/drift/migrate y Billing schema; no inferir suite B9B completa',
        'R12': 'PASS_DIRECTED_SCOPE; N-minus-one/N/N-plus-one; sin afirmación de capacidad comercial',
        'R13': 'PASS_DIRECTED_RELEASE_NEGATIVES; readiness/aprobaciones reales pendientes',
        'R14': 'PREPARATION_AND_METHOD_RECORDED; fuentes exactas e intérpretes bloqueados; límites de cierre documentados',
        'R15': 'DECISION_AND_EVIDENCE_CONSERVED; privacidad y requisitos operativos separados'}
    save('candidate-decision.json', {'schema': 'b9i-wsl-r9-candidate-decision-v1',
        'date_local': '2026-10-13', 'timezone': 'America/Mexico_City',
        'candidate_sha': read('checkout-before.json')['head'], 'decision': 'PENDING',
        'campaign_state': 'STOPPED_DURING_FULL_BACKING_DISK_RESERVE_WITH_DAMAGED_FINAL_RECEIPTS',
        'product_failure_attributed': False, 'raw_stop_state_preserved': 'PENDING',
        'formal_block_runs': 10, 'formal_reruns': 0, 'blocking_gates_passed': COMPLETE,
        'directed_complete_gate': True, 'directed_ids_pass': 87,
        'full_partial_outcomes': read('full-partial-receipt.json')['outcomes'],
        'full_gate_passed': False, 'full_final_runner_totals': None, 'profile_variants_executed': 0,
        'partial_failure_causes_unclassified': True, 'R01_R15': R, 'I01_I14': I,
        'coverage_definition': 'Only this campaign complete PASS receipts support directed coverage. Partial full outcomes do not form a valid full gate and raw failures remain unclassified. Historical results are not transferred.',
        'operational_requirements': {'R06_real_promotion_eval': 'PENDING_SEPARATE',
            'R13_real_release_readiness': 'PENDING_SEPARATE', 'R15_P_A_P_B_privacy': 'PENDING_SEPARATE'},
        'activation': 'PENDING_ACTIVATION_REQUIREMENTS', 'R1-04': 'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX': 'SEPARATE_UNCHANGED_SCOPES', 'prior_campaign_results_transferred_to_r9': False,
        'resource_policy': 'User-amended 2 GiB admission/execution reserve; original 1 GiB disk and 1-second clock guards',
        'candidate_sources_checked_after_restart': 3332, 'dependency_files_checked_after_restart': 13508,
        'evaluation_seal_files_checked_after_restart': 108,
        'cleanup': 'PASS_AFTER_POSTGRESQL_CRASH_RECOVERY', 'clock_current_state': 'PASS_ACTIVE_RUNNING_ENABLED',
        'monitor_current_absence': 'PASS', 'normal_monitor_and_guardian_closure_receipts': 'MISSING_AFTER_RESTART',
        'commits_created': 0, 'pushes_performed': 0, 'production_activation_or_deployment': False})
    save('environment-remediation.json', {'state': 'NEW_CAMPAIGN_NOT_STARTED',
         'primary_observed_blocker': 'Backing volume dropped below 1 GiB',
         'additional_limits': 'Unexpected host restart, three invalid JSON receipts, missing graceful monitor closures',
         'root_cause_of_space_drop_or_restart': 'NOT_ESTABLISHED',
         'requirements_before_a_separately_authorized_new_campaign': [
             'A backing volume with stable free space above 1 GiB throughout the fixed run, with preparation and fluctuation margin',
             'Host continuity and new preflight; preserve memory/clock/awake guards and exact candidate/locks',
             'Inspect retained FAIL/ERROR IDs in a separately authorized diagnostic task; do not convert them to PASS or exclude them'],
         'formal_rerun_performed': False, 'threshold_changes': False, 'product_or_test_fixes': False})
    disk_min = stats['full']['minimum_backing_disk_available_bytes']
    disk_after = read('blocks/full.command.json')['resources_after']['guest']['disk_available']
    rows = '\n'.join(f"| {label} | PASS | {statuses[label].get('test_ids_pass', 'check')} | {statuses[label]['seconds']:.3f} |" for label in COMPLETE)
    failures = '\n'.join(f"- `{r['outcome']}` — `{r['id']}`" for r in bad_ids)
    skipped = '\n'.join(f"- `{r['id']}`: {r['reason']}" for r in skips)
    report = f'''# B9E — r9 cerrada: PENDING por entorno y evidencia final incompleta

Decisión del **13-10-2026, America/Mexico_City**, para
`194772677ca4e9fe1a1dec7f4dafa48396a6c583` en `codex/e4-capacity-scheduling`.
La campaña preparada el 12-10 terminó por el guard original de disco durante
la suite completa. **Nueve gates completos PASS**, incluidos el corpus dirigido
**87/87** y B0/B3/B4/B5. La aceptación integral queda **PENDING**.

## Resultados conservados

| Bloque | Gate | IDs/check | Duración del comando (s) |
|---|---|---:|---:|
{rows}
| full | PENDING, interrumpido | 2.679/3.331 IDs observados | 7289.097 |
| Frontend, seguridad y auditorías advisory | NOT_EXECUTED | 0 | — |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE, SATURATION | NOT_EXECUTED | 0 | — |

Los cinco recibos completos de pruebas contienen **251 IDs PASS únicos**.
La suite completa conserva **2.666 PASS, 10 FAIL, 1 ERROR y 2 SKIP**; faltan
**652 IDs** y el recibo final. Sumando las observaciones completas y parciales
hay **2.930 registros sobre 2.723 IDs únicos**, con 207 solapes. Esos totales
describen evidencia observada y no equivalen a una regresión completa aprobada.
Cada bloque tuvo una única corrida formal; no hubo reintentos de pruebas.

Los [recibos por bloque](block-status.json), [conteos deduplicados](execution-summary.json)
y [journal parcial clasificado](full-partial-receipt.json) conservan el detalle.
Las duraciones anteriores son las del comando monitorizado, no las del runner interno.

## Parada y límites de la evidencia

El [STOP original](STOP.json) indica `Backing disk reserve exhausted`, fase
`full`. El primer incumplimiento monitorizado fue a **{breach[0]['guest']['utc']}**
(01:23:17 del 13-10 en México): **{disk_min:,} bytes**, unos **{disk_min/GIB:.2f} GiB**,
frente al mínimo de 1 GiB. El recibo del comando registra **{disk_after:,} bytes**
(unos **{disk_after/1024**2:.0f} MiB**) tras la terminación, exit **-9**.
El espacio disponible se recuperó después; no se conoce la causa de la caída y
esa recuperación no valida el bloque interrumpido.

En los monitores formales conservados no se agotó la reserva de memoria de
2 GiB ni se superó el guard de reloj de 1 s. Durante full, Windows tuvo un mínimo
de **{stats['full']['minimum_host_available_bytes']/GIB:.3f} GiB**, y la desviación máxima de
reloj fue **{stats['full']['maximum_absolute_clock_skew_seconds']:.9f} s**. La solicitud de
actividad apareció `ACTIVE_CONFIRMED` en todos los checks. Esto describe las
muestras conservadas, sin afirmar continuidad durante el reinicio posterior.

Windows conserva eventos Kernel-Power 41 y EventLog 6008 de un reinicio
inesperado, con arranque registrado el 13-10 a las 18:08 de México. Los timestamps
del mensaje histórico y del journal se conservan sin inferir una cronología
exacta del apagado ni una causa. Al retomar, tres JSON finales estaban rellenos
de bytes NUL: `invocation-formal.json`, `dependency-check-after-full.json` y
`seal-check-after-full.json`. `invocation-formal.log` tiene una cola de 107 NUL.
Se preservan sus bytes originales; no se fabricaron recibos finales sustitutos.
Véanse [daños observados](damaged-receipts.json), [eventos del host](host-restart-evidence.json)
y [clasificación](incident-classification.json).

La suite fue interrumpida antes de imprimir las trazas finales de unittest.
Los 10 fallos y el error son observaciones reales del journal; su causa sigue
sin clasificar. No se atribuyen al disco, no se descartan por ser tests legacy
y no se convierten en PASS. El journal carece de timestamps por ID para probar
la relación temporal exacta de cada terminación con el incidente.

{failures}

Skips identificados, sin usarlos para cubrir requisitos pendientes:

{skipped}

## Integridad y cierre

Los nueve bloques completados conservaron sus checks de integridad válidos.
Después del reinicio se comprobaron de nuevo **3.332 fuentes**, **13.508 archivos
de dependencias** y **108 archivos del sello**, todos sin diferencias. Son
recibos nuevos de recuperación; no sustituyen los dos checks finales dañados.
El candidato, sus locks, los tests y los helpers evaluativos sellados no cambiaron.

El primer cleanup encontró PostgreSQL apagado. Se arrancó exclusivamente el
clúster privado para conservar propiedad, conexiones, transacciones y tablas
por SQL. El arranque superó el timeout de pg_ctl pero terminó su recuperación;
se comprobó que estaba listo antes de continuar. Se conservaron los intentos
fallidos del cierre, incluido un inventario que contó su propio wrapper RTK.
El [cleanup final](cleanup.json) retiró las bases propias, apagó PostgreSQL,
cerró el puerto 35479 y eliminó únicamente el workspace exacto de r9.
No se ejecutaron tests durante la recuperación.

WSL está `active/running/enabled` para systemd-timesyncd, igual al estado
original. Los PIDs originales del observador y la solicitud de actividad están
ausentes. Faltan los recibos de cierre normal de esos procesos y del guardián;
no se afirma que sus bloques finally terminaran ni que se probara la llamada
explícita de restauración del thread. Véanse [estado del reloj](clock-restoration.json)
y [ausencia de procesos](monitor-closure-after-restart.json). W32Time y las
políticas globales de energía/pantalla no se modificaron.

Se verificaron **{len(prior)} archivos de nueve campañas anteriores** sin cambios,
además de los tres cambios ajenos registrados. El reporte inicial de r9 anterior
a su reanudación sigue en [su copia histórica exacta](preparation-history/REPORT-before-resumption.md).
La nueva documentación de recuperación queda fuera del evaluador sellado.

## Decisión y conservación

La [matriz R01–R15/I01–I14](candidate-decision.json) usa solamente esta campaña:
cobertura dirigida PASS donde existe recibo, regresión integral y PROFILE
pendientes. Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING con
limitación aceptada y cero nuevos intentos físicos; E/P/UX y aprobaciones
operativas/privacidad siguen separados. Sin commits, push, despliegue ni activación.

Una campaña nueva exige decisión separada y un volumen que sostenga la reserva
original de 1 GiB con margen para preparación y fluctuaciones, además de
continuidad del host y nuevo preflight. Esta campaña queda cerrada y no se reanuda
desde el punto de corte. Los fallos parciales siguen disponibles para un diagnóstico
separado. [Requisitos para avanzar](environment-remediation.json).

[Índice y recuperación](README.md). El resultado del empaquetado y de la selección
Git explícita se acredita en los recibos de entrega enlazados allí; no implica un commit.
'''
    (HERE / 'REPORT.md').write_text(report, encoding='utf-8', newline='\n')
    readme = '''# Evidencia r9 — candidato 1947726

[Reporte y límites](REPORT.md) · [Decisión](candidate-decision.json) ·
[Estado por bloque](block-status.json) · [Incidente](incident-classification.json) ·
[Índice de archivos](artifact-index.json) · [Inventario del paquete](preservation-manifest.json) ·
[Prueba de recuperación](preservation-verification.json) · [Verificación de entrega](delivery-verification.json).

El paquete conserva también logs originales y recibos dañados. Los hashes prueban
la conservación de esos bytes; no convierten JSON inválido en evidencia válida.
`artifact-index.json` enumera el núcleo antes del paquete; los recibos de entrega
son posteriores y se conservan como archivos Git independientes.

Para recuperar en una carpeta nueva, ejecutar desde este expediente:

```powershell
rtk proxy python -B restore_wsl.py --destination C:/ruta/nueva/recuperacion-r9
```

El comando comprueba SHA-256 de las partes, del ZIP y de cada miembro; rechaza
un destino existente. No inicia PostgreSQL ni pruebas. El empaquetador ejecuta
una recuperación interna y otra por el CLI real en destinos temporales distintos.

Solo se preparan los paths explícitos de `git-selection.json` en la rama original.
Se preservan los blobs previamente staged fuera de los tres archivos compartidos
de entrega. Los logs están dentro del ZIP sin normalización; no se agregan sueltos
al índice Git. No hay commit ni push.
'''
    (HERE / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    acta = REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before = acta.read_bytes()
    assert b'WSL2 r9' not in before
    addition = '''

## 2026-10-13 — B9E 1947726: campaña WSL2 r9 cerrada

Decisión integral **PENDING por entorno y recibos finales incompletos**. Preparación reanudada por «prosige» el 12-10, mismo candidato y contratos, reserva de memoria autorizada de 2 GiB, disco de 1 GiB y reloj de 1 s. Corpus dirigido **87/87**, B0 **17/17**, B3 **42/42**, B4 **68/68**, B5 **37/37**, Django check/drift/migrate y Billing schema: nueve gates **PASS** con integridad válida. La suite full de 3.331 IDs fue interrumpida por disco: monitor 708.132.864 bytes (0,66 GiB), recibo posterior 267.816.960 bytes (255 MiB), exit -9. Retuvo **2.666 PASS, 10 FAIL, 1 ERROR, 2 SKIP**; 652 IDs sin resultado. Causas de fallos parciales sin clasificar y sin trazas finales; no se atribuyen automáticamente al entorno ni al producto. Frontend, seguridad y cinco PROFILE **NOT_EXECUTED**. Cero reintentos formales.

Al retomar se observaron un reinicio inesperado del host, tres JSON finales con bytes NUL y ausencia de recibos de cierre normal de los monitores/guardián. Se conservan originales exactos. Nueva comprobación posterior: 3.332 fuentes, 13.508 dependencias y 108 archivos sellados sin diferencias; no revalida la suite incompleta. Cleanup recuperado PASS: SQL de propiedad guardado tras recuperar PostgreSQL privado, bases/servicio/puerto/workspace retirados. Sincronización WSL actual active/running/enabled y PIDs originales ausentes, sin afirmar cierre graceful anterior. W32Time y políticas globales intactos. 1.623 archivos de nueve campañas anteriores y cambios ajenos preservados.

Matriz R/I con PASS limitado al corpus dirigido donde corresponde; aceptación integral PENDING. Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado y E/P/UX/operación/privacidad separados. [Reporte r9](../b9-integral-acceptance-1947726-wsl-20261012-r9/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261012-r9/candidate-decision.json) y [conservación](../b9-integral-acceptance-1947726-wsl-20261012-r9/README.md). Sin commits, push, despliegue ni activación. No hay campaña nueva automática.
'''.encode('utf-8')
    acta.write_bytes(before + addition)
    assert acta.read_bytes()[:len(before)] == before
    save('acta-update.json', {'state': 'PASS', 'append_only': True, 'prior_prefix_bytes': len(before),
         'prior_prefix_sha256': digest(before), 'appended_bytes': len(addition),
         'appended_sha256': digest(addition), 'final_sha256': digest(acta.read_bytes())})
    save('closure-reporting.json', {'state': 'PASS', 'created_after_stop': True,
         'reporting_script_sha256': digest(Path(__file__).read_bytes()), 'sealed_evaluator_changed': False,
         'damaged_receipts_preserved': True, 'decision': 'PENDING', 'formal_reruns': 0})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS', len(prior))


if __name__ == '__main__':
    main()
