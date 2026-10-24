"""Local build without upload credentials and scoped JS lint."""
import json
import os
import subprocess
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
kind = sys.argv[1]
env = os.environ.copy()
env.pop('SENTRY_AUTH_TOKEN', None)
command = ['rtk', 'proxy', 'node']
if kind == 'build':
    command += ['node_modules/vite/bin/vite.js', 'build']
else:
    command += ['node_modules/eslint/bin/eslint.js', 'src/pages/inbox/index.jsx',
        'src/pages/inbox/ThreadContextPanel.jsx', 'src/pages/inbox/index.context.test.jsx',
        'src/pages/inbox/index.test.jsx', 'src/pages/inbox/index.window.test.jsx',
        'src/pages/inbox/index.retry.test.jsx', 'src/pages/inbox/index.unread.test.jsx',
        'src/api/inbox.js', 'src/api/inbox.test.js', '--format=json', '--output-file='+str(out/'lint.json')]
with (out/f'{kind}.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
(out/f'{kind}-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode,
    sentry_upload_disabled=True), indent=2), encoding='utf-8')
if kind == 'lint':
    print(json.dumps([dict(file=row['filePath'], messages=row['messages'])
                      for row in json.loads((out/'lint.json').read_text(encoding='utf-8')) if row['messages']]))
else:
    print(json.dumps(dict(check=kind, exit_code=result.returncode, log=str(out/'build.log'))))
raise SystemExit(result.returncode)
