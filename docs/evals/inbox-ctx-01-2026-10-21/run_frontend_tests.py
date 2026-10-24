"""Context and the directly affected header, history, draft, window and read flows."""
import json
import subprocess
import shutil
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
for name in ('frontend.log', 'frontend-run.json', 'vitest.json'):
    source = out/name
    initial = out/('initial-'+name)
    if source.exists() and not initial.exists():
        shutil.copyfile(source, initial)
pattern = 'WA-CTX-01|WA-WIN-01|WA-UNR-02|WA-HIST-01|WA-HIST-02|WA-VER-01|Inbox — aislamiento del borrador'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
    'src/pages/inbox/index.context.test.jsx', 'src/pages/inbox/index.test.jsx',
    'src/pages/inbox/index.window.test.jsx', 'src/pages/inbox/index.unread.test.jsx',
    'src/api/inbox.test.js', '--testNamePattern='+pattern, '--fileParallelism=false',
    '--reporter=default', '--reporter=json', '--outputFile='+str(out/'vitest.json')]
with (out/'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=240)
(out/'frontend-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
report = json.loads((out/'vitest.json').read_text(encoding='utf-8'))
print(json.dumps({key: report.get(key) for key in ('numPassedTests', 'numFailedTests', 'numPendingTests', 'success')}, indent=2))
raise SystemExit(result.returncode)
