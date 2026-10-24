"""Only exact verified historical fingerprints; no path/value/rule exclusions."""
import hashlib
import json
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
target = root / '.gitleaksignore'
assert not target.exists()
source = out / 'security-classification.json'
classification = json.loads(source.read_text(encoding='utf-8'))
assert classification['status'] == 'CLASSIFIED_FALSE_POSITIVE_CONTEXTS'
assert classification['total'] == 3156
fingerprints = [item['fingerprint'] for item in classification['findings']]
assert len(set(fingerprints)) == 3156
assert all(len(item.split(':')[0]) == 40 and ':generic-api-key:' in item for item in fingerprints)
lines = ['# Verified historical non-credentials only: exact commit/file/rule/line.',
    '# No wildcards, whole-directory exclusions or rule disablement.',
    '# Evidence: docs/evals/inbox-readiness-2026-10-22/security-classification.json',
    '# The original B9 r12 FAIL is preserved. New fingerprints are still scanned.']
target.write_text('\n'.join([*lines, *sorted(fingerprints)])+'\n', encoding='utf-8')
result = dict(status='PREPARED_NOT_YET_SCANNED', fingerprints=len(fingerprints),
    policy_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    classification_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    toml_configuration_changed=False, default_rules_disabled=False, historical_r12_gate_changed=False)
(out / 'security-policy.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
