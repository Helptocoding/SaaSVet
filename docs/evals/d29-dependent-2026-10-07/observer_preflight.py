"""Negative verification checks; these are not physical accreditation."""
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
_,state=lab['session']()
sys.path[:0]=[state['orchestration'],str(Path(state['copy'])/'backend')]
import causal_observations
from apps.agent.tests.scheduling_characterization.execution import read_capture,read_lines

directory=HERE/'individual/individual-R104-forecasts'
job=lab['read'](directory/'participant-plan.json')
report=lab['read'](directory/'job-result.json')
journals=read_capture(directory)
events,missing=causal_observations.observe(job,report,journals,directory)
checks={'old_ordinary_capture_cannot_supply_missing_prequery_witnesses':
    not events and set(missing['errors'])=={
        'PRE_QUERY_WITNESS_COVERAGE_INCOMPLETE:planner_1',
        'PRE_QUERY_WITNESS_COVERAGE_INCOMPLETE:planner_2'}}
role=next(j for j in journals if j[0]['worker']=='planner_1')
selected=next(r for r in role if r['event']=='selection_result')
final=read_lines(directory/'snapshots.jsonl')[-1]
forged=dict(run_id=job['run_id'],role='planner_1',os_pid=role[0]['os_pid'],
    selection_id=selected['selection_id'],pre_query=final,post_query=final,
    actual_selected_conversations=selected['conversation_ids'],
    other_participants_held=False,extra_ingress_generated=False,claim_miss_asserted=False)
with patch.object(causal_observations,'read_lines',lambda p:[forged] if p.name.startswith('planner_1') else []):
    events,later=causal_observations.observe(job,report,journals,directory)
checks['later_census_cannot_replace_prequery_cut']=not events and 'PRE_QUERY_ORDER_OR_ACTUAL_RESULT_INVALID:planner_1' in later['errors']
result=dict(status='PASS' if all(checks.values()) else 'FAIL',checks=checks,
    scope='NEGATIVE_VERIFIER_REGRESSION_NOT_PHYSICAL_ACCREDITATION',
    source_receipt_sha256=lab['sha'](directory/'job-result.json'),
    evaluator_sha256=lab['sha'](Path(state['orchestration'])/'causal_observations.py'))
lab['write'](HERE/'causal-observer-preflight.json',result)
print(result,flush=True)
raise SystemExit(0 if all(checks.values()) else 1)
