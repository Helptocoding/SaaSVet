"""Post-stop evidence and append-only ACTA, without test execution."""
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
    stop=read('STOP.json');receipt=read('blocks/directed.command.json')
    assert stop=={'state':'PENDING','phase':'directed','cause':'Memory reserve exhausted','no_rerun':True}
    assert receipt['invalidating_incident']=='Memory reserve exhausted' and receipt['exit_code']==-15
    assert len(list((HERE/'blocks').glob('*.command.json')))==1
    assert not list((HERE/'blocks').glob('*.results.json'))
    assert not (HERE/'blocks/directed.results.passed.jsonl').read_bytes()
    assert read('preflight.json')['state']=='PASS' and read('interpreter-preflight.json')['state']=='PASS'
    assert read('cleanup.json')['state']=='PASS' and read('clock-restoration.json')['state']=='PASS'
    for name in ('integrity-final-before-cleanup.json','seal-check-preflight.json',
        'seal-check-before-directed.json','seal-check-after-directed.json',
        'dependency-check-preflight.json','dependency-check-before-directed.json','dependency-check-after-directed.json'):
        assert not read(name)['mismatches'],name
    prior=read('prior-evidence-before.json')
    mismatches=[name for name,h in prior.items() if not (REPO/name).is_file() or digest((REPO/name).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    unrelated={name:{'exists':(REPO/name).exists(),'sha256':digest((REPO/name).read_bytes()) if (REPO/name).exists() else None} for name in original}
    assert not mismatches and unrelated==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),
        'prior_campaign_mismatches':mismatches,'unrelated_unchanged':True,'unrelated':unrelated})
    monitor=read('monitor-directed.json')
    statistics={'samples':len(monitor),'minimum_host_available_bytes':min(r['host']['physical_available'] for r in monitor),
        'minimum_guest_available_bytes':min(r['guest']['physical_available'] for r in monitor),
        'minimum_backing_disk_available_bytes':min(r['guest']['disk_available'] for r in monitor),
        'maximum_absolute_clock_skew_seconds':max(abs(r['wall_minus_monotonic_seconds']) for r in monitor)}
    save('monitor-summary.json',statistics)
    cause='Windows available physical memory fell below the retained 2 GiB execution reserve during directed-runner database migrations'
    save('incident-classification.json',{'state':'PENDING_ENVIRONMENT_RESOURCES','cause':cause,
        'product_failure_attributed':False,'raw_stop_preserved':True,'formal_block_runs':1,
        'test_ids_completed':0,'suite_receipt_absent':True,'partial_migrations_are_not_a_test_result':True,
        'termination':'Controller SIGTERM of its owned process group, exit -15',
        'admission_override':'Prior 5 GiB admission waived by explicit user instruction; block started with 4391899136 bytes available on host',
        'reserve_retained_bytes':2*GIB,'monitored_minimum_host_available_bytes':statistics['minimum_host_available_bytes'],
        'clock_or_disk_invalidating_incidents':False,'cause_of_host_memory_fluctuation':'Not established',
        'formal_reruns':0,'evidence':['STOP.json','blocks/directed.command.json','blocks/directed.log',
            'blocks/directed.results.passed.jsonl','monitor-directed.json','resource-policy.json']})
    counts=read('discovery.json')['counts']
    labels=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
        'frontend-build','frontend-test','frontend-lint','frontend-smoke-urls','security','pip-audit','pnpm-audit',
        'profile-base','profile-blocked_llm','profile-meta_slow','profile-duplicate','profile-saturation']
    save('block-status.json',{label:{'state':'INTERRUPTED_PENDING_ENVIRONMENT' if label=='directed' else 'NOT_EXECUTED',
        'formal_runs':1 if label=='directed' else 0,'expected_ids':counts.get(label),
        'test_ids_completed':0,'reason':'Memory reserve exhausted during first block bootstrap'} for label in labels})
    save('execution-summary.json',{'formal_controller_invocations':1,'formal_block_runs':1,'formal_reruns':0,
        'unique_test_ids_completed':0,'passed_test_id_journal_rows':0,'profile_runs':0,
        'discovered_counts_not_execution':counts,'preflight':'PASS_WITH_USER_AMENDED_ADMISSION',
        'directed':'INTERRUPTED_DURING_DATABASE_MIGRATIONS; no final suite receipt',
        'remaining_blocks':'NOT_EXECUTED','prior_results_transferred_to_r5':False})
    save('candidate-decision.json',{'schema':'b9i-wsl-r5-candidate-decision-v1','date':'2026-10-11',
        'candidate_sha':SHA,'decision':'PENDING','campaign_state':'STOPPED_DURING_DIRECTED_BOOTSTRAP_MEMORY_RESERVE',
        'cause':cause,'product_failure_attributed':False,'raw_stop_state_preserved':'PENDING',
        'formal_block_runs':1,'formal_reruns':0,'test_ids_completed':0,'profile_variants_executed':0,
        'R01_R15':{f'R{i:02d}':('DECISION_AND_LIMITS_DOCUMENTED; execution PENDING due to host resources; operational requirements separate'
            if i in (8,15) else 'PENDING_THIS_CAMPAIGN; no test completed; historical evidence preserved in its own campaign') for i in range(1,16)},
        'I01_I14':{f'I{i:02d}':'NOT_EVALUATED_THIS_CAMPAIGN; no test completed; historical dispositions preserved separately' for i in range(1,15)},
        'operational_requirements':{'R06_real_promotion_eval':'PENDING_SEPARATE','R13_real_release_readiness':'PENDING_SEPARATE','R15_P_A_P_B_privacy':'PENDING_SEPARATE'},
        'resource_condition':'Explicitly user-amended admission; 5 GiB prerequisite waived, 2 GiB execution reserve retained and exhausted',
        'activation':'PENDING_ACTIVATION_REQUIREMENTS','R1-04':'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX':'SEPARATE_UNCHANGED_SCOPES','historical_profile_metrics_transferred':False,
        'dual_interpreter_validation':'PASS','dependency_files_checked':13508,
        'candidate_sources':'3332 exact Git blobs; final integrity PASS','sealed_evaluator_files':len(read('evaluation-seal.json')['files']),
        'cleanup':'PASS','clock_restoration':'PASS','Windows_W32Time_unchanged':True,
        'new_campaign':'No automatic retry after durable stop; current evidence demonstrates insufficient retained reserve for this attempt',
        'commits_created':0,'pushes_performed':0,'production_activation_or_deployment':False})
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes();assert b'WSL2 r5' not in before
    addition='''

## 2026-10-11 — B9E 1947726: campaña WSL2 r5 con recursos actuales

Decisión integral **PENDING por entorno/recursos**. El usuario autorizó «procede con lo disponible actual, no puedo liberar mas aun». Se modificó explícitamente el mínimo de admisión de 5 GiB, conservando la reserva de ejecución de 2 GiB, disco/reloj/integridad y todos los contratos de producto. No se cambió el candidato, los tests, fixtures, cargas, tiempos ni aserciones. Ambos Python privados pasaron la validación con las dependencias congeladas.

El preflight pasó y el bloque dirigido inició con 4,09 GiB disponibles en Windows. Durante sus migraciones privadas el host bajó a **1,61 GiB**, agotando la reserva retenida. El controlador interrumpió solo su grupo de procesos mediante SIGTERM. Hubo una invocación formal del bloque, **cero IDs completados**, sin recibo final ni PROFILE. La migración parcial no se convierte en PASS o fallo del producto. STOP original y muestras conservados, sin reintentos. La excepción del mínimo de 5 GiB queda explícita; no se afirma que se cumplió ese prerrequisito histórico.

Cleanup PASS: retiradas las bases control/dirigida, PostgreSQL y solo el workspace r5. Sincronización WSL restaurada active/running/enabled, W32Time intacto. Las cinco campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. [Reporte r5](../b9-integral-acceptance-1947726-wsl-20261011-r5/REPORT.md) y [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r5/candidate-decision.json). No se crearon commits ni se hizo push, despliegue o activación.
'''.encode('utf-8')
    acta.write_bytes(before+addition);after=acta.read_bytes()
    assert after[:len(before)]==before and after[len(before):]==addition
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),
        'prior_prefix_sha256':digest(before),'appended_bytes':len(addition),'appended_sha256':digest(addition),'final_sha256':digest(after)})
    save('closure-reporting.json',{'state':'PASS','created_after_stop':True,
        'reporting_script_sha256':digest(Path(__file__).read_bytes()),'sealed_evaluator_changed':False,
        'cleanup':'PASS','clock_restoration':'PASS','test_ids_completed':0})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS',len(prior))

if __name__=='__main__':
    main()
