"""Recheck protected bytes after regression, immediately before closing lab."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial=read(OUT/'initial-integrity.json')
task=Path(read(OUT/'environment.json')['task']);state=read(task/'session.json');copy=Path(state['copy'])
errors=[];checked=0
for name,h in initial['protected_sources'].items():
    p=ROOT/name
    if not p.is_file() or sha(p)!=h:errors.append('PROTECTED_SOURCE_CHANGED:'+name)
with zipfile.ZipFile(task/'baseline.zip') as z:
    for name in z.namelist():
        if name.startswith('backend/') and name.endswith('.py'):
            checked+=1
            if not (copy/name).is_file() or (copy/name).read_bytes()!=z.read(name):errors.append('EXECUTED_BASELINE_SOURCE_CHANGED:'+name)
history=[]
for name in ('d29-physical-2026-10-06','d29-frontiers-2026-10-07','d29-r102-base-2026-10-07'):
    directory=ROOT/'docs/evals'/name;index=read(directory/'artifact-index.json')
    for p,entry in index.items():
        if not (directory/p).is_file() or sha(directory/p)!=entry['sha256']:errors.append('HISTORICAL_RECEIPT_CHANGED:'+name+'/'+p)
    history.append(dict(directory=name,artifacts=len(index),index_sha256=sha(directory/'artifact-index.json')))
head=subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
if head!='825db75df68bf076929fa787e77beefe96803350':errors.append('BASELINE_HEAD_CHANGED')
status=subprocess.check_output(['rtk','proxy','git','status','--short'],cwd=ROOT).decode().splitlines()
value=dict(status='PASS' if not errors else 'FAIL',errors=errors,head=head,
    baseline_preserved=True if head=='825db75df68bf076929fa787e77beefe96803350' else False,
    executed_baseline_python_count=checked,historical_evidence=history,
    confirmed_base_sha256=sha(ROOT/'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'),
    original_protected_manifest_sha256=sha(OUT/'initial-integrity.json'),git_status=status,
    phase_changes_scope='docs/evals/d29-authorized-probes-2026-10-07 evaluation only; unrelated prior changes retained',
    no_commits=True,production_configuration_modified=False)
with (OUT/'final-integrity-v5.json').open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
print(json.dumps({k:value[k] for k in ('status','errors','head','executed_baseline_python_count','confirmed_base_sha256')}))
