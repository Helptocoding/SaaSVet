"""Distinguish existing checkout CRLF from byte-identical executed archive."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
prior=read(OUT/'integrity-audit-v2.json')
task=Path(read(OUT/'environment.json')['task']);state=read(task/'session.json')
copy=Path(state['copy'])
exact_mismatches=[];checkout_content_mismatches=[];checkout_crlf_only=[];count=0
with zipfile.ZipFile(task/'baseline.zip') as z:
    for name in z.namelist():
        if not name.startswith('backend/') or not name.endswith('.py'):continue
        count+=1;expected=z.read(name);actual=(copy/name).read_bytes()
        if actual!=expected:exact_mismatches.append(name)
        workspace=(ROOT/name).read_bytes()
        if workspace!=expected:
            if workspace.replace(b'\r\n',b'\n')==expected:checkout_crlf_only.append(name)
            else:checkout_content_mismatches.append(name)
diff=subprocess.check_output(['rtk','proxy','git','diff','--name-only',prior['baseline'],'--','backend'],cwd=ROOT).decode().splitlines()
out=dict(prior,tracked_backend_python_count=count,
    executed_archive_python_mismatches=exact_mismatches,
    checkout_CRLF_only_paths=checkout_crlf_only,checkout_other_content_mismatches=checkout_content_mismatches,
    git_backend_diff_paths=diff,
    clarification='v2 compared raw LF archive against the existing CRLF checkout. These are reported byte differences, not edits by this phase. Execution used the LF archive; prior protected-source bytes are unchanged.',
    runtime_and_history_intact=not (exact_mismatches or checkout_content_mismatches or diff or prior['initial_protected_source_mismatches'] or prior['historical_evidence_mismatches']) and prior['baseline_head_unchanged'])
with (OUT/'integrity-audit-v3.json').open('x',encoding='utf-8') as f:json.dump(out,f,indent=2)
print(json.dumps(dict(checked=count,executed_archive_mismatches=exact_mismatches,checkout_crlf_only=len(checkout_crlf_only),
    other_checkout_mismatches=checkout_content_mismatches,git_backend_diff=diff,prior_protected_mismatches=prior['initial_protected_source_mismatches'],
    historical_evidence_mismatches=prior['historical_evidence_mismatches'],runtime_and_history_intact=out['runtime_and_history_intact'])))
