"""New window cases and directly affected composer, visibility, history and retry cases."""
import json
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
pattern = 'WA-WIN-01|WA-CMP-01|WA-VIS-01|WA-HIST-01|WA-HIST-02|WA-RETRY-01|Inbox — aislamiento del borrador'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
    'src/pages/inbox/index.window.test.jsx', 'src/pages/inbox/index.test.jsx',
    'src/pages/inbox/index.retry.test.jsx', '--testNamePattern='+pattern,
    '--fileParallelism=false', '--reporter=default', '--reporter=json',
    '--outputFile='+str(out/'vitest.json')]
with (out/'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=240)
(out/'frontend-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
print((out/'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
