"""Use original validators with their candidate path rebound to the exact restored tree."""
import json
from pathlib import Path
import sys

out = Path(__file__).resolve().parent
old = out.with_name('b9-correction-20261020-native-r12')
sys.path.insert(0, str(old))
import composite_evidence
import frontend_resumption

frontend_resumption.REPO = out / 'runtime/b9/src'
backend = composite_evidence.validate_references()
frontend = frontend_resumption.validate_frontend_references()
labels = ['directed', 'django-check', 'migration-drift', 'migrate', 'billing-schema',
          'b0', 'b3', 'b4', 'b5', 'full', 'frontend-build', 'frontend-test', 'frontend-smoke-urls']
gates = {label: composite_evidence.read_block(label) for label in labels}
assert all(r['state'] == 'PASS' for r in gates.values())
result = dict(state='PASS', backend=backend, frontend=frontend, gates=gates,
    original_validators_used=True, candidate_path_rebound_only=True,
    original_evidence_modified=False, historical_r12_fail_preserved=True,
    current_backend_test_runs=0, current_frontend_test_runs=0,
    accepted_historical_evidence_limitation=True, continuous_campaign_claimed=False)
(out / 'b9-retained-reference-validation.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print('ORIGINAL_REFERENCE_VALIDATORS_PASS', flush=True)
