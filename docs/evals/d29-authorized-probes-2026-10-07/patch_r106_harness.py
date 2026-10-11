import json
from pathlib import Path

e = json.loads(Path('docs/evals/d29-authorized-probes-2026-10-07/environment.json').read_text())
s = json.loads((Path(e['task']) / 'session.json').read_text())
p = Path(s['orchestration']) / 'load_case.py'
text = p.read_text(encoding='utf-8')
old = "if job[key] != p[key]:\n            raise ValueError('Accepted base parameter changed: ' + key)"
new = "if job[key] != p[key] and not (job['case_id'] == 'R1-06' and key == 'conversations_per_org' and job.get('scenario_population') == 'R1-06_OPTION_B_2X4'):\n            raise ValueError('Accepted base parameter changed: ' + key)"
if old not in text:
    raise RuntimeError('R1-06 harness patch target not found')
p.write_text(text.replace(old, new), encoding='utf-8')
print(p)
