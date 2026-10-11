"""Recheck retained protected evidence after removal of the private labs."""
import hashlib
import json
import subprocess
from pathlib import Path
from inspect_cleanup_v3 import inspect

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    errors = []
    initial = read(OUT/'initial-integrity.json')
    for name, digest in initial['protected_sources'].items():
        p = ROOT/name
        if not p.is_file() or sha(p) != digest:
            errors.append('PROTECTED_SOURCE_CHANGED:'+name)
    previous = read(OUT/'final-integrity-v5.json')
    if previous['status'] != 'PASS' or previous['executed_baseline_python_count'] != 789:
        errors.append('PRE_CLEANUP_EXECUTED_SOURCE_VERIFICATION_NOT_PASS')
    history = []
    for name in ('d29-physical-2026-10-06','d29-frontiers-2026-10-07','d29-r102-base-2026-10-07'):
        directory = ROOT/'docs/evals'/name
        index = read(directory/'artifact-index.json')
        old = next(x for x in previous['historical_evidence'] if x['directory'] == name)
        if sha(directory/'artifact-index.json') != old['index_sha256']:
            errors.append('HISTORICAL_INDEX_CHANGED:'+name)
        for relative, entry in index.items():
            p = directory/relative
            if not p.is_file() or sha(p) != entry['sha256']:
                errors.append('HISTORICAL_RECEIPT_CHANGED:'+name+'/'+relative)
        history.append(dict(directory=name,artifacts=len(index),index_sha256=sha(directory/'artifact-index.json')))
    base_hash = sha(ROOT/'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json')
    if base_hash != '71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56':
        errors.append('CONFIRMED_BASE_CHANGED')
    head = subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    if head != '825db75df68bf076929fa787e77beefe96803350':
        errors.append('BASELINE_HEAD_CHANGED')
    cleanup = read(OUT/'lab-cleanup-v2.json')
    state = inspect()
    if not cleanup['all_owned_labs_removed'] or state['matching_processes'] or any(x['exists'] or not x['port_closed'] for x in state['laboratories']):
        errors.append('OWNED_CLEANUP_INCOMPLETE')
    status = subprocess.check_output(['rtk','proxy','git','status','--short'],cwd=ROOT).decode().splitlines()
    value = dict(status='PASS' if not errors else 'FAIL',errors=errors,head=head,
        protected_source_count=len(initial['protected_sources']),historical_evidence=history,
        confirmed_base_sha256=base_hash,git_status=status,cleanup=state,
        executed_baseline_verification=dict(path='final-integrity-v5.json',sha256=sha(OUT/'final-integrity-v5.json'),
            status=previous['status'],count=789,scope='Verified before cleanup; source archive was intentionally removed with the owned private cluster.'),
        cleanup_receipt_sha256=sha(OUT/'lab-cleanup-v2.json'),no_commits_created=head==previous['head'])
    with (OUT/'closure-integrity-v6.json').open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2)
    print(json.dumps(dict(status=value['status'],errors=errors,head=head,owned_processes_remaining=len(state['matching_processes']))),flush=True)
    if errors:
        raise RuntimeError('Closure integrity failed')

if __name__ == '__main__':
    main()
