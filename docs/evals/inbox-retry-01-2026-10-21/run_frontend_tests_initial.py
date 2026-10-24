"""RETRY-01 and directly affected send/transcript regressions only."""
import json
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
pattern = 'WA-RETRY-01|WA-UNR-02|WA-HIST-02|WA-HIST-01|WA-GRP-01|Inbox — aislamiento del borrador|sendInboxMessage'
cmd = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
       'src/pages/inbox/index.test.jsx', 'src/pages/inbox/index.unread.test.jsx',
       'src/pages/inbox/index.retry.test.jsx', 'src/pages/inbox/useThreadHistory.test.jsx',
       'src/api/inbox.test.js',
       '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
       '--outputFile=' + str(out / 'vitest.json')]
with (out / 'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=root / 'frontend', stdout=log,
                            stderr=subprocess.STDOUT, timeout=240)
(out / 'frontend-run.json').write_text(json.dumps({'exit_code': result.returncode, 'command': cmd}, indent=2), encoding='utf-8')
print((out / 'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
