"""Read-only small technical inventory; no job execution."""
import json
from common import PRIOR, read

for path in sorted(PRIOR.rglob('participant-plan.json')):
    v=read(path)
    if v.get('case_id')=='R2-09':
        print(str(path.relative_to(PRIOR)),json.dumps({k:v.get(k) for k in ('run_id','variant','slow_multiplier','offer_seconds','followup_seconds','confirmed_base_reference','conversations_per_org','organization_ids')}))
for path in sorted(PRIOR.rglob('artifact-index*.json')):
    if path.parent==PRIOR:
        v=read(path)
        print(path.name, type(v).__name__,len(v),list(v)[:4])
path=PRIOR/'recovered-labs/vet-d29-authorized-20261007-03e5n2jy'
print('recovered_lab_files', sorted(str(p.relative_to(path)) for p in path.iterdir()))
