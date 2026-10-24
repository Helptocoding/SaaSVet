"""Run only PERF-02 and directly affected Inbox regressions."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = 'un refresco parcial fallido'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest-selector-final.json')]
with (output / 'frontend-selector-final.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log, stderr=subprocess.STDOUT,
                            timeout=180)
(output / 'frontend-selector-final-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New PERF-02 and directly affected list loading, visibility polling and tab title only'}, indent=2), encoding='utf-8')
print((output / 'frontend-selector-final.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
