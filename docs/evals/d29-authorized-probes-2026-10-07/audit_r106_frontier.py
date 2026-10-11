"""Accredit the finite backlog frontier separately from the pending load gate."""
import json
import sys
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from apps.agent.tests.scheduling_characterization.execution import read_lines
from apps.agent.tests.scheduling_characterization.evidence import Interval,reconstruct,transactions
d=OUT/'r1-06/authorized-r106-2x4-20261007-0002'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
journals=[read_lines(d/(role+'.jsonl')) for role in ('ingress','planner_1','planner_2','sender')]
pre=next(s for s in read_lines(d/'snapshots.jsonl') if s['stage']=='backlog_ready_before_workers')
offers=read_lines(d/'schedule-offers.jsonl');backlog=[o for o in offers if o['phase']=='BACKLOG']
before=reconstruct(journals,backlog,pre['messages'],Interval(pre['db_ns'],pre['db_ns']),run_id=d.name)
after=read(d/'job-result.json');full=read(d/'full-durable-final.json');slots=read_lines(d/'population-slots.jsonl')
effects,unknown=transactions(journals)
claims=[(tx,r) for tx in effects for r in tx['rows'] if r['event']=='claim_bound']
originals=[]
for ep in before['episodes']:
    later=next(e for e in after['episodes'] if ep['member_ids'][0] in e['member_ids'])
    originals.append(dict(input_id=ep['member_ids'][0],organization_id=ep['organization_id'],conversation_id=ep['conversation_id'],
        ready_before=ep['ready_ns_bounds'],ready_final=later['ready_ns_bounds'],same_origin=ep['ready_ns_bounds']==later['ready_ns_bounds'],
        final_members=later['member_ids'],work_id=later['turn_work_id'],claim=later['claim_commit_ns_bounds']))
fourth=[s['message_id'] for s in slots if s['scenario_only']]
checks=dict(eight_natural_ready_before_start=len(before['episodes'])==8 and before['summary']['PENDING_CENSORED']==8 and not before['issues'],
    four_conversations_each=sorted(before['organization_counts'].values())==[4,4],
    no_claim_before_cut=bool(claims) and min(tx['commit'].lo for tx,r in claims)>pre['db_ns'],
    origins_preserved=all(o['same_origin'] for o in originals),
    ordinary_rotation_three=[s['slot'] for s in slots if s['phase']=='ORDINARY']==[i%3 for i in range(24)],
    fourth_only_backlog=len(fourth)==2 and all(s['phase']=='BACKLOG' for s in slots if s['scenario_only']),
    all_inbounds_assigned=all(m['turn_work_id'] for m in full['messages'] if m['direction']=='in'),
    all_works_completed=all(w['status']=='COMPLETED' for w in full['works']),
    all_created_outputs_accepted=all(m['provider_accepted_at'] for m in full['messages'] if m['direction']=='out'),
    clocks_valid=read(d.with_name(d.name+'-clock')/'clock-receipt.json')['gate_passed'],
    invariants_valid=not after['gates']['invariants']['missing'] and not after['gates']['invariants']['violations'])
v=dict(physical_frontier='PASS' if all(checks.values()) else 'NOT_ACCREDITED',load_condition='NOT_ACCREDITED',
    overall_status='NOT_ACCREDITED',checks=checks,original_backlog=originals,fourth_conversation_input_ids=fourth,
    pre_start_cohort=before,base_changed=False,
    pending='Scenario-wide coalescing and superseded-response gate interpretation is not authorized by the R2-02-specific exception.')
with (d/'backlog-frontier-audit-v2.json').open('x',encoding='utf-8') as f:json.dump(v,f,indent=2)
print(json.dumps(dict(physical_frontier=v['physical_frontier'],load_condition=v['load_condition'],checks=checks)))
