"""Only HIST-01 and transcript regressions directly affected by the state split."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = 'estado acumulativo del historial|explica el turno y habilita|umbral del viewport'
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx', 'src/pages/inbox/useThreadHistory.test.jsx',
           'src/pages/inbox/ThreadViewport.test.jsx', 'src/api/inbox.test.js',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest-repaired.json')]
with (output / 'frontend-repaired.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log,
                            stderr=subprocess.STDOUT, timeout=180)
(output / 'frontend-repaired-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New HIST-01 and affected transcript/send/viewport regressions'},
    indent=2), encoding='utf-8')
print((output / 'frontend-repaired.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
