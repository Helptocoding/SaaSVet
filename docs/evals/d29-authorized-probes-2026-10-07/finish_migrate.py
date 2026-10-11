import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import authorized_lab as lab

e = json.loads((lab.OUT / 'environment.json').read_text())
task = Path(e['task'])
state = json.loads((task / 'session.json').read_text())
cfg = state['config']
env = lab.environment(cfg, Path(state['copy']))
with (lab.OUT / 'schema-retry.log').open('w', encoding='utf-8') as log:
    p = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8','manage.py','migrate','--noinput'], cwd=Path(state['copy'])/'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
print(p.returncode)
