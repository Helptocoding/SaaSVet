"""Verify exact evidence bytes and protected sources in the index or HEAD."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--index', action='store_true')
args = parser.parse_args()
result = json.loads((ROOT/'docs/evals/w1-mono/acceptance-results.json').read_text(encoding='utf-8'))
validation = json.loads((ROOT/'docs/evals/w1-mono/validation.json').read_text(encoding='utf-8'))
prefix = ':' if args.index else 'HEAD:'
expected = result['artifact_sha256']
protected = validation['protected_sources_unchanged_lf_sha256']
refs = [prefix+path for path in expected]
refs += [cut+':'+path for cut in (result['baseline'], 'HEAD') for path in protected]
raw = subprocess.run(['rtk', 'proxy', 'git', 'cat-file', '--batch'], cwd=ROOT,
    input=('\n'.join(refs)+'\n').encode(), capture_output=True, check=True).stdout
position = 0
blobs = []
for ref in refs:
    end = raw.index(b'\n', position)
    header = raw[position:end].split()
    assert len(header) == 3 and header[1] == b'blob', (ref, header)
    size = int(header[2])
    blob = raw[end+1:end+1+size]
    assert len(blob) == size and raw[end+1+size:end+2+size] == b'\n'
    blobs.append(blob)
    position = end+size+2
assert position == len(raw)
for (path, sha), blob in zip(expected.items(), blobs):
    assert hashlib.sha256(blob).hexdigest() == sha, path
offset = len(expected)
for cut in (result['baseline'], 'HEAD'):
    for path, sha in protected.items():
        assert hashlib.sha256(blobs[offset].replace(b'\r\n', b'\n')).hexdigest() == sha, (cut,path)
        offset += 1
if args.index:
    staged = subprocess.run(['rtk', 'proxy', 'git', 'diff-index', '--cached', '--name-only', 'HEAD'],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    own = {'.gitattributes', 'docs/modules/agent.md',
        'docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md',
        'docs/runbooks/agent-whatsapp.md',
        'docs/implementacion-elegibilidad-monotonica-preclaim-2026-09-30.md'}
    assert all(path in own or path.startswith('docs/evals/w1-mono') for path in staged), staged
    assert set(validation['preexisting_changes_excluded']).isdisjoint(staged)
assert result['accepted_unique_total'] == 758 and len(result['new_ids']) == 33
assert result['acceptance_profile_runs'] == 0
print(json.dumps(dict(revision='index' if args.index else 'HEAD',
    verified_evidence_blobs=len(expected), protected_sources=len(protected),
    accepted_unique_ids=758, acceptance_profile_runs=0)))
