"""Post-stop reporting and append-only ACTA; never execute a campaign or test."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
REPO=HERE.parents[2]
SHA='194772677ca4e9fe1a1dec7f4dafa48396a6c583'
GIB=1024**3

def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))

def save(name,data):
    path=HERE/name
    assert not path.exists(),name
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    stop=read('STOP.json')
    assert stop['state']=='PENDING' and stop['phase']=='directed' and stop['block_executed'] is False
    assert read('preflight.json')['state']=='PASS'
    assert read('interpreter-preflight.json')['state']=='PASS'
    assert read('cleanup.json')['state']=='PASS' and read('clock-restoration.json')['state']=='PASS'
    commands=list((HERE/'blocks').glob('*.command.json'))
    assert not commands and not list((HERE/'blocks').glob('*.results.json'))
    for name in ('integrity-final-before-cleanup.json','seal-check-preflight.json','seal-check-before-directed.json',
                 'dependency-check-preflight.json','dependency-check-before-directed.json'):
        assert not read(name)['mismatches']
    prior=read('prior-evidence-before.json')
    mismatches=[name for name,h in prior.items() if not (REPO/name).is_file() or digest((REPO/name).read_bytes())!=h]
    original=read('checkout-before.json')['unrelated']
    unrelated={name:{'exists':(REPO/name).exists(),'sha256':digest((REPO/name).read_bytes()) if (REPO/name).exists() else None}
        for name in original}
    assert not mismatches and unrelated==original
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(prior),
        'prior_campaign_mismatches':mismatches,'unrelated_unchanged':True,'unrelated':unrelated})
    classification={'state':'PENDING_ENVIRONMENT_RESOURCES','product_failure_attributed':False,
        'cause':'Windows backing-host available physical memory fell below the unchanged 5 GiB threshold immediately before the first block',
        'raw_stop_state_preserved':stop['state'],'block_executed':False,'application_tests_executed':0,
        'preflight_host_available_bytes':read('preflight.json')['resources']['host']['physical_available'],
        'before_directed_host_available_bytes':stop['resources']['host']['physical_available'],
        'before_directed_host_available_gib':stop['resources']['host']['physical_available']/GIB,
        'required_host_and_guest_available_bytes':5*GIB,'guest_resources_sufficient':True,
        'disk_resources_sufficient':True,'dependency_remediation_validated_before_seal':True,
        'clock_observation_passed':True,'formal_reruns':0,'blocks_remaining':'NOT_EXECUTED',
        'cause_of_host_memory_fluctuation':'Not established; temporally separated measurements do not prove a single cause',
        'evidence':['STOP.json','preflight.json','resource-ready-observation-4.json','interpreter-preflight.json',
            'dependency-check-before-directed.json','seal-check-before-directed.json']}
    save('incident-classification.json',classification)
    inventory=read('discovery.json')['counts']
    labels=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
        'frontend-build','frontend-test','frontend-lint','frontend-smoke-urls','security','pip-audit','pnpm-audit',
        'profile-base','profile-blocked_llm','profile-meta_slow','profile-duplicate','profile-saturation']
    save('block-status.json',{label:{'state':'NOT_EXECUTED','reason':'Durable resource stop before first block',
        'expected_ids':inventory.get(label),'formal_runs':0} for label in labels})
    save('execution-summary.json',{'formal_controller_invocations':1,'formal_block_runs':0,
        'application_test_id_observations':0,'unique_test_ids_executed':0,'profile_runs':0,
        'discovered_counts_not_execution':inventory,'formal_reruns':0,
        'preflight':'PASS','first_block':'NOT_EXECUTED_RESOURCE_STOP','backend_checks':'NOT_EXECUTED',
        'frontend_frozen_dependency_install':'PASS','frontend_checks':'NOT_EXECUTED',
        'prior_campaign_results_not_transferred_to_r4':True})
    save('candidate-decision.json',{'schema':'b9i-wsl-r4-candidate-decision-v1','date':'2026-10-11',
        'candidate_sha':SHA,'decision':'PENDING','campaign_state':'STOPPED_BEFORE_FIRST_BLOCK_INSUFFICIENT_HOST_MEMORY',
        'cause':classification['cause'],'cause_evidence':classification['evidence'],
        'product_failure_attributed':False,'raw_stop_state_preserved':'PENDING','application_tests_executed':0,
        'formal_block_runs':0,'formal_reruns':0,'profile_variants_executed':0,
        'R01_R15':{f'R{i:02d}':('DECISION_AND_LIMITS_DOCUMENTED; execution PENDING due to host resources; operational requirements remain separate'
            if i in (8,15) else 'PENDING_THIS_CAMPAIGN; no application tests, checks or PROFILE executed; prior evidence remains in its original campaign') for i in range(1,16)},
        'I01_I14':{f'I{i:02d}':'NOT_EVALUATED_THIS_CAMPAIGN; no test executed; historical dispositions preserved separately' for i in range(1,15)},
        'operational_requirements':{'R06_real_promotion_eval':'PENDING_SEPARATE','R13_real_release_readiness':'PENDING_SEPARATE','R15_P_A_P_B_privacy':'PENDING_SEPARATE'},
        'activation':'PENDING_ACTIVATION_REQUIREMENTS','R1-04':'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
        'E_P_UX':'SEPARATE_UNCHANGED_SCOPES','historical_profile_metrics_transferred_to_current_campaign':False,
        'preflight':'PASS','dual_interpreter_dependency_validation':'PASS','dependency_files_checked':13508,
        'sealed_evaluator_files':len(read('evaluation-seal.json')['files']),
        'candidate_sources':'3332 exact Git blobs; final integrity PASS',
        'cleanup':'PASS','clock_restoration':'PASS','Windows_W32Time_unchanged':True,
        'new_campaign':'Requires a new decision and sufficient host/guest resources before each block; no automatic retry',
        'commits_created':0,'pushes_performed':0,'production_activation_or_deployment':False})
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    before=acta.read_bytes()
    assert b'WSL2 r4' not in before,'ACTA already appended'
    text='''

## 2026-10-11 — B9E 1947726: campaña WSL2 r4

Decisión integral **PENDING**. Autorización «hazlo» para preparar el Python base y el venv privados con el mismo lock, validar ambos antes del sello y ejecutar una campaña nueva con los mismos gates. La validación de Django, módulos y paridad de dependencias pasó en ambos intérpretes; 13.508 archivos de dependencias y las 3.332 fuentes exactas quedaron comprobados. No se cambiaron producto, tests, fixtures, cargas ni umbrales.

El preflight pasó con 5,70 GiB libres en Windows. En el control inmediato anterior al corpus dirigido bajaron a 3,60 GiB, por debajo de los 5 GiB exigidos. La parada original se conserva: **cero tests, checks de aplicación o PROFILE ejecutados**. No se atribuye fallo al producto ni se trasladan los resultados de r3 a r4. No hubo reintentos.

Cleanup PASS: se retiró únicamente la base control, PostgreSQL y el workspace privado r4. La sincronización de WSL se restauró active/running/enabled; W32Time intacto. Las cuatro campañas anteriores y los cambios ajenos se conservaron. R1-04 mantiene PENDING aceptado; activación **PENDING_ACTIVATION_REQUIREMENTS**, E/P/UX separados. Expediente independiente: [reporte r4](../b9-integral-acceptance-1947726-wsl-20261011-r4/REPORT.md) y [decisión](../b9-integral-acceptance-1947726-wsl-20261011-r4/candidate-decision.json). Otra campaña requiere una decisión nueva y recursos suficientes; no se autoriza commit, push, despliegue ni activación.
'''
    addition=text.encode('utf-8')
    acta.write_bytes(before+addition)
    after=acta.read_bytes()
    assert after[:len(before)]==before and after[len(before):]==addition
    save('acta-update.json',{'state':'PASS','append_only':True,'prior_prefix_bytes':len(before),
        'prior_prefix_sha256':digest(before),'appended_bytes':len(addition),
        'appended_sha256':digest(addition),'final_sha256':digest(after)})
    save('closure-reporting.json',{'state':'PASS','created_after_stop':True,
        'reporting_script_sha256':digest(Path(__file__).read_bytes()),'sealed_evaluator_changed':False,
        'cleanup':'PASS','clock_restoration':'PASS','application_tests_executed':0})
    print('REPORTING_AND_APPEND_ONLY_ACTA_PASS',len(prior))

if __name__=='__main__':
    main()
