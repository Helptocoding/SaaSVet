"""Run only copy/link and directly affected Inbox render regressions, without pnpm.cmd."""
import json
import subprocess
from pathlib import Path

output = Path(__file__).resolve().parent
root = output.parents[2]
pattern = ('WA-CPY-01.*(copia el cuerpo|muestra un error|maneja clipboard|renderiza enlaces)|WA-GRP-01|pinta el envío|integra recibos|'
           ''
           'conserva el optimista|oculta failed-local')
command = ['rtk', 'proxy', 'node', 'node_modules/vitest/vitest.mjs', 'run',
           'src/pages/inbox/index.test.jsx',
           '--testNamePattern=' + pattern, '--reporter=default', '--reporter=json',
           '--outputFile=' + str(output / 'vitest.json')]
with (output / 'frontend.log').open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root / 'frontend', stdout=log, stderr=subprocess.STDOUT,
                            timeout=180)
(output / 'frontend-run.json').write_text(json.dumps({'exit_code': result.returncode,
    'command': command, 'scope': 'New copy/link tests, grouping render and directly affected optimistic regressions only'}, indent=2), encoding='utf-8')
print((output / 'frontend.log').read_text(encoding='utf-8'))
raise SystemExit(result.returncode)
