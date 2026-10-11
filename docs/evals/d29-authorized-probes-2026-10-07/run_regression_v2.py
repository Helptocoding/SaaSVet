"""Complete unchanged application regression in independently receipted suites."""
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import authorized_lab as lab

LABELS=['test_b3_durable','test_b4_sender','test_w1_monotonic','test_b5_safety',
        'test_operation_execution','test_b9b_budget','test_b9c_concurrency','test_b9c_processes']

def main():
    task,state=lab.session();cfg=state['config'];copy=Path(state['copy'])
    root=OUT/'application-regression-v2';root.mkdir(exist_ok=False)
    with lab.connect(cfg) as con:
        active=con.execute("SELECT datname,state FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
        dbs=[r[0] for r in con.execute('SELECT datname FROM pg_database')]
        if active:raise RuntimeError('Unexpected active clients: '+str(active))
        old='test_d29_dependent_appreg'
        if old in dbs:con.execute(lab.sql.SQL('DROP DATABASE {}').format(lab.sql.Identifier(old)))
    lab.write(root/'previous-incomplete-attempt.json',dict(status='INCOMPLETE_NOT_PASS',
        reason='No running process or final receipt after continuation; exit outcome unknown',
        log_path='application-regression.log',log_sha256=lab.sha(OUT/'application-regression.log'),
        prior_database_removed=old in dbs))
    script=lab.ROOT/'docs/evals/d29-physical-2026-10-06/orchestration-current/app_regression.py'
    def suite(label):
        name='test_d29_reg_v2_'+label.removeprefix('test_')
        path=root/(label+'.json')
        with lab.connect(cfg) as con:
            con.execute(lab.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(lab.sql.Identifier(name),lab.sql.Identifier(cfg['NAME'])))
        env=lab.environment(dict(cfg,NAME=name),copy)
        env.update(D29_REGRESSION_LABELS=json.dumps(['apps.agent.tests.'+label]),D29_REGRESSION_OUTPUT=str(path))
        try:
            with (root/(label+'.log')).open('x',encoding='utf-8') as log:
                proc=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(script)],cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            result=lab.read(path) if path.exists() else dict(status='INCOMPLETE_NOT_PASS',tests=None,failures=[],errors=['NO_RECEIPT'])
            lab.write(root/(label+'-exit.json'),dict(exit_code=proc.returncode))
            print(json.dumps(dict(suite=label,status=result['status'],tests=result['tests'],exit_code=proc.returncode)),flush=True)
            return dict(label=label,exit_code=proc.returncode,receipt=result,receipt_sha256=lab.sha(path) if path.exists() else None)
        finally:
            with lab.connect(cfg) as con:
                con.execute(lab.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(lab.sql.Identifier(name)))
                absent=not con.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
            lab.write(root/(label+'-cleanup.json'),dict(database=name,removed=absent))
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(suite,label):label for label in LABELS}
        for f in as_completed(futures):results.append(f.result())
    results.sort(key=lambda r:LABELS.index(r['label']))
    ok=all(r['exit_code']==0 and r['receipt']['status']=='PASS' for r in results)
    value=dict(status='PASS' if ok else 'FAIL',scope='EXISTING_APPLICATION_REGRESSION_NOT_PHYSICAL_ACCREDITATION',
        tests=sum(r['receipt']['tests'] or 0 for r in results),
        failures=[x for r in results for x in r['receipt']['failures']],errors=[x for r in results for x in r['receipt']['errors']],
        skipped=sum(r['receipt'].get('skipped',0) for r in results),labels=['apps.agent.tests.'+x for x in LABELS],
        suites=results,source_integrity=all(r['receipt'].get('source_integrity') is True for r in results),benchmark=False,
        method='Same baseline regression suites, separate fresh DB per suite, two regression processes, no live scenario load.')
    lab.write(OUT/'application-regression.json',value)
    lab.write(OUT/'application-regression-exit.json',dict(exit_code=0 if ok else 1))
    print('Application regression '+value['status'],flush=True)

if __name__=='__main__':main()
