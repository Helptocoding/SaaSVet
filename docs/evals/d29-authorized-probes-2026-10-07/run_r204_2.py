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

e = json.loads((OUT / 'environment.json').read_text())
s = json.loads((Path(e['task']) / 'session.json').read_text())
cfg, copy, scripts = s['config'], Path(s['copy']), Path(s['orchestration'])
run_id = 'authorized-r204-postcommit-base-20261007-0002'
root = OUT / 'r2-04'
directory = root / run_id
name = 'test_d29_auth_' + hashlib.sha256(run_id.encode()).hexdigest()[:20]
with lab.connect(cfg) as con:
    con.execute(lab.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(lab.sql.Identifier(name), lab.sql.Identifier(cfg['NAME'])))
env = lab.environment(dict(cfg, NAME=name), copy)
env['PYTHONPATH'] = str(scripts) + os.pathsep + str(copy / 'backend')
root.mkdir(parents=True, exist_ok=True)
try:
    with (root / (run_id + '.log')).open('x', encoding='utf-8') as log:
        proc = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'r204_entry.py'),'--output',str(directory),'--run-id',run_id], cwd=copy/'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
    receipt = json.loads((directory/'r204-receipt.json').read_text()) if (directory/'r204-receipt.json').exists() else {'status':'NOT_ACCREDITED','error':'RECEIPT_MISSING'}
    base_path = ROOT / 'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'
    receipt.update({'executor_exit_code':proc.returncode,'run_id':run_id,'case_id':'R2-04','variant':'postcommit_base_concurrent','confirmed_base_reference':{'path':str(base_path),'sha256':lab.sha(base_path)}})
    (root/(run_id+'-result.json')).write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
finally:
    with lab.connect(cfg) as con:
        con.execute(lab.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(lab.sql.Identifier(name)))
    (root/(run_id+'-database-cleanup.json')).write_text(json.dumps({'database':name,'removed':True,'created_by_this_run':True},indent=2)+'\n',encoding='utf-8')

