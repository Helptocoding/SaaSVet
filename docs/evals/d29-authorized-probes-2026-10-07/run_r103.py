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

def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))

def write(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

task, state = lab.session()
cfg = state['config']
copy = Path(state['copy'])
scripts = Path(state['orchestration'])
run_id = 'authorized-r103-unequal-20261007-0001'
directory = OUT / 'r1-03' / run_id
job = lab.make_job('R1-03', 'unequal', run_id)
job_path = OUT / 'r1-03' / (run_id + '-plan.json')
lab.write(job_path, job)
name = 'test_d29_auth_' + hashlib.sha256(run_id.encode()).hexdigest()[:20]
with lab.connect(cfg) as p:
    p.execute(lab.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(lab.sql.Identifier(name), lab.sql.Identifier(cfg['NAME'])))
isolated = dict(cfg, NAME=name)
env = lab.environment(isolated, copy)
env['PYTHONPATH'] = str(scripts) + os.pathsep + str(copy / 'backend')
directory.parent.mkdir(parents=True, exist_ok=True)
log_path = OUT / 'r1-03' / (run_id + '.log')
command = ['rtk', 'proxy', sys.executable, '-B', '-X', 'utf8', str(scripts / 'r103_entry.py'), '--job', str(job_path), '--output', str(directory)]
try:
    with log_path.open('x', encoding='utf-8') as log:
        proc = subprocess.run(command, cwd=copy / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
    verify_log = OUT / 'r1-03' / (run_id + '-verification.log')
    with verify_log.open('x', encoding='utf-8') as log:
        verified = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'verify_case.py'),'--job',str(job_path),'--output',str(directory)], cwd=copy/'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
    result_path = directory / 'independent-verification.json'
    result = read(result_path) if result_path.exists() else {'status':'INVALID_RUN','errors':['VERIFIER_DID_NOT_COMPLETE']}
    result.update({'case_id':'R1-03','variant':'unequal','run_id':run_id,'executor_exit_code':proc.returncode,'verifier_exit_code':verified.returncode,'job_sha256':job['job_sha256'],'confirmed_base_reference':job['confirmed_base_reference'],'status':('INVALID_RUN' if (directory/'clock-invalid.json').exists() or result.get('status')=='INVALID_RUN' else result.get('status'))})
    write(OUT / 'r1-03-result.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
finally:
    with lab.connect(cfg) as p:
        p.execute(lab.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(lab.sql.Identifier(name)))
    write(OUT / 'r1-03-database-cleanup.json', {'database':name,'removed':True,'created_by_this_run':True})
