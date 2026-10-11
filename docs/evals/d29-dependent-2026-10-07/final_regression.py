"""Final offline D29 regression with all accepted physical negative fixtures."""
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))


def main():
    labels=['apps.agent.tests.'+name for name in ('test_scheduling_characterization',
        'test_scheduling_controller','test_d29_physical','test_d29_frontiers')]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',
        PYTHONPATH=str(lab['ROOT']/'backend'),
        D29_FRONTIER_RECEIPTS=str(lab['ROOT']/'docs/evals/d29-frontiers-2026-10-07'))
    log=HERE/'final-d29-regression.log'
    with log.open('x',encoding='utf-8') as stream:
        proc=subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8','-m','unittest','-v']+labels,
            cwd=lab['ROOT']/'backend',env=env,stdout=stream,stderr=subprocess.STDOUT)
    text=log.read_text(encoding='utf-8')
    count=re.search(r'Ran (\d+) tests',text)
    skipped=re.search(r'skipped=(\d+)',text)
    value=dict(exit_code=proc.returncode,tests=int(count[1]) if count else None,
        skipped=int(skipped[1]) if skipped else 0,labels=labels,
        scope='FINAL_OFFLINE_REGRESSION_NOT_LOAD_ACCREDITATION',
        sources_intact=lab['integrity']()['intact'],log_sha256=lab['sha'](log))
    lab['write'](HERE/'final-d29-regression.json',value)
    print('Final D29 regression:',value['tests'],'tests; exit',proc.returncode,flush=True)


if __name__=='__main__':
    main()
