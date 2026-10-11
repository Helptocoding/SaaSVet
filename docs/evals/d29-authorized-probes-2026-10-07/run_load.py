import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\LAP\Desktop\VeterinariaSaaS')
OUT = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07'
sys.path.insert(0, str(OUT))
import authorized_lab as lab

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def write(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('case', choices=['R1-06','R2-02','R2-09'])
ap.add_argument('variant')
ap.add_argument('run_id')
a = ap.parse_args()
task, state = lab.session()
cfg, copy, scripts = state['config'], Path(state['copy']), Path(state['orchestration'])
job = lab.make_job(a.case, a.variant, a.run_id)
if a.case == 'R1-06':
    job['conversations_per_org'] = 4
    job['scenario_population'] = 'R1-06_OPTION_B_2X4'
    job['base_population_reference'] = {'conversations_per_org': 3, 'receipt': str(lab.BASE_DIR / 'confirmed-base-receipt.json')}
if a.case == 'R2-02':
    job['allow_coalesced_episodes'] = True
    job['input_episode_relation'] = 'ONE_INPUT_ONE_MEMBERSHIP_MAY_COALESCE'
job['job_sha256'] = digest({k:v for k,v in job.items() if k != 'job_sha256'})
root = OUT / a.case.lower()
directory = root / a.run_id
job_path = root / (a.run_id + '-plan.json')
lab.write(job_path, job)
name = 'test_d29_auth_' + hashlib.sha256(a.run_id.encode()).hexdigest()[:20]
with lab.connect(cfg) as p:
    p.execute(lab.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(lab.sql.Identifier(name), lab.sql.Identifier(cfg['NAME'])))
isolated = dict(cfg, NAME=name)
env = lab.environment(isolated, copy)
env['PYTHONPATH'] = str(scripts) + os.pathsep + str(copy / 'backend')
directory.parent.mkdir(parents=True, exist_ok=True)
try:
    with (root / (a.run_id + '.log')).open('x', encoding='utf-8') as stream:
        proc = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'load_entry.py'),'--job',str(job_path),'--output',str(directory)], cwd=copy/'backend', env=env, stdout=stream, stderr=subprocess.STDOUT)
    with (root / (a.run_id + '-verification.log')).open('x', encoding='utf-8') as stream:
        verified = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'verify_entry.py'),'--job',str(job_path),'--output',str(directory)], cwd=copy/'backend', env=env, stdout=stream, stderr=subprocess.STDOUT)
    path = directory / 'independent-verification.json'
    result = read(path) if path.exists() else {'status':'NOT_ACCREDITED','errors':['VERIFIER_DID_NOT_COMPLETE']}
    result.update({'case_id':a.case,'variant':a.variant,'run_id':a.run_id,'executor_exit_code':proc.returncode,'verifier_exit_code':verified.returncode,'job_sha256':job['job_sha256'],'confirmed_base_reference':job['confirmed_base_reference']})
    write(root / (a.run_id + '-result.json'), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
finally:
    with lab.connect(cfg) as p:
        p.execute(lab.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(lab.sql.Identifier(name)))
    write(root / (a.run_id + '-database-cleanup.json'), {'database':name,'removed':True,'created_by_this_run':True})
