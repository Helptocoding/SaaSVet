"""Validate captured source inventories and pre-launch revision2 seals."""
import hashlib
import json
import zipfile
from pathlib import Path

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
task=Path(read(OUT/'environment.json')['task'])
expected={}
with zipfile.ZipFile(task/'baseline.zip') as z:
    for name in z.namelist():
        if name.startswith('backend/') and name.endswith('.py'):
            expected[name.removeprefix('backend/')]=hashlib.sha256(z.read(name)).hexdigest()
frozen=read(OUT/'frozen-sources.json')
for name,h in frozen.items():
    if name.startswith('backend/') and name.endswith('.py'):expected[name.removeprefix('backend/')]=h
results=[]
for case,run in [('r1-03','authorized-r103-unequal-20261007-0002'),
    ('r1-06','authorized-r106-2x4-20261007-0002'),('r2-02','authorized-r202-blocked-20261007-0002'),
    ('r2-04','authorized-r204-postcommit-base-20261007-0004'),('r2-09','authorized-r209-uncertain-meta-20261007-0002')]:
    d=OUT/case/run;manifest=read(d/'source-manifest.json')['backend_source_sha256']
    mismatches=[p for p,h in expected.items() if manifest.get(p)!=h]
    unexpected=[p for p in manifest if p not in expected]
    plan=read(d.parent/(run+'-plan.json'))
    seal=plan.get('evaluation_source_hashes')
    script_errors=[n for n,h in (seal or {}).items() if not (OUT/'revision2'/n).is_file() or sha(OUT/'revision2'/n)!=h]
    results.append(dict(case=case.upper(),run_id=run,expected_backend_sources=len(expected),
        captured_backend_sources=len(manifest),backend_mismatches=mismatches,unexpected_sources=unexpected,
        revision2_prelaunch_seal_present=seal is not None,revision2_script_mismatches=script_errors,
        source_manifest_sha256=sha(d/'source-manifest.json'),plan_sha256=sha(d.parent/(run+'-plan.json')),
        source_integrity_passed=not (mismatches or unexpected or script_errors)))
result=dict(results=results,all_captured_backend_sources_intact=all(r['source_integrity_passed'] for r in results),
    original_orchestration_seal=read(OUT/'orchestration-seal.json'),
    limitation='Earlier orchestration seal was empty; captured backend bytes and accepted base remain verifiable. Closure recovery does not repair that missing prior seal.')
with (OUT/'probe-source-audit.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(result))
