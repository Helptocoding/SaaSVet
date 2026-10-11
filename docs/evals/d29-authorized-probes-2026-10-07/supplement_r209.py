import json
from pathlib import Path

base = Path('docs/evals/d29-authorized-probes-2026-10-07/r2-09/authorized-r209-uncertain-meta-20261007-0002')
job = json.loads((base / 'participant-plan.json').read_text())
wire = []
for role in ('planner_1','planner_2','sender'):
    p = base / (role + '-wire.jsonl')
    if p.exists():
        wire.extend(json.loads(line) for line in p.read_text().splitlines())
from pathlib import Path as P
import sys
sys.path.insert(0, str(P('docs/evals/d29-authorized-probes-2026-10-07/orchestration')))
try:
    from evaluation_provider import verify_wire
    claimed = [w['id'] for w in json.loads((base / 'job-result.json').read_text()).get('works', [])]
    provider_gate = verify_wire(job, wire, claimed)
except Exception as exc:
    provider_gate = {'passed': False, 'issues': ['SUPPLEMENTAL_PROVIDER_GATE_ERROR:' + type(exc).__name__]}
result = json.loads((base / 'independent-verification.json').read_text())
raw = json.loads((base / 'job-result.json').read_text())
queues = raw.get('queue_samples', [])
positive = []
for cut in queues:
    counts = cut.get('counts', {})
    if any(any(v > 0 for v in pair) for key, pair in counts.items() if isinstance(pair, list)):
        positive.append(cut)
queue_gate = {'observed': bool(positive), 'positive_cuts': positive, 'required': 'READY_QUEUE_CONCURRENT_WITH_UNCERTAIN_META'}
result['supplemental_provider_gate'] = provider_gate
result['supplemental_ready_queue_gate'] = queue_gate
if not provider_gate.get('passed', False) or not queue_gate['observed']:
    result['status'] = 'NOT_ACCREDITED'
    result['verifier_passed'] = False
    result.setdefault('errors', [])
    if not provider_gate.get('passed', False):
        result['errors'].append('PROVIDER_WIRE_SUPPLEMENTAL_GATE_FAILED')
    if not queue_gate['observed']:
        result['errors'].append('READY_QUEUE_CONCURRENT_NOT_OBSERVED')
    result['pending_reason'] = 'PENDING_NATURAL_READY_QUEUE_OVERLAP' if not queue_gate['observed'] else None
(base / 'authorized-final-receipt.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({'status':result['status'],'queue_observed':queue_gate['observed'],'provider_gate':provider_gate}, ensure_ascii=False))
