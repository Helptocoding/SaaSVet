"""Finite frontend checks; preserve each receipt and log without overwriting."""
import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('kind', choices=['new', 'affected', 'boundary', 'build', 'lint'])
parser.add_argument('tag')
args = parser.parse_args()
out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / f'{args.kind}-{args.tag}.json'
log = receipt.with_suffix('.log')
assert not receipt.exists() and not log.exists(), 'Never overwrite evidence'
if args.kind in ['new', 'affected', 'boundary']:
    report = out / f'{args.kind}-{args.tag}-vitest.json'
    assert not report.exists()
    selected = (['src/pages/inbox/index.replies.test.jsx', 'src/api/inbox.test.js',
                 '-t', 'WA-RPL-05|sendInboxMessage'] if args.kind == 'new' else
                ['src/pages/inbox/index.test.jsx', '-t',
                 'Inbox — aislamiento del borrador|WA-CMP-01|WA-CPY-01'])
    if args.kind == 'boundary':
        selected = ['src/pages/inbox/index.replies.test.jsx', '-t', 'si vence la ventana después de seleccionar']
    command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run', *selected,
               '--maxWorkers=1', '--reporter=json', f'--outputFile={report}']
elif args.kind == 'build':
    command = ['rtk', 'npm', 'run', 'build']
else:
    command = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js',
               'src/api/inbox.js', 'src/api/inbox.test.js', 'src/pages/inbox/index.jsx',
               'src/pages/inbox/index.replies.test.jsx']
started = time.monotonic()
with log.open('w', encoding='utf-8') as stream:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=stream, stderr=subprocess.STDOUT)
data = dict(kind=args.kind, command=command, exit_code=result.returncode,
            elapsed_s=time.monotonic() - started, working_database_migrated=False)
if args.kind in ['new', 'affected', 'boundary'] and report.exists():
    data['vitest_report'] = report.name
    payload = json.loads(report.read_text(encoding='utf-8'))
    data['passed'] = payload['numPassedTests']
    data['failed'] = payload['numFailedTests']
receipt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(data, ensure_ascii=False))
print('\n'.join(log.read_text(encoding='utf-8').splitlines()[-16:]))
raise SystemExit(result.returncode)
