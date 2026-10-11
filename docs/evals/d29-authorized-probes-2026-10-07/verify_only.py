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
copy, scripts = Path(s['copy']), Path(s['orchestration'])
job = OUT / 'r2-09' / 'authorized-r209-uncertain-meta-20261007-0001-plan.json'
directory = OUT / 'r2-09' / 'authorized-r209-uncertain-meta-20261007-0001'
env = lab.environment(s['config'], copy)
env['PYTHONPATH'] = str(scripts) + os.pathsep + str(copy / 'backend')
with (OUT / 'r2-09' / 'authorized-r209-uncertain-meta-20261007-0001-verification-retry.log').open('w', encoding='utf-8') as log:
    p = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(scripts/'verify_entry.py'),'--job',str(job),'--output',str(directory)], cwd=copy/'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
print(p.returncode)
if (directory/'independent-verification.json').exists():
    print((directory/'independent-verification.json').read_text(encoding='utf-8'))
