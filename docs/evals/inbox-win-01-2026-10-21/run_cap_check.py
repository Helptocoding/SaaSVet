"""Repeat only the timed-out existing cap case; keep the same 5s test timeout."""
import json
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
    'src/pages/inbox/index.test.jsx', '--testNamePattern=aplica el cap global',
    '--reporter=default', '--reporter=json', '--outputFile='+str(out/'vitest-cap.json')]
with (out/'frontend-cap.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=90)
(out/'frontend-cap-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
print((out/'frontend-cap.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
