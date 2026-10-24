"""Named directed receipts; never overwrite an earlier run."""
import json
import subprocess
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
tag, *files = sys.argv[1:]
assert tag.replace('-', '').isalnum()
assert not (out/f'vitest-{tag}.json').exists()
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run', *files,
    '--fileParallelism=false', '--reporter=default', '--reporter=json', '--outputFile='+str(out/f'vitest-{tag}.json')]
with (out/f'frontend-{tag}.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root/'frontend', stdout=log, stderr=subprocess.STDOUT, timeout=360)
(out/f'frontend-{tag}-run.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
report = json.loads((out/f'vitest-{tag}.json').read_text(encoding='utf-8'))
print(json.dumps({key: report.get(key) for key in ('numPassedTests', 'numFailedTests', 'numPendingTests', 'success')}, indent=2))
raise SystemExit(result.returncode)
