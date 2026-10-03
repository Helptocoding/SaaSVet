"""Hash the final retained artifacts after privacy cleanup and report generation."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def main():
    target = OUT/'artifact-manifest.json'
    assert not target.exists()
    assert (OUT/'README.md').is_file() and (OUT/'privacy.json').is_file()
    assert json.loads((OUT/'verification-summary.json').read_text())['status']=='OPTIMIZATION_VERIFIED'
    entries=[]
    for path in sorted(OUT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        assert path.suffix != '.log', path
        raw=path.read_bytes()
        raw.decode('utf-8')  # All retained artifacts are text; pyc/binary files are excluded.
        canonical=raw.replace(b'\r\n',b'\n')
        entries.append(dict(path=path.relative_to(OUT).as_posix(),bytes=len(raw),
            canonical_bytes=len(canonical),sha256=hashlib.sha256(canonical).hexdigest(),
            windows_worktree_sha256=hashlib.sha256(raw).hexdigest()))
    document=dict(schema='e4-sql-redesign-artifacts-v1',algorithm='SHA256',
        canonicalization='UTF-8 text with CRLF normalized to LF for portable Git checkout verification',
        manifest_excludes_itself=True,files=entries,
        runtime_tests_commit=json.loads((OUT/'commits.json').read_text())['runtime_tests'])
    target.write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    print('FINAL_MANIFEST_WRITTEN',len(entries))


if __name__=='__main__':
    main()
