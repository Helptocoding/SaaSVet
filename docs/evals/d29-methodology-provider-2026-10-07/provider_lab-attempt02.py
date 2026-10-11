"""Local lab for the explicitly authorized minimal provider validation only."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PREP=ROOT/'docs/evals/d29-gap-preparation-2026-10-07'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


lab=module('previous_owned_lab',ROOT/'docs/evals/d29-dependent-2026-10-07/orchestration/lab.py')
lab.OUT=HERE
lab.PREFIX='vet-d29-provider-20261007-'


def write(name,value):
    lab.write(HERE/name,value)


def integrity():
    result=module('protected_integrity',PREP/'check_integrity.py').audit()
    index=lab.read(PREP/'artifact-index.json')
    errors=[name for name,entry in index.items() if lab.sha(PREP/name)!=entry['sha256']]
    result.update(preparation_index_sha256=lab.sha(PREP/'artifact-index.json'),
        preparation_artifact_count=len(index),preparation_mismatches=errors)
    result['intact']=result['intact'] and not errors
    if not result['intact']:
        raise RuntimeError('Protected prior evidence changed')
    return result


def initialize():
    write('complete-initial-integrity.json',integrity())
    approved={}
    for name in ('evaluation_provider.py','clock_guard.py','host-event-cut.ps1'):
        shutil.copy2(PREP/name,HERE/'orchestration'/name)
        approved[name]=dict(source=str(PREP/name),sha256=lab.sha(PREP/name))
    write('approved-overlay-provenance.json',approved)
    lab.initialize()
    task,state=lab.session()
    # Old laboratory freezes Python orchestration; the readonly Windows event
    # collector is additional evaluation infrastructure, copied without edits.
    shutil.copy2(HERE/'orchestration/host-event-cut.ps1',Path(state['orchestration'])/'host-event-cut.ps1')


def run(attempt=1):
    from psycopg import sql
    task,state=lab.session()
    cfg=state['config']
    copy=Path(state['copy'])
    scripts=Path(state['orchestration'])
    for name,digest in lab.read(HERE/'orchestration-seal.json').items():
        if lab.sha(scripts/name)!=digest or lab.sha(HERE/'orchestration'/name)!=digest:
            raise RuntimeError('Frozen validation infrastructure changed')
    for name,entry in lab.read(HERE/'approved-overlay-provenance.json').items():
        if lab.sha(scripts/name)!=entry['sha256']:
            raise RuntimeError('Approved provider/clock overlay changed')
    if attempt==2:
        scripts=task/'orchestration-v2'
        scripts.mkdir(exist_ok=False)
        for source in (HERE/'orchestration-v2').iterdir():
            if source.is_file():
                shutil.copy2(source,scripts/source.name)
        write('orchestration-v2-seal.json',{f.name:lab.sha(f) for f in scripts.iterdir() if f.is_file()})
        for name,entry in lab.read(HERE/'approved-overlay-provenance.json').items():
            if lab.sha(scripts/name)!=entry['sha256']:
                raise RuntimeError('Approved provider/clock overlay changed')
    base=lab.BASE_DIR/'confirmed-base-receipt.json'
    job=dict(run_id=f'provider-isolation-minimal-{attempt:02d}',phase='PROVIDER_INFRASTRUCTURE_VALIDATION',
        case_id='R2-09',variant='uncertain_meta',input_count=2,organization_count=2,
        conversations_per_org_reference_only=3,slow_multiplier=2,blocked_llm_hold_seconds=120,
        provider_sha256=lab.sha(scripts/'evaluation_provider.py'),
        confirmed_base_reference=dict(path=str(base),sha256=lab.sha(base)),
        baseline=lab.BASE,scenario_accreditation=False,characterization=False,
        arrival_recipe='ONE_ORDINARY_INPUT_PER_ORG_AFTER_PARTICIPANTS_READY; NO_RATE_SCHEDULE',
        population_scope='MINIMAL_PROVIDER_FIXTURE_SUBSET_NOT_A_BASE_POPULATION_CHANGE',
        planner_count=2,sender_count=1,batch=1,poll_seconds=1)
    suffix='' if attempt==1 else f'-{attempt:02d}'
    plan_name='provider-validation-plan'+suffix+'.json'
    write(plan_name,job)
    name=f'test_d29_provider_isolation_{attempt:02d}'
    directory=HERE/f'provider-validation-{attempt:02d}'
    with lab.connect(cfg) as db:
        db.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(cfg['NAME'])))
    try:
        env=lab.environment(dict(cfg,NAME=name),copy)
        env['PYTHONPATH']=str(scripts)+os.pathsep+env['PYTHONPATH']
        with (HERE/f'provider-validation-{attempt:02d}.log').open('x',encoding='utf-8') as log:
            proc=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'provider_validation.py'),
                '--job',str(HERE/plan_name),'--output',str(directory)],
                cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
        write('provider-validation-exit'+suffix+'.json',dict(exit_code=proc.returncode,scope='MINIMAL_PROVIDER_INFRASTRUCTURE_ONLY'))
        print('Provider infrastructure validation exit '+str(proc.returncode),flush=True)
    finally:
        with lab.connect(cfg) as db:
            db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            gone=not db.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
        write('provider-database-cleanup'+suffix+'.json',dict(database=name,created_by_this_phase=True,removed=gone))


def close():
    lab.close()
    write('complete-final-integrity.json',integrity())


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['initialize','run','run02','close'])
    args=parser.parse_args()
    {'initialize':initialize,'run':run,'run02':lambda:run(2),'close':close}[args.command]()
