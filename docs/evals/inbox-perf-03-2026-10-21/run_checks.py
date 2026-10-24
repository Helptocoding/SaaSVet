"""Build, scoped lint, and read-only migration drift check, with named receipts."""
import json
import os
import subprocess
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
kind = sys.argv[1]
assert not (out/f'{kind}-run.json').exists()
env = os.environ.copy()
env.pop('SENTRY_AUTH_TOKEN', None)
env['SENTRY_DSN'] = ''
command = ['rtk', 'proxy']
cwd = root/'frontend'
if kind == 'build':
    command += ['node', 'node_modules/vite/bin/vite.js', 'build']
elif kind == 'lint':
    command += ['node', 'node_modules/eslint/bin/eslint.js', 'src/pages/inbox/index.jsx',
        'src/pages/inbox/inboxSync.js', 'src/pages/inbox/inboxSync.test.js',
        'src/pages/inbox/index.sync.test.jsx', 'src/pages/inbox/useThreadHistory.js',
        'src/api/inbox.js', '--format=json', '--output-file='+str(out/'lint.json')]
elif kind == 'migration':
    cwd = root/'backend'
    command += ['python', 'manage.py', 'makemigrations', '--check', '--dry-run']
elif kind == 'lint-final':
    command += ['node', 'node_modules/eslint/bin/eslint.js', 'src/pages/inbox/index.jsx',
        'src/pages/inbox/index.test.jsx', 'src/pages/inbox/index.sync.test.jsx',
        '--format=json', '--output-file='+str(out/'lint-final.json')]
else:
    raise ValueError(kind)
with (out/f'{kind}.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
receipt = dict(command=command, exit_code=result.returncode,
    sentry_upload_disabled=True, working_database_migrated=False)
(out/f'{kind}-run.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
print(json.dumps(receipt))
if kind.startswith('lint'):
    print(json.dumps([row for row in json.loads((out/f'{kind}.json').read_text(encoding='utf-8')) if row['messages']]))
raise SystemExit(result.returncode)
