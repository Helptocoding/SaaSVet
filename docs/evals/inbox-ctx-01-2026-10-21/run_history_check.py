"""Repeat only the affected history test after naming its transcript region."""
import json
import subprocess
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
suffix = sys.argv[1] if len(sys.argv) > 1 else 'history'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
    'src/pages/inbox/index.test.jsx', '--testNamePattern=el poll conserva páginas anteriores',
    '--reporter=default', '--reporter=json', '--outputFile='+str(out/f'vitest-{suffix}.json')]
with (out/f'frontend-{suffix}.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=out.parents[2]/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=90)
(out/f'frontend-{suffix}-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
report = json.loads((out/f'vitest-{suffix}.json').read_text(encoding='utf-8'))
print(json.dumps({key: report.get(key) for key in ('numPassedTests', 'numFailedTests', 'numPendingTests', 'success')}, indent=2))
raise SystemExit(result.returncode)
