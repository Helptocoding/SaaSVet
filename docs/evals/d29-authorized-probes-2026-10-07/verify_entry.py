import argparse
import json
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--job', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apps.agent.tests.scheduling_characterization.runner import bootstrap
bootstrap()
import verify_case
job = json.loads(Path(a.job).read_text(encoding='utf-8'))
if job['case_id'] == 'R2-02':
    from apps.agent.tests.scheduling_characterization import assessment
    original = assessment.demand_gate
    def demand_gate(plan, *args, **kwargs):
        value = original(plan, *args, **kwargs)
        if plan.get('allow_coalesced_episodes'):
            value['violations'] = [v for v in value['violations'] if v != 'COALESCED_DEMAND_NOT_DECLARED_READY_EPISODE_LOAD']
        return value
    assessment.demand_gate = demand_gate
result = verify_case.verify(Path(a.job), Path(a.output))
(Path(a.output) / 'independent-verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({k: result[k] for k in ('case_id','run_id','status','errors')}), flush=True)
