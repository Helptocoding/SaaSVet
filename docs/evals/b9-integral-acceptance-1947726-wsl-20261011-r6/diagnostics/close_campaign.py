"""Post-stop reporting and append-only ACTA, without a formal retry."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[2]
SHA='194772677ca4e9fe1a1dec7f4dafa48396a6c583'
GIB=1024**3

def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(name,data):
    p=HERE/name
    assert not p.exists(),name
    p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    stop=read('STOP.json')
    assert stop=={'state':'PENDING','phase':'migrate','cause':'Clock discontinuity','no_rerun':True}
    assert read('cleanup.json')['state']=='PASS' and read('clock-restoration.json')['state']=='PASS'
    assert read('resource-observer-closure.json')['state']=='PASS'
    assert read('resource-observer-closure.json')['explicit_stop_requested']
    suite=read('blocks/directed.results.json')
    assert suite['tests']==87 and suite['exit_code']==0 and not any(suite[k] for k in ('failures','errors','skips','xfail'))
    assert sorted(suite['test_ids'])==read('directed-selected.json')
    labels=['directed','django-check','migration-drift','migrate']
    assert len(list((HERE/'blocks').glob('*.command.json')))==4
    rows={label:read('monitor-'+label+'.json') for label in labels}
    commands={label:read('blocks/'+label+'.command.json') for label in labels}
    for label in labels[:3]:
        assert read('blocks/'+label+'.gate.json')['state']=='PASS'
        assert commands[label]['exit_code']==0 and commands[label]['invalidating_incident'] is None
    assert commands['migrate']['exit_code']==-15 and commands['migrate']['invalidating_incident']=='Clock discontinuity'
    for p in HERE.glob('seal-check-*.json'):
        assert not json.loads(p.read_text())['mismatches'],p.name
    for p in HERE.glob('dependency-check-*.json'):
        assert not json.loads(p.read_text())['mismatches'],p.name
    assert not read('integrity-final-before-cleanup.json')['mismatches']
    prior=read('prior-evidence-before.json')
    mismatches=[name for name,h in prior.items() if not (REPO/name).is_file() or digest((REPO/name).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    unrelated={name:{'exists':(REPO/name).exists(),'sha256':digest((REPO/name).read_bytes()) if (REPO/name).exists() else None} for name in original}
    assert not mismatches and unrelated==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),
        'prior_campaign_mismatches':mismatches,'unrelated_unchanged':True,'unrelated':unrelated})
    statistics={label:{'samples':len(items),
        'minimum_host_available_bytes':min(r['host']['physical_available'] for r in items),
        'minimum_guest_available_bytes':min(r['guest']['physical_available'] for r in items),
        'minimum_backing_disk_available_bytes':min(r['guest']['disk_available'] for r in items),
        'maximum_absolute_clock_skew_seconds':max(abs(r['wall_minus_monotonic_seconds']) for r in items)}
        for label,items in rows.items()}
    save('monitor-summary.json',{'blocks':statistics,'samples':sum(len(items) for items in rows.values()),
        'memory_or_disk_reserve_exhausted':False,'clock_incident_block':'migrate',
        'host_samples_during_suspend':'Retained raw cached host observations; observer itself paused, and the clock guard stopped the block after resume'})
    observer=[json.loads(s) for s in (HERE/'resource-observer/samples.jsonl').read_text().splitlines()]
    gaps=[{'before':a['utc'],'after':b['utc'],'seconds':b['utc_epoch_seconds']-a['utc_epoch_seconds']}
        for a,b in zip(observer,observer[1:]) if b['utc_epoch_seconds']-a['utc_epoch_seconds']>5]
    save('resource-observer-summary.json',{'state':'CLOSED','samples':len(observer),'sampling_gaps_over_five_seconds':gaps,
        'source':'Same Windows GlobalMemoryStatusEx helper, persistent private Python process',
        'memory_fluctuation_cause_established':False,'application_tests_executed_by_observer':False})
    power=read('windows-clock-power-events.json')
    wake=next(e for e in power['events'] if e['provider']=='Microsoft-Windows-Power-Troubleshooter' and e['id']==1)
    assert any(e['provider']=='Microsoft-Windows-Kernel-Power' and e['id']==42 for e in power['events'])
    cause='Host suspension/resume coincides with a 121.912111-second civil-minus-monotonic discontinuity during the private checks migration'
    save('incident-classification.json',{'state':'PENDING_ENVIRONMENT_CLOCK','cause':cause,
        'product_failure_attributed':False,'raw_stop_preserved':True,
        'clock_skew_seconds':statistics['migrate']['maximum_absolute_clock_skew_seconds'],
        'original_clock_limit_seconds':1,'windows_sleep_time':wake['data']['SleepTime'],
        'windows_wake_time':wake['data']['WakeTime'],'windows_sleep_resume_events_confirmed':True,
        'correlation_limit':'Windows events confirm host suspension/resume in this interval; no claim that pausing WSL NTP prevents host suspension or every clock incident',
        'memory_or_disk_reserve_exhausted':False,'partial_migration_is_not_a_pass':True,
        'termination':'Controller SIGTERM of its owned process group, exit -15',
        'formal_reruns':0,'evidence':['STOP.json','monitor-migrate.json','blocks/migrate.command.json',
            'blocks/migrate.command.log','windows-clock-power-events.json','resource-observer/samples.jsonl']})
    all_labels=labels+['billing-schema','b0','b3','b4','b5','full','frontend-build','frontend-test','frontend-lint',
        'frontend-smoke-urls','security','pip-audit','pnpm-audit','profile-base','profile-blocked_llm',
        'profile-meta_slow','profile-duplicate','profile-saturation']
    save('block-status.json',{label:{'state':'PASS' if label in labels[:3] else 'INTERRUPTED_PENDING_ENVIRONMENT' if label=='migrate' else 'NOT_EXECUTED',
        'formal_runs':1 if label in labels else 0,'test_ids_completed':87 if label=='directed' else 0} for label in all_labels})
    save('execution-summary.json',{'formal_controller_invocations':1,'formal_block_runs':4,'formal_reruns':0,
        'backend_test_id_observations':87,'unique_test_ids_completed':87,'unique_test_ids_passed':87,
        'failures':0,'errors':0,'skips':0,'xfail':0,'profile_runs':0,
        'discovered_counts_not_execution':read('discovery.json')['counts'],
        'blocking_gates_passed':labels[:3],'interrupted_block':'migrate','remaining_blocks':'NOT_EXECUTED',
        'prior_campaign_results_transferred_to_r6':False})
    decision=read_prior_decision()
    decision.update(schema='b9i-wsl-r6-candidate-decision-v1',date='2026-10-11',candidate_sha=SHA,
        decision='PENDING',campaign_state='STOPPED_DURING_CHECKS_MIGRATION_HOST_SUSPENSION_CLOCK_DISCONTINUITY',
        cause=cause,cause_evidence=['incident-classification.json','windows-clock-power-events.json','monitor-migrate.json','STOP.json'],
        product_failure_attributed=False,raw_stop_state_preserved='PENDING',raw_runner_failures=0,
        formal_block_runs=4,formal_reruns=0,backend_id_observations=87,backend_unique_ids_passed=87,
        backend_unique_ids_raw_failed_before_contract=0,b0_tests={'state':'NOT_EXECUTED'},b3_tests={'state':'NOT_EXECUTED'},
        profile_variants_executed=0,clock_control='Approved WSL pause restored active/running/enabled; Windows W32Time unchanged; Windows host suspension occurred during checks migration',
        clock_or_resource_incidents_during_blocks=True,clock_incident='121.912111-second discontinuity during migrate; host suspension/resume confirmed',
        memory_or_disk_reserve_exhausted=False,resource_policy='User-amended 2 GiB admission/execution reserve; original 5 GiB prerequisite waived',
        frontend_dependency_install='PASS_FROZEN_LOCKFILE_IN_LINUX; frontend CI checks NOT_EXECUTED',
        evaluation_seal='99 files plus source/dependency manifests; all completed post-block checks intact',
        dual_interpreter_preflight='PASS; same locked application dependencies in venv and private base Python',
        dependency_files_checked=13508,cleanup='PASS',clock_restoration='PASS',resource_observer_cleanup='PASS',
        new_campaign='No automatic retry after this durable stop; any future temporal execution must avoid host suspension and revalidate clocks')
    decision['R01_R15'].update({
        'R01':'PENDING_INTEGRAL; directed corpus PASS, remaining gates incomplete after clock incident',
        'R04':'DIRECTED_SCALE_PASS; process regression runners and temporal PROFILE NOT_EXECUTED',
        'R06':'PARTIAL_LOCAL_CHECKS; directed, Django check and drift PASS; checks migration interrupted; schema/critical/full/frontend/security NOT_EXECUTED',
        'R11':'DIRECTED_BUDGET_PASS; Django check/drift PASS; checks migration incomplete and Billing schema NOT_EXECUTED',
        'R14':'EXISTING_DOCUMENTATION_PRESERVED; directed harness PASS; both interpreters validated before seal',
        'R15':'DECISION_AND_EVIDENCE_CONSERVED; technical PENDING; privacy/operational requirements separate'})
    decision['I01_I14'].update({
        'I09':'DIRECTED_TAKEOVER_PASS; B3/full regression NOT_EXECUTED',
        'I10':'DIRECTED_RECOVERY_PASS; selected B9 FI PASS; B3 crash/restart regression NOT_EXECUTED'})
    save('candidate-decision.json',decision)
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes();assert b'WSL2 r6' not in before
    addition='''

## 2026-10-11 — B9E 1947726: campaña WSL2 r6, reanudación

Decisión integral **PENDING por entorno/reloj**. Autorización «reanuda», conservando la excepción de admisión de memoria aprobada y la reserva de 2 GiB. Mismo SHA, selección, fixtures, cargas, tiempos y contratos. Se validaron ambos Python privados con el mismo lock. La sonda Windows pasó a un proceso persistente con la misma API, antes del sello.

El corpus dirigido terminó **87/87 PASS**, cero fallos/errores/skips/xfail. Django check y drift de migraciones también PASS. Durante la migración posterior de checks, el monitor detectó **121,912111 s** de discontinuidad civil−monotónica y detuvo su grupo de procesos. Los eventos de Windows confirman suspensión a las 03:59:21 UTC y reactivación a las 04:01:24 UTC del 12-10, todavía 11-10 en México. No se agotaron las reservas de memoria o disco. La migración parcial no se acredita como PASS ni como fallo del producto. Schema Billing, B0/B3/B4/B5/full, frontend, seguridad y las cinco variantes PROFILE quedaron NOT_EXECUTED. No hubo reintentos.

Fuentes, dependencias y sello íntegros. Cleanup PASS: retiradas las tres bases propias, PostgreSQL, workspace r6 y sonda propia de Windows. Sincronización WSL restaurada active/running/enabled, W32Time intacto. Las seis campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r6](../b9-integral-acceptance-1947726-wsl-20261011-r6/REPORT.md), [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r6/candidate-decision.json) y [eventos del host](../b9-integral-acceptance-1947726-wsl-20261011-r6/windows-clock-power-events.json). No se crearon commits ni se hizo push, despliegue o activación.
'''.encode('utf-8')
    acta.write_bytes(before+addition);after=acta.read_bytes()
    assert after[:len(before)]==before and after[len(before):]==addition
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),
        'prior_prefix_sha256':digest(before),'appended_bytes':len(addition),'appended_sha256':digest(addition),'final_sha256':digest(after)})
    save('closure-reporting.json',{'state':'PASS','created_after_stop':True,
        'reporting_script_sha256':digest(Path(__file__).read_bytes()),'sealed_evaluator_changed':False,
        'cleanup':'PASS','clock_restoration':'PASS','resource_observer_cleanup':'PASS','test_ids_passed':87})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS',len(prior))

def read_prior_decision():
    # Reuse disposition wording only, then explicitly replace campaign results.
    return json.loads((HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r3')/'candidate-decision.json').read_text(encoding='utf-8'))

if __name__=='__main__':
    main()
