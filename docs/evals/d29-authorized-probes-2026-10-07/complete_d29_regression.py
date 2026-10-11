"""Run the nine previously skipped tests on preserved receipts, without load."""
import os
import subprocess
import sys
from pathlib import Path
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(OUT))
import authorized_lab as lab
task,state=lab.session();copy=Path(state['copy'])
env=lab.environment(state['config'],copy)
env['D29_FRONTIER_RECEIPTS']=str(lab.ROOT/'docs/evals/d29-frontiers-2026-10-07')
labels=['apps.agent.tests.test_d29_frontiers.PhysicalVerifierNegativeTests']
with (OUT/'d29-preserved-receipt-regression.log').open('x',encoding='utf-8') as f:
    p=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8','-m','unittest','-v']+labels,
        cwd=copy/'backend',env=env,stdout=f,stderr=subprocess.STDOUT)
lab.write(OUT/'d29-preserved-receipt-regression.json',dict(exit_code=p.returncode,labels=labels,
    preserved_receipt_root=env['D29_FRONTIER_RECEIPTS'],scope='OFFLINE_NEGATIVE_VERIFIER_REGRESSION_NO_LOAD'))
print('Preserved-receipt D29 regression exit '+str(p.returncode),flush=True)
