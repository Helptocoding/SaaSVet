"""Verify the delivered hash index without rewriting preserved receipts."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    errors = []
    index = read(OUT/'artifact-index-v2.json')
    actual = {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file() and p.name!='artifact-index-v2.json' and '__pycache__' not in p.parts}
    if actual != set(index):
        errors.append('INDEX_FILESET_MISMATCH')
    for relative, entry in index.items():
        p = OUT/relative
        if not p.is_file() or p.stat().st_size!=entry['bytes'] or sha(p)!=entry['sha256']:
            errors.append('ARTIFACT_CHANGED:'+relative)
    result = read(OUT/'final-phase-receipt.json')
    expected = {'R1-03':'PASS','R1-06':'NOT_ACCREDITED','R2-02':'PASS','R2-04':'INVALID_RUN','R2-09':'NOT_ACCREDITED'}
    for case in result['scenarios']:
        if case['status']!=expected[case['case_id']]:
            errors.append('UNEXPECTED_SCENARIO_STATUS:'+case['case_id'])
        if sha(OUT/case['receipt_path'])!=case['receipt_sha256']:
            errors.append('SCENARIO_RECEIPT_HASH_MISMATCH:'+case['case_id'])
    for name in ('integrity_receipt','final_integrity_receipt','closure_integrity_receipt','cleanup_receipt'):
        ref = result[name]
        if sha(OUT/ref['path'])!=ref['sha256']:
            errors.append('REFERENCE_HASH_MISMATCH:'+name)
    if result['state']!='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY' or result['full_matrix_executed'] or result['commits_created']:
        errors.append('UNAUTHORIZED_STATE_TRANSITION')
    if result['regression']['d29']['status']!='PASS' or result['regression']['application']['status']!='INCOMPLETE_INFRASTRUCTURE':
        errors.append('REGRESSION_STATUS_MISMATCH')
    if any(Path(p).name=='session.json' for p in index):
        errors.append('PRIVATE_SESSION_FILE_INCLUDED')
    print(json.dumps(dict(status='PASS' if not errors else 'FAIL',artifacts=len(index),errors=errors)),flush=True)
    if errors:
        raise RuntimeError('Final package verification failed')

if __name__ == '__main__':
    main()
