"""Read-only baseline/history integrity inventory, no blanket clean-tree claim."""
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
BASE='825db75df68bf076929fa787e77beefe96803350'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def audit():
    previous=read(OUT/'initial-integrity.json')
    differences=[]
    for name,h in previous['protected_sources'].items():
        p=ROOT/name
        if not p.exists() or sha(p)!=h:differences.append(name)
    evidence=[];historical={}
    for name in ('d29-physical-2026-10-06','d29-frontiers-2026-10-07','d29-r102-base-2026-10-07'):
        directory=ROOT/'docs/evals'/name;index=read(directory/'artifact-index.json')
        for path,entry in index.items():
            p=directory/path
            if not p.exists() or sha(p)!=entry['sha256']:evidence.append(name+'/'+path)
        historical[name]=dict(count=len(index),index_sha256=sha(directory/'artifact-index.json'))
    archive=subprocess.check_output(['rtk','proxy','git','archive','--format=tar',BASE,'backend'],cwd=ROOT)
    source_errors=[];count=0
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        for member in t.getmembers():
            if member.isfile() and member.name.endswith('.py'):
                count+=1;p=ROOT/member.name
                expected=hashlib.sha256(t.extractfile(member).read()).hexdigest()
                if not p.exists() or sha(p)!=expected:source_errors.append(member.name)
    head=subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    result=dict(baseline=BASE,head=head,baseline_head_unchanged=head==BASE,
        tracked_backend_python_count=count,tracked_backend_python_mismatches=source_errors,
        initial_protected_source_mismatches=differences,historical_evidence_mismatches=evidence,
        historical_indexes=historical,confirmed_base_sha256=sha(ROOT/'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'),
        runtime_and_history_intact=head==BASE and not source_errors and not evidence,
        whole_workspace_clean=False,unrelated_existing_changes_preserved=['DEPLOY_VPS_PLAN.md','DEPLOY_VPS_STATUS.md','skills-lock.json'])
    with (OUT/'integrity-audit-v2.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='historical_indexes'}))

if __name__=='__main__':audit()
