"""Full Astro build of the existing private review copy; original landing read-only."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / 'landing-build.json'
assert not receipt.exists() and not receipt.with_suffix('.log').exists()
work = root / 'docs/evals/inbox-b2-guarantees-2026-10-22/runtime/landing-review/frontend'
assert (work / 'node_modules/astro/astro.js').is_file()
original = Path('C:/Users/LAP/Desktop/LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro')
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
before = digest(original)
assert before == json.loads((out/'preparation.json').read_text())['original_landing_sha256']
draft = root / 'docs/compliance/inbox-privacy-review-2026-10-23/aviso-de-privacidad.astro'
shutil.copy2(draft, work/'src/pages/aviso-de-privacidad.astro')
# Reuse installed dependencies; no package installs, original repo writes or deploy.
env = {k:v for k,v in os.environ.items() if k.upper() in
    {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC'}}
env.update(ASTRO_TELEMETRY_DISABLED='1', CI='true', NODE_ENV='production')
args = ['rtk', 'proxy', shutil.which('node'), str(work/'node_modules/astro/astro.js'), 'build']
started = time.monotonic()
with receipt.with_suffix('.log').open('xb') as log:
    process = subprocess.run(args, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
html = work/'dist/aviso-de-privacidad/index.html'
if not html.exists():
    html = work/'dist/aviso-de-privacidad.html'
rendered = re.sub('<[^>]+>', ' ', html.read_text(encoding='utf-8')) if html.exists() else ''
rendered = ' '.join(rendered.split())
clauses = {v:v in rendered for v in ('180 días naturales', 'siete días naturales', 'completarse y verificarse',
    'bloques físicos internos', 'restablecer accesos expirados o revocados', 'Meta', 'Backblaze')}
result = dict(state='PASS' if process.returncode == 0 and all(clauses.values()) and before == digest(original) else 'FAIL',
    exit_code=process.returncode, elapsed_s=round(time.monotonic()-started,3), clauses=clauses,
    built_pages=sorted(p.relative_to(work/'dist').as_posix() for p in (work/'dist').rglob('*.html')),
    draft_sha256=digest(draft), original_landing_sha256=digest(original), original_landing_unchanged=before == digest(original),
    dependencies_reused=True, published=False, legal_seed_executed=False, https_verified=False)
receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result['state']=='PASS' else 1)
