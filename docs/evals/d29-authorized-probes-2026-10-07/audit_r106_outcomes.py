"""Read-only reconciliation; does not relax the R1-06 accreditation gates."""
import hashlib
import json
import sys
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from apps.agent.tests.scheduling_characterization.execution import read_lines
from apps.agent.tests.scheduling_characterization.evidence import transactions
d=OUT/'r1-06/authorized-r106-2x4-20261007-0002'
r=json.loads((d/'job-result.json').read_text());f=json.loads((d/'full-durable-final.json').read_text())
j=[read_lines(d/(role+'.jsonl')) for role in ('ingress','planner_1','planner_2','sender')]
tx,unknown=transactions(j)
claims=[event for t in tx for event in t['rows'] if event['event']=='claim_bound']
deferred=[]
for w in f['works']:
    if w['outcome_code']!='deferred_to_new_input':continue
    ep=next(e for e in r['episodes'] if e['turn_work_id']==w['id'])
    following=[e for e in r['episodes'] if e['conversation_id']==w['conversation_id'] and e['claim_commit_ns_bounds'][0]>ep['claim_commit_ns_bounds'][1]]
    following.sort(key=lambda e:e['claim_commit_ns_bounds'][0])
    successor=following[0] if following else None
    outputs=[m for m in f['messages'] if m['direction']=='out' and successor and m['turn_work_id']==successor['turn_work_id']]
    deferred.append(dict(work_id=w['id'],outcome=w['outcome_code'],episode=ep,
        next_episode=successor,successor_outputs=outputs))
v=dict(status='OBSERVATION_ONLY_NOT_ACCREDITATION',run_id=r['run_id'],
    accepted_inputs=32,episodes=len(r['episodes']),works=len(f['works']),claims=len(claims),
    commits_with_population_effects=len(tx),coalesced_episodes=[e for e in r['episodes'] if len(e['member_ids'])>1],
    deferred_works=deferred,outbound_count=sum(m['direction']=='out' for m in f['messages']),
    outbound_all_accepted=all(m['provider_accepted_at'] for m in f['messages'] if m['direction']=='out'),
    unresolved_transactions=unknown,all_works_completed=all(w['status']=='COMPLETED' for w in f['works']),
    gates_unchanged=True,base_changed=False,
    decision_required='Do not inherit the R2-02 coalescing exception. Review the R1-06 load gate and response-obligation reconciliation separately.',
    final_snapshot_sha256=hashlib.sha256((d/'full-durable-final.json').read_bytes()).hexdigest())
with (d/'outcome-reconciliation-v2.json').open('x',encoding='utf-8') as s:json.dump(v,s,indent=2)
print(json.dumps({k:v[k] for k in ('status','accepted_inputs','episodes','works','claims','commits_with_population_effects','outbound_count','outbound_all_accepted')}))
