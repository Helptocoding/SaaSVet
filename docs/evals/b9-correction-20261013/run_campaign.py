"""One fixed Linux campaign, sequential blocks, durable stop, no formal retries."""
import difflib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from prepare_wsl import EVIDENCE,OLD,WORK,TREE,PYTHON,PG,NODE,PNPM,DATA,PORT,SHA,RTK,GIB,save,sha256,resources,environment,integrity
from stage_wsl import host_resources
from awake_status import status as awake_status

BLOCKS=EVIDENCE/'blocks'
BLOCKS.mkdir(exist_ok=True)
REQUIRED=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
    'frontend-build','frontend-test','frontend-smoke-urls','security']
SCENARIOS=['base','blocked_llm','meta_slow','duplicate','saturation']

def validate_clock_control():
    config=json.loads((EVIDENCE/'clock-control.json').read_text())
    process=Path('/proc')/str(config['guard_pid'])/'cmdline'
    if not process.exists() or config['guard_source_linux'].encode() not in process.read_bytes():
        stop('PENDING','clock-control','Clock service guardian unavailable')
    current=subprocess.check_output([str(RTK),'proxy','systemctl','show','systemd-timesyncd.service',
        '--property=ActiveState,UnitFileState'],stdin=subprocess.DEVNULL,text=True)
    if 'ActiveState=inactive' not in current or 'UnitFileState='+config['initial_enabled'] not in current:
        stop('PENDING','clock-control','Approved temporary clock service configuration changed')

class StopCampaign(Exception):
    pass

def stop(state,phase,cause,**details):
    save('STOP.json',dict(state=state,phase=phase,cause=cause,no_rerun=True,**details))
    print(json.dumps({'campaign':state,'phase':phase,'cause':cause}),flush=True)
    raise StopCampaign(cause)

def verify(label,*,require_awake=True):
    validate_clock_control()
    integrity(label)
    dependencies=json.loads((EVIDENCE/'dependency-files.json').read_text())
    changed=[p for p,h in dependencies['files'].items() if not Path(p).is_file() or sha256(Path(p).read_bytes())!=h]
    save('dependency-check-'+label+'.json',{'checked':len(dependencies['files']),'mismatches':changed})
    if changed:
        stop('PENDING',label,'Sealed application dependencies changed',mismatches=changed)

    seal=json.loads((EVIDENCE/'evaluation-seal.json').read_text())
    mismatch=[p for p,h in seal['files'].items() if not Path(p).is_file() or sha256(Path(p).read_bytes())!=h]
    save('seal-check-'+label+'.json',{'checked':len(seal['files']),'mismatches':mismatch})
    if mismatch:
        stop('PENDING',label,'Evaluator/toolchain seal changed',mismatches=mismatch)
    if require_awake:
        awake=awake_status()
        if awake['state']!='ACTIVE_CONFIRMED':
            stop('PENDING',label,'Owned awake request unavailable',awake=awake)

def budget():
    guest=resources()
    host=host_resources()
    return {'guest':guest,'host':host,'ready':guest['physical_available']>=2*GIB and
        host['physical_available']>=2*GIB and guest['disk_available']>=GIB}

def seal():
    if (EVIDENCE/'preflight.json').exists() or (EVIDENCE/'STOP.json').exists():
        raise RuntimeError('Preflight already decided; cannot silently restart campaign')
    assert json.loads((EVIDENCE/'environment-ready.json').read_text())['state']=='READY_FOR_SEAL'
    assert json.loads((EVIDENCE/'interpreter-preflight.json').read_text())['state']=='PASS'
    discovery=json.loads((EVIDENCE/'discovery.json').read_text())
    assert discovery['counts']['directed']==87 and not discovery['missing_directed']
    assert not any(discovery['loader_errors'].values()) and not any(discovery['duplicates'].values())
    # Validate adapter syntax and Django's runner resolution without running a test.
    for p in EVIDENCE.glob('*.py'):
        compile(p.read_text(encoding='utf-8'),str(p),'exec')
    sys.path.insert(0,str(EVIDENCE))
    import recorded_suite
    from django.test.utils import get_runner
    from django.conf import settings
    for name in ('RecordedB0Runner','RecordedB3Runner','RecordedB4Runner','RecordedB5Runner','RecordedFullRunner'):
        resolved=get_runner(settings,'recorded_suite.'+name)
        assert resolved is getattr(recorded_suite,name)
    diff=''.join(difflib.unified_diff((OLD/'recorded_suite.py').read_text().splitlines(True),
        (EVIDENCE/'recorded_suite.py').read_text().splitlines(True),fromfile='previous-prepared-adapter',tofile='linux-receipt-adapter'))
    (EVIDENCE/'receipt-adapter.diff').write_text(diff,encoding='utf-8')
    save('adapter-validation.json',{'syntax':'PASS','django_runner_resolution':'PASS',
        'candidate_runner_sources_unchanged':True,'critical_guards_preserved_by_super':True,
        'change':'Django receives an import path; record subtest failures without changing assertions',
        'application_tests_executed':False})
    paths=[*EVIDENCE.glob('*.py'),EVIDENCE/'scope-manifest.json',EVIDENCE/'PLAN.md',
        EVIDENCE/'candidate-sources.json',EVIDENCE/'assembly.json',EVIDENCE/'authorization.json',
        EVIDENCE/'assembly-adaptations.json',EVIDENCE/'candidate.json',EVIDENCE/'correction.diff',
        EVIDENCE/'resource-policy.json',EVIDENCE/'resource-observer-control.json',
        EVIDENCE/'adapter-lineage.json',EVIDENCE/'clock-control.json',
        EVIDENCE/'adapter-lineage-final.json',EVIDENCE/'preseal-resource-observer.json',
        EVIDENCE/'awake-request/control.json',EVIDENCE/'preseal-awake-validation.json',
        EVIDENCE/'preseal-sleep-event-messages.json',
        EVIDENCE/'preparation-resumption.json',EVIDENCE/'preparation-history/REPORT-before-resumption.md',
        EVIDENCE/'preseal-preparation-cleanup.json',EVIDENCE/'preseal-environment-amendments.json',
        EVIDENCE/'dependency-files.json',EVIDENCE/'interpreter-preflight.json',EVIDENCE/'base-python-environment.json',
        *[p for p in (EVIDENCE/'clock-diagnostics').rglob('*') if p.is_file()],
        Path(json.loads((EVIDENCE/'clock-control.json').read_text())['guard_source_linux']),
        Path(json.loads((EVIDENCE/'clock-control.json').read_text())['guard_rtk_linux']),
        EVIDENCE/'effective-configuration.json',EVIDENCE/'toolchain.json',EVIDENCE/'python-environment.json',
        EVIDENCE/'profile-compatibility.json',*EVIDENCE.glob('*-selected.json'),
        PYTHON,Path(sys._base_executable),NODE,PNPM,WORK/'gitleaks/gitleaks',
        *PG.glob('*'),DATA/'postgresql.conf',DATA/'pg_hba.conf']
    paths=[p for p in paths if p.is_file()]
    save('evaluation-seal.json',{'candidate_sha':SHA,'files':{str(p):sha256(p.read_bytes()) for p in paths},
        'candidate_manifest_sha256':sha256((EVIDENCE/'candidate-sources.json').read_bytes())})
    verify('preflight')
    observation=budget()
    save('preflight.json',{'state':'PASS' if observation['ready'] else 'PENDING',
        'candidate_sha':SHA,'exact_git_files':3332,'directed_ids':87,'full_ids':discovery['counts']['full'],
        'resource_budget':{'suite_estimate_not_reserved':3*GIB,'admission_floor':2*GIB,'memory_reserve':2*GIB,'prior_5_gib_admission_waived_by_user':True,'backing_disk_reserve':GIB},
        'resources':observation,'no_formal_application_tests_yet':True,'focused_verification_recorded':True,
        'formal_runs_per_block_max':1,'profile_runs_per_scenario_max':1,
        'host_clock_configuration_unchanged':True,'runtime_and_lock_changes':False,'resource_policy':'USER_AMENDED_ADMISSION_HEADROOM'})
    if not observation['ready']:
        stop('PENDING','preflight','Insufficient resources for frozen budget',resources=observation)
    print('PREFLIGHT_PASS',flush=True)

def execute(label,args,*,cwd=None,env=None,advisory=False):
    if (EVIDENCE/'STOP.json').exists():
        raise StopCampaign('Durable stop present')
    if json.loads((EVIDENCE/'preflight.json').read_text())['state']!='PASS':
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
    invalid=None;rows=[];last_wall=wall;last_host=observation['host'];last_host_check=start
    last_awake=awake_status()
    print('BLOCK_START '+label,flush=True)
    with (BLOCKS/(label+'.command.log')).open('wb') as stream:
        proc=subprocess.Popen(argv,cwd=cwd or TREE/'backend',env=config,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        data['pid']=proc.pid
        while proc.poll() is None:
            now,now_wall=time.monotonic(),time.time()
            guest=resources()
            skew=(now_wall-wall)-(now-start)
            if now_wall<last_wall or abs(skew)>1:
                invalid='Clock discontinuity'
            elif now-last_host_check>=5:
                try:
                    last_host=host_resources()
                except (OSError,ValueError,KeyError,RuntimeError) as exc:
                    invalid='Host resource observer unavailable: '+type(exc).__name__+': '+str(exc)
                last_awake=awake_status();last_host_check=now
            if not invalid and last_awake['state']!='ACTIVE_CONFIRMED':
                invalid='Owned awake request unavailable: '+last_awake.get('reason','not confirmed')
            if not invalid and min(guest['physical_available'],last_host['physical_available'])<2*GIB:
                invalid='Memory reserve exhausted'
            elif not invalid and guest['disk_available']<GIB:
                invalid='Backing disk reserve exhausted'
            rows.append({'elapsed_seconds':now-start,'wall_minus_monotonic_seconds':skew,'guest':guest,'host':last_host,'awake':last_awake})
            if invalid:
                os.killpg(proc.pid,signal.SIGTERM)
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL)
                break
            last_wall=now_wall
            time.sleep(1)
        code=proc.wait()
    try:
        final_host=host_resources()
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        final_host={'state':'UNAVAILABLE','reason':str(exc)}
        if not invalid:invalid='Host resource observer unavailable after block'
    final_awake=awake_status()
    if not invalid and final_awake['state']!='ACTIVE_CONFIRMED':
        invalid='Owned awake request unavailable after block'
    data.update(state='COMPLETED',exit_code=code,seconds=time.monotonic()-start,
        invalidating_incident=invalid,resources_after={'guest':resources(),'host':final_host,'awake':final_awake})
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
    data=json.loads(p.read_text())
    expected=json.loads((EVIDENCE/(label+'-selected.json')).read_text())
    if sorted(data['test_ids'])!=expected or data['tests']!=len(expected):
        stop('PENDING',label,'Suite inventory/denominator incomplete',exit_code=code)
    if data['failures'] or data['errors']:
        gate(label,'NONPASS_REQUIRES_CLASSIFICATION',receipt=data)
        stop('PENDING_CLASSIFICATION',label,'Suite reports failures/errors; classify validity from retained traces',failed_ids=data['failed_ids'])
    skips=data.get('skips',[])
    if label!='full' and (skips or data.get('xfail') or data.get('xpass')):
        stop('PENDING',label,'Required suite has skips/xfail/xpass')
    if label=='full':
        required=set(json.loads((EVIDENCE/'directed-selected.json').read_text()))
        for kind in ('b0','b3','b4','b5'):
            required.update(json.loads((EVIDENCE/(kind+'-selected.json')).read_text()))
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

def run_all():
    seal()
    code=execute('directed',[PYTHON,'-B','-m','apps.agent.tests.run_b9a_acceptance','--suite','targeted',
        '--database','test_b8b_b9i_directed','--ids-file',EVIDENCE/'directed-selected.json','--output',BLOCKS/'directed'])
    check_suite('directed',code)
    create_db('test_b9i_checks')
    for label,args in [('django-check',['check']),('migration-drift',['makemigrations','--check','--dry-run']),
        ('migrate',['migrate','--no-input']),('billing-schema',['audit_billing_schema','--json'])]:
        code=execute(label,[PYTHON,'-B','manage.py',*args],env={'DATABASE_URL':f'postgresql://b9e@127.0.0.1:{PORT}/test_b9i_checks'})
        if code: stop('PENDING_CLASSIFICATION',label,'Blocking command nonzero; inspect validity before decision',exit_code=code)
        gate(label)
    for kind in ('b0','b3','b4','b5','full'):
        code=execute(kind,[PYTHON,'-B',EVIDENCE/'recorded_suite.py',kind,'test_b9i_'+kind],
            env={'B9I_SUITE':kind,'B9I_ID_JOURNAL':str(BLOCKS/(kind+'.ids.jsonl')),
                'B9I_SUITE_RECEIPT':str(BLOCKS/(kind+'.results.json'))})
        check_suite(kind,code)
    for task in ('build','test','lint','smoke:urls'):
        label='frontend-'+task.replace(':','-')
        args=[NODE,PNPM,'run',task]
        if task=='test':args+=['--reporter=default','--reporter=json','--outputFile='+str(BLOCKS/'frontend-tests.json')]
        code=execute(label,args,cwd=TREE/'frontend',advisory=task=='lint')
        if code and task!='lint':stop('PENDING_CLASSIFICATION',label,'Frontend blocking command nonzero',exit_code=code)
        gate(label,'ADVISORY_NONZERO' if code else 'PASS',exit_code=code)
    code=execute('security',[PYTHON,'-B',EVIDENCE/'scan_security.py'],cwd=WORK/'history')
    if code:stop('PENDING_CLASSIFICATION','security','Gitleaks nonzero; distinguish findings from scanner error',exit_code=code)
    gate('security')
    for label,args,cwd in [('pip-audit',[WORK/'audit-venv/bin/pip-audit','-r',TREE/'backend/requirements.lock','--format=json','--output',BLOCKS/'pip-audit.json'],TREE),
        ('pnpm-audit',[NODE,PNPM,'audit','--json'],TREE/'frontend')]:
        code=execute(label,args,cwd=cwd,advisory=True)
        gate(label,'ADVISORY_NONZERO' if code else 'PASS',exit_code=code)
    if any(json.loads((BLOCKS/(label+'.gate.json')).read_text())['state']!='PASS' for label in REQUIRED):
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
        result=json.loads(path.read_text())
        if result.get('smoke_only') is not False or result.get('warmup_seconds')!=30 or result.get('measurement_seconds')!=300 or not result.get('gates'):
            stop('PENDING',label,'PROFILE contract metadata invalid')
        if result.get('technical_pass') is not True or not all(value is True for value in result['gates'].values()):
            gate(label,'FAIL',gates=result['gates']);stop('FAIL',label,'PROFILE applicable gate violated',gates=result['gates'])
        gate(label,gates=result['gates'])
    save('technical-completion.json',{'state':'PASS','candidate_sha':SHA,'activation':'PENDING_ACTIVATION_REQUIREMENTS'})
    print('TECHNICAL_CAMPAIGN_PASS',flush=True)

if __name__=='__main__':
    try:run_all()
    except StopCampaign:raise SystemExit(2)
    except Exception as exc:
        save('controller-incident.json',{'type':type(exc).__name__,'message':str(exc)})
        if not (EVIDENCE/'STOP.json').exists():save('STOP.json',{'state':'PENDING','phase':'controller','cause':str(exc),'no_rerun':True})
        raise
