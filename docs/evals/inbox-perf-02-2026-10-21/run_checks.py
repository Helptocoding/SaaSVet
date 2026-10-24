"""Build without publishing source maps; lint only files changed for PERF-02."""
import json
import os
import subprocess
import sys
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
kind = sys.argv[1]
env = os.environ.copy()
env.pop('SENTRY_AUTH_TOKEN', None)
if kind == 'build':
    cmd = ['rtk', 'proxy', 'node', 'node_modules/vite/bin/vite.js', 'build']
else:
    cmd = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js',
           'src/pages/inbox/index.jsx', 'src/pages/inbox/index.test.jsx',
           '--format=json',
           '--output-file=' + str(output / 'lint.json')]
with (output / f'{kind}.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(cmd, cwd=root / 'frontend', env=env, stdout=log,
                            stderr=subprocess.STDOUT, timeout=180)
(output / f'{kind}-run.json').write_text(json.dumps({'command': cmd,
    'exit_code': result.returncode, 'sentry_upload_disabled': True}, indent=2), encoding='utf-8')
if kind == 'lint':
    data = json.loads((output / 'lint.json').read_text(encoding='utf-8'))
    print(json.dumps([{'path': x['filePath'], 'messages': [
        {'line': m['line'], 'rule': m['ruleId'], 'message': m['message'].splitlines()[0]}
        for m in x['messages']]} for x in data]))
else:
    print((output / f'{kind}.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
