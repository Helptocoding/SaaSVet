"""Run only new/affected frontend checks and preserve every attempt."""
import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('kind', choices=['new', 'affected', 'build', 'lint', 'retry'])
parser.add_argument('tag')
parser.add_argument('--pattern')
args = parser.parse_args()
out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / f'{args.kind}-{args.tag}.json'
log = receipt.with_suffix('.log')
assert not receipt.exists() and not log.exists(), 'Never overwrite evidence'
if args.kind in ['new', 'affected', 'retry']:
    report = out / f'{args.kind}-{args.tag}-vitest.json'
    assert not report.exists()
    if args.kind in ['new', 'retry']:
        selected = ['src/pages/inbox/ReplyQuote.test.jsx', 'src/pages/inbox/useThreadHistory.jump.test.jsx',
                    'src/pages/inbox/index.jump.test.jsx']
    else:
        selected = ['src/pages/inbox/useThreadHistory.test.jsx', 'src/pages/inbox/index.replies.test.jsx',
                    'src/pages/inbox/index.sync.test.jsx', 'src/pages/inbox/index.test.jsx', '-t',
                    'WA-HIST-|WA-GTF-01|WA-RPL-05|WA-PERF-03']
    if args.pattern:
        selected += ['-t', args.pattern]
    command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run', *selected,
               '--maxWorkers=1', '--reporter=json', f'--outputFile={report}']
elif args.kind == 'build':
    command = ['rtk', 'npm', 'run', 'build']
else:
    command = ['rtk', 'proxy', 'node', 'node_modules/eslint/bin/eslint.js',
               *['src/pages/inbox/' + name for name in ['index.jsx', 'useThreadHistory.js', 'ReplyQuote.jsx',
                 'ReplyQuote.test.jsx', 'useThreadHistory.jump.test.jsx', 'index.jump.test.jsx']]]
started = time.monotonic()
with log.open('w', encoding='utf-8') as stream:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=stream, stderr=subprocess.STDOUT)
data = dict(kind=args.kind, command=command, exit_code=result.returncode, elapsed_s=time.monotonic() - started,
            working_database_migrated=False)
if args.kind in ['new', 'affected', 'retry'] and report.exists():
    data['vitest_report'] = report.name
    payload = json.loads(report.read_text(encoding='utf-8'))
    data.update(passed=payload['numPassedTests'], failed=payload['numFailedTests'])
receipt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(data, ensure_ascii=False))
print('\n'.join(log.read_text(encoding='utf-8').splitlines()[-16:]))
raise SystemExit(result.returncode)
