"""Actual slot-conformance inventory; no new rate, workload or characterization."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def lines(p):return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
results=[]
for case,run in [('r1-03','authorized-r103-unequal-20261007-0002'),('r1-06','authorized-r106-2x4-20261007-0002'),
    ('r2-02','authorized-r202-blocked-20261007-0002'),('r2-04','authorized-r204-postcommit-base-20261007-0004'),
    ('r2-09','authorized-r209-uncertain-meta-20261007-0002')]:
    d=OUT/case/run;job=read(d.parent/(run+'-plan.json'));slots=read(d/'schedule.json')
    attempts=[o for o in lines(d/'schedule-offers.jsonl') if o['phase']=='ORDINARY']
    byslot=defaultdict(list)
    for o in attempts:byslot[o['schedule_id']].append(o)
    observation=[];issues=[]
    for slot in slots:
        values=byslot.pop(slot['id'],[])
        if len(values)!=1:
            issues.append('MISSING_OR_DUPLICATE_SLOT:'+slot['id']);continue
        o=values[0];conforms=slot['due_monotonic_ns']<=o['started_monotonic_ns']<slot['end_monotonic_ns'] and o['outcome']=='ACCEPTED_DURABLE'
        if not conforms:issues.append('PACING_SLOT_OR_ACCEPTANCE_FAILED:'+slot['id'])
        observation.append(dict(slot_id=slot['id'],organization_id=o['organization_id'],message_id=o['message_id'],
            planned_start_ns=slot['due_monotonic_ns'],planned_end_ns=slot['end_monotonic_ns'],
            actual_start_ns=o['started_monotonic_ns'],actual_finish_ns=o['finished_monotonic_ns'],
            committed_offer_db_ns_bounds=o['offered_db_ns_bounds'],
            lateness_seconds=(o['started_monotonic_ns']-slot['due_monotonic_ns'])/1e9,conforms=conforms))
    if byslot:issues.append('UNPLANNED_SLOTS')
    r=dict(case=case.upper(),run_id=run,status='NOT_EXECUTED_CLOCK_INVALID' if case=='r2-04' else 'PASS' if not issues else 'NOT_ACCREDITED',
        offer_seconds=job['offer_seconds'],confirmed_base_rates=job['confirmed_base_rates'],
        declared_scenario_rates=job['offered_rates_per_minute'],scheduled_slots=len(slots),observed_ordinary_attempts=len(attempts),
        max_observed_slot_lateness_seconds=max((o['lateness_seconds'] for o in observation),default=None),
        observations=observation,issues=issues,
        schedule_sha256=hashlib.sha256((d/'schedule.json').read_bytes()).hexdigest(),
        role='Pacing conformance of preserved physical offers; no calculation of E or capacity.')
    results.append(r)
with (OUT/'pacing-audit.json').open('x',encoding='utf-8') as f:json.dump(dict(results=results),f,indent=2)
print(json.dumps([{k:r[k] for k in ('case','status','scheduled_slots','observed_ordinary_attempts','max_observed_slot_lateness_seconds')} for r in results]))
