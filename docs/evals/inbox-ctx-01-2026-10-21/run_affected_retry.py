"""The retry page fixture mounts the new panel: ten flows, 25 parameterized cases."""
import json
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
    'src/pages/inbox/index.retry.test.jsx', '--reporter=default', '--reporter=json',
    '--outputFile='+str(out/'vitest-retry.json')]
with (out/'frontend-retry.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=120)
(out/'frontend-retry-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
report = json.loads((out/'vitest-retry.json').read_text(encoding='utf-8'))
print(json.dumps({key: report.get(key) for key in ('numPassedTests', 'numFailedTests', 'numPendingTests', 'success')}, indent=2))
assert result.returncode == 0
command = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js',
    'src/pages/inbox/index.test.jsx', '--format=json', '--output-file='+str(out/'lint-history.json')]
with (out/'lint-history.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=90)
(out/'lint-history-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
raise SystemExit(result.returncode)
