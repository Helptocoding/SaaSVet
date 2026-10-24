"""Run only AGT-01 and directly affected Inbox regressions."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = 'WA-AGT-01|allows the current human owner|A→B→A|no ejecuta continuaciones'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest.json')]
with (output / 'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log, stderr=subprocess.STDOUT,
                            timeout=180)
(output / 'frontend-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New AGT-01 and directly affected claim, selection and late response cases only'}, indent=2), encoding='utf-8')
print((output / 'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
