"""Run only GTF-01 and directly affected Inbox regressions."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = 'WA-GTF-01|WA-GRP-01|WA-CMP-01|WA-LDE-01'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx', 'src/pages/inbox/ThreadViewport.test.jsx',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest.json')]
with (output / 'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log, stderr=subprocess.STDOUT,
                            timeout=180)
(output / 'frontend-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New GTF-01 and directly affected message grouping, composer and loading cases only'}, indent=2), encoding='utf-8')
print((output / 'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
