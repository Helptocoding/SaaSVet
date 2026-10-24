"""Check final sources and whitespace without rewriting the composite manifest."""
import hashlib
import json
from pathlib import Path
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
destination = out/'final-checks.json'
assert not destination.exists()
manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
assert manifest['status'] == 'PASS'
hashes = {}
whitespace_only = []
for path, tested_hash in manifest['source_sha256'].items():
    data = (root/path).read_bytes()
    current_hash = hashlib.sha256(data).hexdigest()
    if current_hash != tested_hash:
        assert path == 'frontend/src/pages/inbox/inbox.module.css'
        assert hashlib.sha256(data+b'\r\n').hexdigest() == tested_hash
        whitespace_only.append(dict(path=path, change='Removed one empty line at EOF after diff check'))
    hashes[path] = current_hash
paths = list(hashes) + ['docs/CIERRE-INBOX-WHATSAPP.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md',
    'docs/modules/agent.md', 'docs/modules/frontend.md', 'CHANGELOG.md']
command = ['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths]
result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
assert result.returncode == 0, result.stdout+result.stderr
for path in paths:
    hashes[path] = hashlib.sha256((root/path).read_bytes()).hexdigest()
destination.write_text(json.dumps(dict(status='PASS', composite_manifest='manifest.json',
    backend_unique_pass=20, frontend_unique_pass=25, source_sha256=hashes,
    whitespace_only_after_test=whitespace_only,
    diff_check=dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr),
    working_database_migrated=False, real_reception_meta='POSTPONED_PENDING'),
    indent=2, ensure_ascii=False), encoding='utf-8')
print('PASS: final source hashes, composite 20 API / 25 frontend, diff check and cleanup receipts')
