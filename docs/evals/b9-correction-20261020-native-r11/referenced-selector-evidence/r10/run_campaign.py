"""One fixed Windows campaign, sequential blocks, durable stop, no formal retries."""
import difflib
import json
from pathlib import Path
import subprocess
import sys
import time
from native_support import EVIDENCE,REPO,OLD,WORK,TREE,PYTHON,PG,NODE,PNPM,DATA,PORT,SHA,RTK,GIB,save,sha256,resources,environment,integrity
from awake_status import status as awake_status
from composite_evidence import is_reused, read_block, provenance, validate_references, validate_current_inputs

BLOCKS=EVIDENCE/'blocks'
BLOCKS.mkdir(exist_ok=True)
REQUIRED=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
    'frontend-build','frontend-test','frontend-smoke-urls','security']
SCENARIOS=['base','blocked_llm','meta_slow','duplicate','saturation']

def validate_clock_control():
    observation=json.loads((EVIDENCE/'clock-preflight.json').read_text(encoding='utf-8'))
    skew=observation.get('max_absolute_wall_minus_monotonic_seconds')
    if observation.get('state')!='PASS' or not isinstance(skew,(int,float)) or isinstance(skew,bool) or not 0<=skew<=1:
        stop('PENDING','clock-preflight','Native Windows clock observation invalid')

class StopCampaign(Exception):
    pass

def stop(state,phase,cause,**details):
    save('STOP.json',dict(state=state,phase=phase,cause=cause,no_rerun=True,**details))
    print(json.dumps({'campaign':state,'phase':phase,'cause':cause}),flush=True)
    raise StopCampaign(cause)

def verify(label,*,require_awake=True):
    validate_clock_control()
    validate_references()
    from frontend_resumption import validate_frontend_references
    validate_frontend_references()
    integrity(label)
    dependencies=json.loads((EVIDENCE/'dependency-files.json').read_text(encoding='utf-8'))
    changed=[p for p,h in dependencies['files'].items() if not Path(p).is_file() or sha256(Path(p).read_bytes())!=h]
    save('dependency-check-'+label+'.json',{'checked':len(dependencies['files']),'mismatches':changed})
    if changed:
        stop('PENDING',label,'Sealed application dependencies changed',mismatches=changed)
    seal=json.loads((EVIDENCE/'evaluation-seal.json').read_text(encoding='utf-8'))
    mismatch=[p for p,h in seal['files'].items() if not Path(p).is_file() or sha256(Path(p).read_bytes())!=h]
    save('seal-check-'+label+'.json',{'checked':len(seal['files']),'mismatches':mismatch})
    if mismatch:
        stop('PENDING',label,'Evaluator/toolchain seal changed',mismatches=mismatch)
    if require_awake:
        awake=awake_status()
        if awake['state']!='ACTIVE_CONFIRMED':
            stop('PENDING',label,'Owned awake request unavailable',awake=awake)

def budget():
    host=resources()
    return {'host':host,'ready':host['physical_available']>=2*GIB and host['disk_available']>=GIB}

def seal():
    if (EVIDENCE/'preflight.json').exists() or (EVIDENCE/'STOP.json').exists():
        raise RuntimeError('Preflight already decided; cannot silently restart campaign')
    for name, state in [('environment-ready.json','READY_FOR_SEAL'),
        ('interpreter-preflight.json','PASS'),('native-preflight.json','PASS'),
        ('launcher-validation.json','PASS'),('backend-reference-validation.json','PASS'),
        ('frontend-resumption-validation.json','PASS'),
        ('diagnostics/preserved-contract-checks.json','PASS'),
        ('diagnostics/composite-validator-checks.json','PASS_VALIDATOR_CHECKS')]:
        assert json.loads((EVIDENCE/name).read_text(encoding='utf-8'))['state']==state, name
    validate_clock_control()
    from full_partition import validate_partition
    validate_partition()
    validate_current_inputs()
    validate_references()
    from frontend_resumption import validate_frontend_references
    validate_frontend_references()
    for path in EVIDENCE.glob('*.py'):
        compile(path.read_text(encoding='utf-8'),str(path),'exec')
    adapter_diff=''.join(difflib.unified_diff(
        (EVIDENCE.with_name('b9-correction-20261020-native-r9')/'recorded_suite.py').read_text(encoding='utf-8').splitlines(True),
        (EVIDENCE/'recorded_suite.py').read_text(encoding='utf-8').splitlines(True),
        fromfile='native-r9/recorded_suite.py',tofile='native-r10/recorded_suite.py'))
    (EVIDENCE/'receipt-adapter.diff').write_text(adapter_diff,encoding='utf-8',newline='\n')
    save('adapter-validation.json',{'syntax':'PASS','django_runner_resolution':'PASS',
        'backend_application_tests_executed':False,'backend_results_origin':'REFERENCED_COMPLETED_R9',
        'change':'Only one exactly filtered frontend case; eight original execution/partition functions preserved',
        'all_original_guards_preserved':True})
    required_names=[
        'frontend-resumption-authorization.json','frontend-equivalence.json','frontend-proposal-analysis.json',
        'frontend-correction.diff','completed-reference-manifest.json','backend-reference-validation.json',
        'frontend-resumption-manifest.json','frontend-resumption-validation.json',
        'frontend-retained-pass-selected.json','frontend-remainder-selected.json','frontend-full-selected.json',
        'authorization.json','candidate.json','correction.diff','resource-policy.json','scope-manifest.json',
        'PLAN.md','assembly.json','candidate-sources.json','toolchain.json','python-environment.json',
        'dependency-files.json','interpreter-preflight.json','private-python-copy.json','frontend-layout.json',
        'security-history.json','install-cache-retirement.json','operational-lifetime-amendment.json',
        'runtime-handoff-supplement.json','prepared-runtime-references.json','resumption.json',
        'composite-amendment.json','pre-patch-current-integrity.json','previous-completion-integrity-reference.json',
        'diagnostics/preserved-contract-checks.json','diagnostics/composite-validator-checks.json',
        'diagnostics/frontend-fixture-ast-check.json','diagnostics/frontend-fixture-original.jsx',
        'diagnostics/verify_frontend_equivalence.py','diagnostics/verify_frontend_equivalence.cjs',
        'diagnostics/close_acceptance.py','launcher-validation.json','downloads.json','audit-toolchain.json',
        'postgresql-preflight.json','profile-compatibility.json','campaign-adaptation.json',
        'effective-configuration.json','code-selection.json','full-partition-contract.json','full-partition.json',
        'awake-request/control.json','clock-preflight.json','native-preflight.json','environment-ready.json',
        'discovery.json','receipt-adapter.diff','adapter-validation.json']
    paths=[*EVIDENCE.glob('*.py'),*[EVIDENCE/name for name in required_names],
        *EVIDENCE.glob('*-selected.json'),RTK,PYTHON,Path(sys._base_executable),NODE,PNPM,
        WORK/'gitleaks/gitleaks.exe',*[p for p in PG.glob('*') if p.suffix.lower() in ('.exe','.dll')],
        DATA/'postgresql.conf',DATA/'pg_hba.conf']
    for name in ('prior-focused-verification.json','base-python-environment.json'):
        if (EVIDENCE/name).exists():paths.append(EVIDENCE/name)
    paths=list(dict.fromkeys(paths))
    missing=[str(p) for p in paths if not p.is_file()]
    if missing:stop('PENDING','seal','Required native evaluator/toolchain inputs absent',missing=missing)
    save('evaluation-seal.json',{'candidate_sha':SHA,'platform':'windows-native',
        'files':{str(p):sha256(p.read_bytes()) for p in paths},
        'candidate_manifest_sha256':sha256((EVIDENCE/'candidate-sources.json').read_bytes())})
    verify('preflight')
    observation=budget()
    save('preflight.json',{'state':'PASS' if observation['ready'] else 'PENDING',
        'candidate_sha':SHA,'exact_git_files':3332,'retained_backend_ids':3331,
        'retained_frontend_PASS':354,'new_frontend_cases':1,
        'resource_budget':{'admission_floor':2*GIB,'memory_reserve':2*GIB,
            'prior_5_gib_admission_waived_by_user':True,'backing_disk_reserve':GIB},
        'resources':observation,'formal_runs_per_new_block_max':1,'profile_runs_per_scenario_max':1,
        'platform':'windows-native','host_clock_configuration_unchanged':True,
        'runtime_and_lock_changes':False,'evidence_mode':'COMPOSITE_ACCEPTANCE',
        'continuous_campaign_claimed':False,'historical_backend_limit_accepted':True})
    if not observation['ready']:
        stop('PENDING','preflight','Insufficient resources for frozen budget',resources=observation)
    print('PREFLIGHT_PASS',flush=True)

def execute(label,args,*,cwd=None,env=None,advisory=False):
    if (EVIDENCE/'STOP.json').exists():
        raise StopCampaign('Durable stop present')
    if json.loads((EVIDENCE/'preflight.json').read_text(encoding='utf-8'))['state']!='PASS':
        raise RuntimeError('Preflight not passed')
    receipt=BLOCKS/(label+'.command.json')
    if receipt.exists():
        raise RuntimeError('Refusing formal rerun: '+label)
    verify('before-'+label)
    observation=budget()
    if not observation['ready']:
        stop('PENDING',label,'Resource margin unavailable before block',resources=observation,block_executed=False)
    argv=[str(RTK),'proxy',*map(str,args)]
    config=environment();config.update(env or {})
    start,wall=time.monotonic(),time.time()
    data={'label':label,'candidate_sha':SHA,'argv':argv,'cwd':str(cwd or TREE/'backend'),
        'formal_run_number':1,'advisory':advisory,'state':'RUNNING','resources_before':observation}
    receipt.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    invalid=None;rows=[];last_wall=wall;last_host=observation['host'];last_awake_check=start
    last_awake=awake_status()
    print('BLOCK_START '+label,flush=True)
    with (BLOCKS/(label+'.command.log')).open('wb') as stream:
        proc=subprocess.Popen(argv,cwd=cwd or TREE/'backend',env=config,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        data['pid']=proc.pid
        data['wrapper_pid']=proc.pid
        while proc.poll() is None:
            now,now_wall=time.monotonic(),time.time()
            try:
                last_host=resources()
            except (OSError,ValueError,KeyError,RuntimeError) as exc:
                invalid='Native resource observer unavailable: '+type(exc).__name__+': '+str(exc)
            skew=(now_wall-wall)-(now-start)
            if now_wall<last_wall or abs(skew)>1:
                invalid='Clock discontinuity'
            if now-last_awake_check>=5:
                last_awake=awake_status();last_awake_check=now
            if not invalid and last_awake['state']!='ACTIVE_CONFIRMED':
                invalid='Owned awake request unavailable: '+last_awake.get('reason','not confirmed')
            if not invalid and last_host['physical_available']<2*GIB:
                invalid='Memory reserve exhausted'
            elif not invalid and last_host['disk_available']<GIB:
                invalid='Backing disk reserve exhausted'
            rows.append({'elapsed_seconds':now-start,'wall_minus_monotonic_seconds':skew,
                         'host':last_host,'awake':last_awake})
            if invalid:
                kill_argv=[str(RTK),'proxy','taskkill.exe','/PID',str(proc.pid),'/T','/F']
                killed=subprocess.run(kill_argv,env=config,stdin=subprocess.DEVNULL,
                    stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
                data['owned_tree_termination']={'argv':kill_argv,'exit_code':killed.returncode,
                    'wrapper_pid':proc.pid,'foreign_processes_targeted':False}
                proc.wait(timeout=30)
                break
            last_wall=now_wall
            time.sleep(1)
        code=proc.wait()
    try:
        final_host=resources()
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        final_host={'state':'UNAVAILABLE','reason':str(exc)}
        if not invalid:invalid='Native resource observer unavailable after block'
    final_awake=awake_status()
    if not invalid and final_awake['state']!='ACTIVE_CONFIRMED':
        invalid='Owned awake request unavailable after block'
    data.update(state='COMPLETED',exit_code=code,seconds=time.monotonic()-start,
        invalidating_incident=invalid,resources_after={'host':final_host,'awake':final_awake})
    receipt.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    save('monitor-'+label+'.json',rows)
    verify('after-'+label,require_awake=not bool(invalid))
    print('BLOCK_END '+label+' exit='+str(code),flush=True)
    if invalid:
        stop('PENDING',label,invalid)
    return code

def gate(label,state='PASS',**details):
    (BLOCKS/(label+'.gate.json')).write_text(json.dumps(dict(label=label,state=state,**details),indent=2)+'\n',encoding='utf-8')

def check_suite(label,code):
    p=BLOCKS/(label+'.results.json')
    if not p.exists():
        stop('PENDING',label,'Suite receipt absent',exit_code=code)
    data=json.loads(p.read_text(encoding='utf-8'))
    expected=json.loads((EVIDENCE/(label+'-selected.json')).read_text(encoding='utf-8'))
    if sorted(data['test_ids'])!=expected or data['tests']!=len(expected):
        stop('PENDING',label,'Suite inventory/denominator incomplete',exit_code=code)
    if data['failures'] or data['errors']:
        gate(label,'NONPASS_REQUIRES_CLASSIFICATION',receipt=data)
        stop('PENDING_CLASSIFICATION',label,'Suite reports failures/errors; classify validity from retained traces',failed_ids=data['failed_ids'])
    skips=data.get('skips',[])
    full_family = label == 'full' or label.startswith('full-')
    if not full_family and (skips or data.get('xfail') or data.get('xpass')):
        stop('PENDING',label,'Required suite has skips/xfail/xpass')
    if full_family:
        required=set(json.loads((EVIDENCE/'directed-selected.json').read_text(encoding='utf-8')))
        for kind in ('b0','b3','b4','b5'):
            required.update(json.loads((EVIDENCE/(kind+'-selected.json')).read_text(encoding='utf-8')))
        if any(row['id'] in required for row in skips):
            stop('PENDING',label,'Required ID skipped in full suite')
    if code:
        stop('PENDING',label,'Nonzero runner guard; no assertion failure recorded',exit_code=code)
    gate(label,tests=data['tests'],skips=skips)

def create_db(name):
    assert name.startswith('test_b9i_')
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))

def reuse_block(label):
    if not is_reused(label):
        return False
    validate_references()
    assert read_block(label)['state']=='PASS'
    save('referenced-block-'+label+'.json',{'state':'REFERENCED_PASS',
        'label':label,'provenance':provenance(label),'application_tests_executed_here':False,
        'source_receipts_copied_as_current':False})
    print('BLOCK_REFERENCED '+label,flush=True)
    return True

def run_all():
    seal()
    for label in REQUIRED:
        if label in ('frontend-test','frontend-smoke-urls','security'):
            continue
        assert read_block(label)['state']=='PASS',label
        save('referenced-block-'+label+'.json',{'state':'REFERENCED_PASS','label':label,
            'provenance':provenance(label),'application_tests_executed_here':False})
        print('BLOCK_REFERENCED '+label,flush=True)
    code=execute('frontend-test-remainder',[PYTHON,'-B',EVIDENCE/'frontend_resumption.py','run'],cwd=TREE/'frontend')
    if code:stop('PENDING_CLASSIFICATION','frontend-test-remainder','Selected frontend case nonzero; preserve traces',exit_code=code)
    code=execute('frontend-test-assemble',[PYTHON,'-B',EVIDENCE/'frontend_resumption.py','assemble'],cwd=REPO)
    if code:stop('PENDING','frontend-test-assemble','Frontend case evidence assembly invalid',exit_code=code)
    logical=json.loads((BLOCKS/'frontend-tests.json').read_text(encoding='utf-8'))
    assert logical['logical_aggregate'] is True
    gate('frontend-test',tests=355,retained_PASS=354,new_PASS=1,
        command_reference='frontend-test-assemble.command.json',
        historical_command_exit_1_preserved=True)
    for task in ('lint','smoke:urls'):
        label='frontend-'+task.replace(':','-')
        args=[NODE,PNPM,'run',task]
        if task=='test':args+=['--reporter=default','--reporter=json','--outputFile='+str(BLOCKS/'frontend-tests.json')]
        code=execute(label,args,cwd=TREE/'frontend',advisory=task=='lint')
        if code and task!='lint':stop('PENDING_CLASSIFICATION',label,'Frontend blocking command nonzero',exit_code=code)
        gate(label,'ADVISORY_NONZERO' if code else 'PASS',exit_code=code)
    code=execute('security',[PYTHON,'-B',EVIDENCE/'scan_security.py'],cwd=REPO)
    if code:stop('PENDING_CLASSIFICATION','security','Gitleaks nonzero; distinguish findings from scanner error',exit_code=code)
    gate('security')
    for label,args,cwd in [('pip-audit',[WORK/'audit-venv/Scripts/python.exe','-m','pip_audit','-r',TREE/'backend/requirements.lock','--format=json','--output',BLOCKS/'pip-audit.json'],TREE),
        ('pnpm-audit',[NODE,PNPM,'audit','--json'],TREE/'frontend')]:
        code=execute(label,args,cwd=cwd,advisory=True)
        gate(label,'ADVISORY_NONZERO' if code else 'PASS',exit_code=code)
    if any(read_block(label)['state']!='PASS' for label in REQUIRED):
        stop('PENDING','profile','Earlier blocking gate incomplete')
    for scenario in SCENARIOS:
        name='test_b9i_profile_'+scenario;create_db(name)
        config={'DATABASE_URL':f'postgresql://b9e@127.0.0.1:{PORT}/{name}'}
        label='profile-'+scenario
        code=execute(label+'-migrate',[PYTHON,'-B','manage.py','migrate','--no-input'],env=config)
        if code:stop('PENDING',label,'PROFILE database migration failed',exit_code=code)
        code=execute(label,[PYTHON,'-B','-m','apps.agent.tests.b9e_profile','--scenario',scenario,'--output',BLOCKS/(label+'.json')],env=config)
        path=BLOCKS/(label+'.json')
        if code or not path.exists():stop('PENDING',label,'PROFILE receipt missing or interrupted',exit_code=code)
        result=json.loads(path.read_text(encoding='utf-8'))
        if result.get('smoke_only') is not False or result.get('warmup_seconds')!=30 or result.get('measurement_seconds')!=300 or not result.get('gates'):
            stop('PENDING',label,'PROFILE contract metadata invalid')
        if result.get('technical_pass') is not True or not all(value is True for value in result['gates'].values()):
            gate(label,'FAIL',gates=result['gates']);stop('FAIL',label,'PROFILE applicable gate violated',gates=result['gates'])
        gate(label,gates=result['gates'])
    save('technical-completion.json',{'state':'PASS','candidate_sha':SHA,
        'evidence_mode':'COMPOSITE_ACCEPTANCE','continuous_campaign_claimed':False,
        'accepted_historical_evidence_limitation':True,
        'acceptance_label':'PASS_BAJO_CONDICION_DE_EVIDENCIA_ENMENDADA',
        'activation':'PENDING_ACTIVATION_REQUIREMENTS'})
    print('TECHNICAL_COMPOSITE_ACCEPTANCE_PASS',flush=True)

if __name__=='__main__':
    try:run_all()
    except StopCampaign:raise SystemExit(2)
    except Exception as exc:
        save('controller-incident.json',{'type':type(exc).__name__,'message':str(exc)})
        if not (EVIDENCE/'STOP.json').exists():save('STOP.json',{'state':'PENDING','phase':'controller','cause':str(exc),'no_rerun':True})
        raise
