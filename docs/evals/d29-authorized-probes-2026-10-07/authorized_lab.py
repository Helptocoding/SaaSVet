"""Owned local laboratory for fixed dependent jobs and the final physical matrix."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(r'C:/Users/LAP/Desktop/VeterinariaSaaS')
OUT = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07'
BASE_DIR = ROOT / 'docs/evals/d29-r102-base-2026-10-07'
BASE = '825db75df68bf076929fa787e77beefe96803350'
BIN = Path(tempfile.gettempdir()) / 'vet-b8b-pg16-bin/pgsql/bin'
PREFIX = 'vet-d29-authorized-20261007-'
PACKAGE = 'apps.agent.tests.scheduling_characterization.'
ROLES = ('planner_1', 'planner_2', 'sender')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def integrity():
    prior = read(BASE_DIR / 'final-integrity.json')
    protected = prior['protected_sources']
    mismatches = [p for p,h in protected.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
    historical = {}
    errors = []
    for name in ('d29-physical-2026-10-06', 'd29-frontiers-2026-10-07', 'd29-r102-base-2026-10-07'):
        directory = ROOT / 'docs/evals' / name
        index = read(directory / 'artifact-index.json')
        historical[name] = dict(count=len(index), index_sha256=sha(directory/'artifact-index.json'))
        for p,entry in index.items():
            if not (directory/p).is_file() or sha(directory/p)!=entry['sha256']:
                errors.append(name+'/'+p)
    head = subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'], cwd=ROOT).decode().strip()
    value = dict(baseline=BASE, head=head, protected_sources=protected,
        previous_evidence=historical, source_mismatches=mismatches, evidence_mismatches=errors,
        intact=head==BASE and not mismatches and not errors)
    if not value['intact']:
        raise RuntimeError('Protected baseline or accepted receipts changed')
    return value


def connect(cfg, name='postgres'):
    return psycopg.connect(dbname=name,user=cfg['USER'],password=cfg['PASSWORD'],host=cfg['HOST'],
        port=cfg['PORT'],autocommit=True,connect_timeout=10)


def environment(cfg, copy):
    return dict(os.environ, SECRET_KEY='isolated-d29-dependent-test-key', DJANGO_SETTINGS_MODULE='config.settings',
        DISABLE_SENTRY='True',SENTRY_DSN='',REDIS_URL='',DISCORD_WEBHOOK_URL='',HEALTHCHECK_AGENT_WORKER_URL='',
        HEALTHCHECK_AGENT_SENDER_URL='',PYTHONDONTWRITEBYTECODE='1',D29_ARCHIVE_REPOSITORY=str(ROOT),
        DATABASE_URL='postgresql://'+cfg['USER']+':'+quote(cfg['PASSWORD'])+'@127.0.0.1:'+cfg['PORT']+'/'+cfg['NAME'],
        B3_TEST_DATABASE=json.dumps(cfg),PYTHONPATH=str(copy/'backend'))


def initialize():
    write(OUT/'initial-integrity.json', integrity())
    task = Path(tempfile.mkdtemp(prefix=PREFIX)).resolve()
    archive = task/'baseline.zip'
    with archive.open('xb') as stream:
        subprocess.run(['rtk','proxy','git','archive','--format=zip',BASE],cwd=ROOT,stdout=stream,check=True)
    copy = task/'baseline'
    with zipfile.ZipFile(archive) as z:
        z.extractall(copy)
    paths = list((ROOT/'backend/apps/agent/tests/scheduling_characterization').glob('*.py'))
    paths += [ROOT/'backend/apps/agent/tests'/n for n in ('test_scheduling_characterization.py','test_scheduling_controller.py','test_d29_physical.py','test_d29_frontiers.py')]
    paths += [ROOT/'docs/decisions/2026-10-05-scheduling-characterization-protocol.json']
    hashes = {}
    for source in paths:
        rel = source.relative_to(ROOT)
        for target in (copy/rel,OUT/'frozen-sources'/rel):
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
        hashes[rel.as_posix()]=sha(source)
    write(OUT/'frozen-sources.json', hashes)
    frozen = task/'orchestration'
    frozen.mkdir()
    orchestration = {}
    for source in (OUT/'orchestration').glob('*.py'):
        shutil.copy2(source,frozen/source.name)
        orchestration[source.name]=sha(source)
    write(OUT/'orchestration-seal.json',orchestration)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port=str(sock.getsockname()[1])
    cfg=dict(ENGINE='django.db.backends.postgresql',NAME='test_d29_dependent_template',USER='d29_dependent',
        PASSWORD=secrets.token_urlsafe(32),HOST='127.0.0.1',PORT=port)
    data=task/'pgdata'
    write(task/'session.json',dict(config=cfg,copy=str(copy),data=str(data),orchestration=str(frozen)))
    write(OUT/'environment.json',dict(baseline=BASE,task=str(task),host=cfg['HOST'],port=port,template=cfg['NAME'],
        runtime_scope='PRIVATE_TEMP_LAB_ONLY',persistent_configuration_changed=False))
    pw=task/'init-password'
    pw.write_text(cfg['PASSWORD'],encoding='utf-8')
    with (OUT/'initdb.log').open('x',encoding='utf-8') as log:
        try:
            subprocess.run(['rtk','proxy',str(BIN/'initdb.exe'),'-D',str(data),'-U',cfg['USER'],'--pwfile',str(pw),
                '--auth-host=scram-sha-256','--auth-local=scram-sha-256','--encoding=UTF8','--locale=C'],stdout=log,stderr=subprocess.STDOUT,check=True)
        finally:
            pw.unlink(missing_ok=True)
    start=task/'start.ps1'
    start.write_text("$proc = Start-Process -FilePath '"+str(BIN/'postgres.exe')+"' -ArgumentList @('-D','"+str(data)+
        "','-h','127.0.0.1','-p','"+port+"') -WindowStyle Hidden -RedirectStandardOutput '"+str(task/'pg.stdout')+
        "' -RedirectStandardError '"+str(task/'pg.stderr')+"' -PassThru\n$proc.Id | Set-Content -LiteralPath '"+str(task/'pg.pid')+"'\n",encoding='utf-8')
    subprocess.Popen(['rtk','proxy','powershell','-NoProfile','-File',str(start)],stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    end=time.monotonic()+60
    while True:
        try:
            with connect(cfg) as p:
                p.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cfg['NAME'])))
            break
        except psycopg.OperationalError:
            if time.monotonic()>=end:
                raise
            time.sleep(.2)
    with (OUT/'schema.log').open('x',encoding='utf-8') as log:
        subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8','manage.py','migrate','--noinput'],
            cwd=copy/'backend',env=environment(cfg,copy),stdout=log,stderr=subprocess.STDOUT,check=True)
    with connect(cfg,cfg['NAME']) as p:
        p.execute('TRUNCATE organizations_organization RESTART IDENTITY CASCADE')
        durability=p.execute("SELECT current_setting('fsync'),current_setting('synchronous_commit')").fetchone()
        version=p.execute('SELECT version()').fetchone()[0]
    if durability!=('on','on'):
        raise RuntimeError('Durability changed')
    write(OUT/'database-provenance.json',dict(postgres_version=version,fsync=durability[0],synchronous_commit=durability[1]))
    print('Private durable lab ready; accepted base preserved; no calibration executed',flush=True)


def session():
    task=Path(read(OUT/'environment.json')['task'])
    return task,read(task/'session.json')


def make_job(case,variant,run_id):
    base=read(BASE_DIR/'confirmed-base-receipt.json')
    params=base['configuration']['parameters']
    rates=base['confirmed_base']['rates']
    job=dict(schema='d29-fixed-accreditation-job-v1',run_id=run_id,baseline=BASE,case_id=case,variant=variant,
        phase='ACCREDITATION_SCENARIO',source_hashes={Path(p).name:h for p,h in read(OUT/'frozen-sources.json').items() if '/scheduling_characterization/' in p},
        offered_rates_per_minute=[sum(rates)*2/3,sum(rates)/3] if case=='R1-03' else rates,
        confirmed_base_rates=rates,confirmed_base_reference=dict(path=str(BASE_DIR/'confirmed-base-receipt.json'),sha256=sha(BASE_DIR/'confirmed-base-receipt.json')),
        organization_count=2,conversations_per_org=params['conversations_per_org'],offer_seconds=params['screen_seconds'],
        followup_seconds=params['followup_seconds'],burst_multiplier=params['burst_multiplier'],burst_seconds=params['burst_seconds'],
        slow_multiplier=params['slow_multiplier'],blocked_llm_hold_seconds=params['blocked_llm_hold_seconds'],bound_seconds=120,
        boundary_case=False,fault_contract_coverage='PENDING',comparison_global_rate=sum(rates),
        calibration_episodes_per_org=params['calibration_episodes_per_org'],repetition=None,
        characterization=False,new_base_generated=False,maximum_capacity=None,sustainable_envelope=None)
    job['job_sha256']=hashlib.sha256(json.dumps(job,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return job


def one(case,variant,label,mode='load'):
    task,state=session()
    cfg=state['config'];copy=Path(state['copy']);scripts=Path(state['orchestration'])
    run_id=label+'-'+case.replace('-','')+'-'+variant.replace('_','')
    name='test_d29_dep_'+hashlib.sha256(run_id.encode()).hexdigest()[:20]
    directory=OUT/label/run_id
    directory.parent.mkdir(parents=True,exist_ok=True)
    job=make_job(case,variant,run_id)
    job_path=directory.parent/(run_id+'-plan.json')
    write(job_path,job)
    with connect(cfg) as p:
        p.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(cfg['NAME'])))
    try:
        isolated=dict(cfg,NAME=name)
        env=environment(isolated,copy)
        if mode=='load':
            command=['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'load_case.py'),'--job',str(job_path),'--output',str(directory)]
        else:
            module='frontiers' if mode=='frontier' else 'physical'
            command=['rtk','proxy',sys.executable,'-B','-X','utf8','-m',PACKAGE+module,'run','--output',str(directory),'--case',case,'--run-id',run_id]
            if mode=='physical':
                command+=['--variant',variant]
        print('RUN '+run_id+' '+mode,flush=True)
        with (directory.parent/(run_id+'.log')).open('x',encoding='utf-8') as log:
            proc=subprocess.run(command,cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
        if mode=='load' and (directory/'dependent-executor-receipt.json').exists():
            with (directory.parent/(run_id+'-verification.log')).open('x',encoding='utf-8') as log:
                verified=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'verify_case.py'),
                    '--job',str(job_path),'--output',str(directory)],cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            result=read(directory/'independent-verification.json') if (directory/'independent-verification.json').exists() else dict(status='NOT_ACCREDITED',errors=['VERIFIER_FAILED'],verifier_exit_code=verified.returncode)
        else:
            result=read(directory/'verification.json') if (directory/'verification.json').exists() else dict(status='NOT_ACCREDITED',errors=['EXECUTOR_FAILED_BEFORE_RECEIPT'])
            result=dict(result,physical_frontier=dict(status=result['status']),load_condition=dict(status='NOT_ACCREDITED',reason='FINITE_ADAPTER_DOES_NOT_EXECUTE_CONFIRMED_BASE_LOAD'),
                confirmed_base_reference=job['confirmed_base_reference'],base_recalibrated=False,new_base_generated=False,
                evidence_synthetic=[],prerequisites=[dict(name='CONFIRMED_BASE',status='ACCEPTED')])
        result=dict(result,case_id=case,variant=variant,run_id=run_id,exit_code=proc.returncode,
            receipt=str(directory.relative_to(OUT)),mode=mode)
        write(directory.parent/(run_id+'-result.json'),result)
        print(json.dumps(dict(case=case,variant=variant,status=result['status'],errors=result.get('errors',[]))),flush=True)
        return result
    finally:
        with connect(cfg) as p:
            p.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            removed=not p.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
        write(directory.parent/(run_id+'-database-cleanup.json'),dict(database=name,removed=removed,created_by_this_run=True))


def individual():
    values=[one(case,variant,'individual') for case,variant in [('R1-03','unequal'),('R1-04','forecasts'),
        ('R1-05','simultaneous'),('R1-05','concentrated'),('R1-06','backlog')]]
    write(OUT/'individual-result.json',dict(results=values,state='FULL_LIVE_MATRIX_NOT_READY'))


def physical_matrix():
    task,state=session()
    sys.path.insert(0,str(Path(state['copy'])/'backend'))
    from apps.agent.tests.scheduling_characterization.physical import ADAPTERS
    from apps.agent.tests.scheduling_characterization.recipes import RECIPES
    jobs=[(c,v) for c in ADAPTERS for v in RECIPES[c].variants]
    jobs.sort(key=lambda j:0 if j[0] in ('R2-04','R2-06','R2-10') else 1)
    values=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(one,c,v,'matrix-physical','physical'):(c,v) for c,v in jobs}
        for future in concurrent.futures.as_completed(pending):
            c,v=pending[future]
            try:
                values.append(future.result())
            except Exception as exc:
                result=dict(case_id=c,variant=v,status='NOT_ACCREDITED',errors=[str(exc)],error_class=type(exc).__name__)
                write(OUT/'matrix-physical'/(c+'-'+v+'-orchestration-error.json'),result)
                values.append(result)
    write(OUT/'matrix-physical-result.json',dict(results=values,state='FULL_LIVE_MATRIX_NOT_READY'))


def remaining_matrix():
    values=[one('R1-01','ordinary','matrix-existing','frontier')]
    for c,v in [('R1-02','balanced'),('R1-03','unequal'),('R1-04','forecasts'),('R1-05','simultaneous'),
        ('R1-05','concentrated'),('R1-06','backlog'),('R2-01','slow'),('R2-02','blocked'),('R2-09','slow_meta'),('R2-09','uncertain_meta')]:
        values.append(one(c,v,'matrix-existing'))
    write(OUT/'matrix-existing-result.json',dict(results=values,state='FULL_LIVE_MATRIX_NOT_READY'))


def regression(kind):
    task,state=session();cfg=state['config'];copy=Path(state['copy'])
    if kind=='unit':
        labels=['apps.agent.tests.'+n for n in ('test_scheduling_characterization','test_scheduling_controller','test_d29_physical','test_d29_frontiers')]
        command=['rtk','proxy',sys.executable,'-B','-X','utf8','-m','unittest','-v']+labels
        with (OUT/'unit-regression.log').open('x',encoding='utf-8') as log:
            proc=subprocess.run(command,cwd=copy/'backend',env=environment(cfg,copy),stdout=log,stderr=subprocess.STDOUT)
        write(OUT/'unit-regression.json',dict(exit_code=proc.returncode,labels=labels,scope='REGRESSION_NOT_ACCREDITATION'))
        print('D29 regression exit '+str(proc.returncode),flush=True)
        return
    name='test_d29_dependent_appreg'
    with connect(cfg) as p:
        p.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(cfg['NAME'])))
    try:
        env=dict(environment(dict(cfg,NAME=name),copy),D29_REGRESSION_OUTPUT=str(OUT/'application-regression.json'))
        script=ROOT/'docs/evals/d29-physical-2026-10-06/orchestration-current/app_regression.py'
        with (OUT/'application-regression.log').open('x',encoding='utf-8') as log:
            proc=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(script)],cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
        write(OUT/'application-regression-exit.json',dict(exit_code=proc.returncode))
        print('Application regression exit '+str(proc.returncode),flush=True)
    finally:
        with connect(cfg) as p:
            p.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        write(OUT/'application-database-cleanup.json',dict(database=name,removed=True,created_by_this_run=True))


def close():
    task,state=session();cfg=state['config']
    with connect(cfg) as p:
        names=[r[0] for r in p.execute("SELECT datname FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')").fetchall()]
        if names!=[cfg['NAME']]:
            raise RuntimeError('Unexpected database remains: '+str(names))
        p.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(cfg['NAME'])))
    subprocess.run(['rtk','proxy',str(BIN/'pg_ctl.exe'),'-D',state['data'],'stop','-m','fast','-w'],check=True)
    owned=task.resolve()
    if owned.parent!=Path(tempfile.gettempdir()).resolve() or not owned.name.startswith(PREFIX):
        raise RuntimeError('Unsafe cleanup path')
    subprocess.run(['rtk','proxy','powershell','-NoProfile','-Command',"Remove-Item -LiteralPath '"+str(owned)+"' -Recurse -Force"],check=True)
    with socket.socket() as sock:
        stopped=sock.connect_ex(('127.0.0.1',int(cfg['PORT'])))!=0
    write(OUT/'lab-cleanup.json',dict(owned_temp_removed=not owned.exists(),port_closed=stopped,
        credentials_removed=not (owned/'session.json').exists(),private_databases_removed=True))
    final=integrity();initial=read(OUT/'initial-integrity.json')
    if final['protected_sources']!=initial['protected_sources'] or final['previous_evidence']!=initial['previous_evidence']:
        raise RuntimeError('Protected manifests changed')
    write(OUT/'final-integrity.json',final)
    print('Private lab removed; baseline and historical receipts intact',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['initialize','individual','matrix-physical','matrix-existing','unit','application','close'])
    a=p.parse_args()
    {'initialize':initialize,'individual':individual,'matrix-physical':physical_matrix,'matrix-existing':remaining_matrix,
        'unit':lambda:regression('unit'),'application':lambda:regression('application'),'close':close}[a.command]()
