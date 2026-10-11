import json
from pathlib import Path

e = json.loads((Path('docs/evals/d29-authorized-probes-2026-10-07/environment.json')).read_text())
s = json.loads((Path(e['task']) / 'session.json').read_text())
p = Path(s['orchestration']) / 'worker_entry.py'
text = p.read_text(encoding='utf-8')
old = "('R1-03', 'R1-04', 'R2-04', 'R2-09')"
if old not in text:
    raise RuntimeError('worker entry patch target not found')
p.write_text(text.replace(old, "('R1-03', 'R1-04', 'R2-02', 'R2-04', 'R2-09')"), encoding='utf-8')
print(p)
