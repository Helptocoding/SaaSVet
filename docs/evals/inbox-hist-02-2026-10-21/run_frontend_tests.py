"""Only HIST-02 and transcript regressions directly affected by the state split."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = 'WA-HIST-02|WA-HIST-01|WA-GTF-01|WA-LDE-01|WA-VIS-01|WA-GRP-01|WA-AGT-01|Inbox — aislamiento del borrador'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx', 'src/pages/inbox/useThreadHistory.test.jsx',
           'src/pages/inbox/ThreadViewport.test.jsx',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest.json')]
with (output / 'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log,
                            stderr=subprocess.STDOUT, timeout=180)
(output / 'frontend-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New HIST-02 and affected transcript/send/viewport regressions'},
    indent=2), encoding='utf-8')
print((output / 'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
