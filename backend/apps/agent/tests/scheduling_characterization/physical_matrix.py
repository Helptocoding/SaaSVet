"""Run finite physical cases in fresh local test_* clones; no level command.

The full mode also executes the nine existing adapters as finite probes.
It refuses to turn their two-input probe into accreditation of an unobserved
scenario. In particular it cannot invent CONFIRMED_BASE, rates or burst/history
evidence to close a matrix that requires characterization prerequisites.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .execution import DIRECT_LOAD_CASES, verify_sources
from .physical import ADAPTERS, read
from .recipes import RECIPES
from .runner import BASELINE, bootstrap, write_json

MODULE='apps.agent.tests.scheduling_characterization.physical_matrix'


def probe(output,case,variant,run_id):
    """Existing real executor, conservative finite-probe disposition."""
    from .controller import digest,source_hashes
    from .execution import execute_job,read_capture,read_lines
    from .scenario_observations import observations
    from .recipes import verify_recipe,required_transitions
    job=dict(baseline=BASELINE,bound_seconds=120,case_id=case,variant=variant,run_id=run_id,
        organization_count=1 if case=='R1-01' else 2,conversations_per_org=3,phase='FINITE_PHYSICAL_EXISTING_ADAPTER',
        slow_multiplier=2,blocked_llm_hold_seconds=120,source_hashes=source_hashes())
    job['job_sha256']=digest(job)
    error=None;result=None;events=[]
    try:result=execute_job(output,job,finite=True)
    except Exception as exc:error=dict(kind='EXISTING_FINITE_ADAPTER_LIMITATION',exception_class=type(exc).__name__,message=str(exc))
    if result:
        # Only observed conditions are eligible. Rate and base-load assertions
        # are deliberately absent: this task cannot characterize them.
        if case in ('R1-01','R1-02','R1-04','R2-01','R2-02','R2-09'):
            try:
                job['organization_ids']=sorted(int(o) for o in result['organization_counts'])
                final=read_lines(Path(output)/'snapshots.jsonl')[-1]
                wire=[e for role in ('planner_1','planner_2','sender') for e in read_lines(Path(output)/(role+'-wire.jsonl')) if e['event']=='dispatch']
                if case=='R1-02':
                    # Prove actual equal finite offers and overlapping processes,
                    # without supplying fictitious per-minute rate assertions.
                    journals=read_capture(Path(output))
                    planners=[j for j in journals if j[0]['worker'] in ('planner_1','planner_2')]
                    offers=read_lines(Path(output)/'offers.jsonl')
                    counts=[sum(o['outcome']=='ACCEPTED_DURABLE' and o['organization_id']==org for o in offers) for org in job['organization_ids']]
                    overlap=len(planners)==2 and len({j[0]['os_pid'] for j in planners})==2 and max(j[0]['monotonic_ns'] for j in planners)<min(j[-1]['monotonic_ns'] for j in planners)
                    if overlap:
                        events.append(dict(event='concurrent_planners',run_id=run_id,organization_index=0,db_ns=final['db_ns'],observed=True,source='JOURNAL'))
                    if counts[0]==counts[1] and counts[0]>0:
                        events.append(dict(event='balanced_offer',run_id=run_id,organization_index=0,db_ns=final['db_ns'],observed=True,source='INDEPENDENT_DB_WITNESS',accepted_counts=counts))
                else:events=observations(job,result,read_capture(Path(output)),wire,read_lines,Path(output),final)
            except Exception as exc:error=dict(kind='EXISTING_FINITE_ADAPTER_LIMITATION',exception_class=type(exc).__name__,message=str(exc))
    recipe=verify_recipe(job,events)
    issues=recipe['missing']+recipe['violations']
    if error:issues.append('EXISTING_FINITE_PROBE_FAILED')
    if result and not all(result['checks'].values()):issues.append('FINITE_PROBE_CHECK_FAILED')
    status='PHYSICALLY_ACCREDITED' if result and not issues else 'NOT_ACCREDITED'
    receipt=dict(case_id=case,variant=variant,run_id=run_id,baseline=BASELINE,source_kind='ISOLATED_LIVE_EXISTING_ADAPTER',
        status=status,errors=sorted(set(issues)),physical_probe_checks=result.get('checks') if result else None,
        recipe=recipe,error=error,characterization=False,benchmark=False,sustainable_envelope=None,
        load_prerequisites=list(RECIPES[case].prerequisites),confirmed_base_available=False,level_acceptance=False)
    # execute_job normally created output; preserve its failed capture as well.
    Path(output).mkdir(parents=True,exist_ok=True)
    write_json(Path(output)/'existing-adapter-verification.json',receipt)
    return receipt


def clone_run(template,output,case,variant,run_id):
    import psycopg
    from psycopg import sql
    from django.db import connections
    config=json.loads(os.environ['B3_TEST_DATABASE'])
    if config['NAME']!=template or not template.startswith('test_') or config['HOST'] not in ('127.0.0.1','localhost'):
        raise ValueError('Explicit local test_* template required')
    connections.close_all()
    name='test_d29_physical_'+hashlib.sha256(run_id.encode()).hexdigest()[:20]
    with psycopg.connect(dbname='postgres',user=config['USER'],password=config['PASSWORD'],host=config['HOST'],port=config['PORT'],autocommit=True) as admin:
        # A preexisting clone is never reused or dropped.
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(template)))
        try:
            isolated=dict(config,NAME=name);directory=output/run_id
            command=['rtk','proxy',sys.executable,'-X','utf8','-m',
                'apps.agent.tests.scheduling_characterization.physical' if case in ADAPTERS else MODULE,
                'run' if case in ADAPTERS else 'probe','--output',str(directory),'--case',case,'--variant',variant,'--run-id',run_id]
            with (output/(run_id+'.log')).open('x',encoding='utf-8') as log:
                p=subprocess.run(command,env=dict(os.environ,B3_TEST_DATABASE=json.dumps(isolated),PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            filename='verification.json' if case in ADAPTERS else 'existing-adapter-verification.json'
            result=read(directory/filename) if (directory/filename).exists() else dict(status='NOT_ACCREDITED',errors=['EXECUTOR_FAILED_BEFORE_RECEIPT'])
            return dict(result,case_id=case,variant=variant,run_id=run_id,exit_code=p.returncode,receipt=run_id+'/'+filename,
                load_prerequisites=list(RECIPES[case].prerequisites),confirmed_base_available=False,level_acceptance=False)
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            removed=not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
            write_json(output/(run_id+'-database-cleanup.json'),dict(created_by_this_run=True,database=name,removed=removed))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('eight','full','probe'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--template');p.add_argument('--run-id',required=True)
    p.add_argument('--case',choices=tuple(RECIPES));p.add_argument('--variant')
    p.add_argument('--parallel',type=int,default=4)
    a=p.parse_args()
    bootstrap();verify_sources()
    if a.command=='probe':
        if a.case not in DIRECT_LOAD_CASES or a.variant not in RECIPES[a.case].variants:p.error('Declared existing adapter required')
        r=probe(a.output,a.case,a.variant,a.run_id);print(json.dumps(r));return
    if not a.template:p.error('Explicit --template required')
    if not 1<=a.parallel<=8:p.error('parallel must be 1..8 isolated fixture processes')
    cases=ADAPTERS if a.command=='eight' else tuple(RECIPES)
    a.output.mkdir(parents=True,exist_ok=False)
    from .controller import source_hashes
    write_json(a.output/'manifest.json',dict(baseline=BASELINE,sources=source_hashes(),cases=list(cases),characterization=False,
        benchmark=False,sustainable_envelope=None,scope='FINITE_PHYSICAL_BOUNDARIES_ONLY'))
    from django.db import connections
    connections.close_all()
    jobs=[(case,variant,a.run_id+'-'+case.replace('-','')+'-'+variant.replace('_','')) for case in cases for variant in RECIPES[case].variants]
    # Start long natural expirations first; each job owns a separate database.
    jobs.sort(key=lambda j:0 if j[0] in ('R2-04','R2-06','R2-10') else 1)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.parallel) as pool:
        pending={pool.submit(clone_run,a.template,a.output,case,variant,run_id):(case,variant,run_id) for case,variant,run_id in jobs}
        for future in concurrent.futures.as_completed(pending):
            case,variant,run_id=pending[future]
            try:r=future.result()
            except Exception as exc:r=dict(case_id=case,variant=variant,run_id=run_id,status='NOT_ACCREDITED',error_class=type(exc).__name__)
            results.append(r)
            write_json(a.output/(run_id+'-summary.json'),r);print(json.dumps(r),flush=True)
    results.sort(key=lambda r:(r['case_id'],r['variant']))
    complete=len(cases)==17 and all(r['status']=='PHYSICALLY_ACCREDITED' for r in results)
    write_json(a.output/'matrix-result.json',dict(results=results,state='FULL_CONTROLLER_ACCREDITED' if complete else 'FULL_LIVE_MATRIX_NOT_READY',
        all_requested_adapters_accredited=all(r['status']=='PHYSICALLY_ACCREDITED' for r in results if r['case_id'] in ADAPTERS),
        characterization=False,sustainable_envelope=None))
    succeeded=complete if a.command=='full' else all(r['status']=='PHYSICALLY_ACCREDITED' for r in results)
    if not succeeded:raise SystemExit(1)


if __name__=='__main__':main()
