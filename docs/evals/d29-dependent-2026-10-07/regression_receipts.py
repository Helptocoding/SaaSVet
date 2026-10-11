"""Run the omitted negative checks using accepted raw physical receipts."""
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
lab = runpy.run_path(str(HERE / 'orchestration/lab.py'))
_, state = lab['session']()
copy = Path(state['copy'])
env = lab['environment'](state['config'], copy)
env['D29_FRONTIER_RECEIPTS'] = str(lab['ROOT'] / 'docs/evals/d29-frontiers-2026-10-07')
label = 'apps.agent.tests.test_d29_frontiers.PhysicalVerifierNegativeTests'
with (HERE / 'receipt-negative-regression.log').open('x', encoding='utf-8') as log:
    process = subprocess.run(['rtk', 'proxy', sys.executable, '-B', '-X', 'utf8',
                              '-m', 'unittest', '-v', label], cwd=copy/'backend',
                             env=env, stdout=log, stderr=subprocess.STDOUT)
lab['write'](HERE / 'receipt-negative-regression.json',
             dict(exit_code=process.returncode, label=label,
                  physical_receipts=env['D29_FRONTIER_RECEIPTS'],
                  scope='REGRESSION_NOT_LOAD_ACCREDITATION'))
print('Physical receipt negative checks exit', process.returncode, flush=True)
