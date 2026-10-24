"""New campaign with the user's explicit override of the admission headroom."""
import hashlib
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PRIOR=HERE.with_name('b9-integral-acceptance-1947726-wsl-20261011-r4')
WORK='/home/lap/b9i-wsl-1947726-20261011-r5'

def save(name,data):
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    assert not (HERE/'authorization.json').exists()
    save('authorization.json',{'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'user_instruction':'procede con lo disponible actual, no puedo liberar mas aun',
        'authorized_scope':'New campaign using currently available resources; override the previous 5 GiB admission prerequisite while retaining the existing 2 GiB execution reserve, source/dependency integrity, clock/disk controls and all product gates',
        'candidate_sha':'194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'prior_campaigns_restarted':False,'Windows_W32Time_changes_authorized':False,
        'product_fixtures_workload_timing_assertion_changes_authorized':False,
        'commit_push_deploy_activation_authorized':False})
    folders=[HERE.with_name(n) for n in ('b9-integral-acceptance-1947726',
        'b9-integral-acceptance-1947726-wsl-20261011',
        'b9-integral-acceptance-1947726-wsl-20261011-r2',
        'b9-integral-acceptance-1947726-wsl-20261011-r3',PRIOR.name)]
    save('prior-evidence-before.json',{p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in folders for p in folder.rglob('*') if p.is_file()})
    for name in ('prepare_wsl.py','stage_wsl.py','host_resources.py','discover_candidate.py',
        'recorded_suite.py','run_campaign.py','launch_campaign.py','restore_wsl.py','cleanup_linux.py',
        'capture_wsl.py','preseal.py','deliver_wsl.py','interpreter_preflight.py','clock_setup.py'):
        source=(PRIOR/name).read_text(encoding='utf-8')
        source=source.replace('/home/lap/b9i-wsl-1947726-20261011-r4',WORK)
        if name=='preseal.py':
            source=source.replace("'b9-integral-acceptance-1947726-wsl-20261011-r3'",repr(PRIOR.name))
        if name in ('clock_setup.py','deliver_wsl.py'):
            source=source.replace('r4-','r5-').replace('WSL r4:','WSL r5:')
        if name=='run_campaign.py':
            assert source.count('>=5*GIB')==2
            source=source.replace('>=5*GIB','>=2*GIB')
            source=source.replace("'single_suite':3*GIB,'memory_reserve':2*GIB", "'suite_estimate_not_reserved':3*GIB,'admission_floor':2*GIB,'memory_reserve':2*GIB,'prior_5_gib_admission_waived_by_user':True")
            source=source.replace("EVIDENCE/'assembly-adaptations.json',", "EVIDENCE/'assembly-adaptations.json',EVIDENCE/'resource-policy.json',")
            source=source.replace("'runtime_and_lock_changes':False", "'runtime_and_lock_changes':False,'resource_policy':'USER_AMENDED_ADMISSION_HEADROOM'")
        if name=='capture_wsl.py':
            source=source.replace("args = {", "args = {\n        'preseal-prepare': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/preseal_prepare.py'],")
        (HERE/name).write_text(source,encoding='utf-8',newline='\n')
        compile(source,str(HERE/name),'exec')
    save('resource-policy.json',{'state':'USER_AMENDED_BEFORE_SEAL',
        'instruction':'procede con lo disponible actual, no puedo liberar mas aun',
        'prior_host_and_guest_admission_bytes':5*1024**3,
        'host_and_guest_admission_floor_bytes':2*1024**3,
        'host_and_guest_execution_reserve_bytes':2*1024**3,
        'suite_memory_estimate_bytes_not_guaranteed':3*1024**3,
        'backing_disk_reserve_bytes':1024**3,'clock_discontinuity_limit_seconds':1,
        'suites_sequential':True,'internal_test_concurrency_unchanged':True,
        'oom_or_reserve_exhaustion_action':'Stop PENDING, no retry',
        'interpretation':'Results belong to this explicitly amended resource condition. Do not claim the original 5 GiB prerequisite was satisfied when it was not.',
        'product_gates_fixtures_load_timings_changed':False})
    canonical=(folders[0]/'PLAN.md').read_text(encoding='utf-8')
    (HERE/'PLAN.md').write_text('# B9E — campaña WSL2 r5 con recursos actuales autorizados\n\n'
        'Autorización: «procede con lo disponible actual, no puedo liberar mas aun». '
        'Esta decisión modifica explícitamente el mínimo de admisión de 5 GiB: se permite iniciar con la memoria disponible '
        'si Windows y WSL conservan al menos la reserva original de 2 GiB. Se mantiene esa reserva durante la ejecución, '
        'disco real mínimo de 1 GiB, monitor horario original y parada ante OOM, corrupción o deriva. '
        'No se afirma que estén reservados los 3 GiB estimados para una suite ni que se cumplió el prerrequisito histórico de 5 GiB. '
        'Los resultados corresponden a esta condición de recursos modificada por el usuario.\n\n'
        'Se conserva el mismo SHA, selección, producto, tests, fixtures, tasas, concurrencia interna, tiempos y gates de contrato. '
        'Se preparan y validan ambos intérpretes privados con el mismo lock antes del sello. '
        'La pausa temporal de sincronización de WSL previamente autorizada se comprueba durante 120 s y se restaura al cierre, '
        'con guardián de seis horas. Windows W32Time no cambia. Las cinco campañas anteriores se conservan. '
        'Una corrida formal por bloque y variante, sin reintentos automáticos.\n\n'
        +canonical[canonical.index('## Objetivo y alcance acordado'):],encoding='utf-8')
    save('assembly-adaptations.json',{'new_workspace':WORK,
        'dependency_remediation':'Same locked dependencies in private venv and actual private base Python; dual preseal validation and file hashes',
        'resource_policy':'User authorizes current resources; admission 5 GiB waived, original 2 GiB execution reserve preserved; resource-policy.json authoritative for this explicit amendment',
        'clock_configuration':'Authorized temporary WSL pause, 120-second observation, original 1-second monitor, restore at closure, six-hour guardian',
        'host_probe':'Current Windows Python 3.13.2; same GlobalMemoryStatusEx script and user',
        'receipt_path_portability':'Original smoke:urls task, portable frontend-smoke-urls receipt',
        'conservation':'Independent recovery package and explicit Git selection; preserve all prior staged evidence',
        'product_tests_fixtures_load_timing_or_contract_gate_changes':False})
    print('INITIALIZED_AUTHORIZED_CAMPAIGN_R5')

if __name__=='__main__':
    main()
