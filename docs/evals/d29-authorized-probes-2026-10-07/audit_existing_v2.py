"""Offline audit of preserved evidence; no runtime, replay, or new load."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path[:0]=[str(OUT/'revision2'),str(ROOT/'backend')]
from clock_guard import Continuity
from evaluation_provider import verify_wire
from apps.agent.tests.scheduling_characterization.evidence import ClockMap, transactions, Interval, reconstruct
from apps.agent.tests.scheduling_characterization.execution import read_lines

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,indent=2,ensure_ascii=False)

def audit(case,run):
    d=OUT/case.lower()/run
    job=read(d/'participant-plan.json');raw=read(d/'job-result.json');prior=read(d/'independent-verification.json')
    journals=[read_lines(d/(role+'.jsonl')) for role in ('ingress','planner_1','planner_2','sender')]
    clocks={}
    for rows in journals:
        state=Continuity()
        for row in rows:state.feed(row)
        clocks[rows[0]['worker']]=state.finish()
    wire=[r for role in ('planner_1','planner_2','sender') for r in read_lines(d/(role+'-wire.jsonl'))]
    final=next(s for s in reversed(read_lines(d/'snapshots.jsonl')) if s['stage']=='final')
    offers=read_lines(d/'schedule-offers.jsonl')
    reconstructed=reconstruct(journals,offers,final['messages'],Interval(final['db_ns'],final['db_ns']),run_id=run)
    errors=[]
    if reconstructed['episodes']!=raw['episodes'] or reconstructed['population']!=raw['population'] or reconstructed['issues']:
        errors.append('POPULATION_RECONSTRUCTION_MISMATCH')
    effects,unknown=transactions(journals)
    claim_rows=[r for tx in effects for r in tx['rows'] if r['event']=='claim_bound']
    claimed={r['turn_work_id'] for r in claim_rows}
    episode_works={e['turn_work_id'] for e in raw['episodes'] if e['turn_work_id']}
    if not claimed or claimed!=episode_works or claimed!={w['id'] for w in final['works']}:
        errors.append('CLAIM_WORK_POPULATION_UNRECONCILED')
    provider=verify_wire(job,wire,claimed)
    errors+=provider['issues']
    for wid in claimed:
        results=[r for r in wire if r['event']=='result' and r['boundary']=='llm' and r.get('turn_work_id')==wid]
        if len(results)!=2 or {r['call_number'] for r in results}!={1,2} or any(r['elapsed_ns']<500000000 or r['result']!='ACCEPTED' for r in results):
            errors.append('FULL_LLM_SERVICE_MISSING:'+str(wid))
    mapping=[dict(organization_id=e['organization_id'],conversation_id=e['conversation_id'],
        input_ids=e['member_ids'],episode_id=e['episode_id'],work_id=e['turn_work_id'],
        ready=e['ready_ns_bounds'],claim=e['claim_commit_ns_bounds'],wait=e['wait_seconds_bounds']) for e in raw['episodes']]
    result=dict(case_id=case,run_id=run,prior_verification_sha256=hashlib.sha256((d/'independent-verification.json').read_bytes()).hexdigest(),
        job_result_sha256=hashlib.sha256((d/'job-result.json').read_bytes()).hexdigest(),
        clocks=clocks,provider=provider,inputs=len(offers),episodes=len(mapping),works=len(claimed),
        claims=len(claim_rows),commits=len(effects),input_episode_work_mapping=mapping,
        confirmed_base_reference=job['confirmed_base_reference'],base_changed=False,
        historical_attempts_unchanged=True,synthetic_evidence=[],host_events='NOT_CAPTURED_FOR_THIS_ATTEMPT',
        prior_pacing_gate=raw['gates']['demand'],prior_invariants=raw['gates']['invariants'])
    if case=='R1-03':
        guard=read(d.with_name(d.name+'-clock')/'clock-receipt.json')
        result['host_events']=guard
        if not guard['clock_gate_passed']:errors.append('CLOCK_OR_HOST_GATE_FAILED')
    if case=='R2-02':
        orgs=job['organization_ids'];events=raw['scenario_events']
        begin=next(e['db_ns'] for e in events if e['event']=='block_begin')
        end=next(e['db_ns'] for e in events if e['event']=='block_release')
        if end-begin<120000000000:errors.append('HOLD_TOO_SHORT')
        if any(e['organization_id']!=orgs[0] for e in raw['episodes'] if len(e['member_ids'])>1):errors.append('PEER_COALESCING_NOT_AUTHORIZED')
        peer_claims=[e for e in raw['episodes'] if e['organization_id']==orgs[1] and e['claim_commit_ns_bounds'] and begin<e['claim_commit_ns_bounds'][0]<=e['claim_commit_ns_bounds'][1]<end]
        peer_offers=[o for o in offers if o['organization_id']==orgs[1] and begin<o['offered_db_ns_bounds'][0]<=o['offered_db_ns_bounds'][1]<end]
        if not peer_claims or not peer_offers:errors.append('PEER_PROGRESS_OR_OFFER_MISSING')
        if any(len({e['conversation_id'] for e in raw['episodes'] if e['organization_id']==o})!=3 for o in orgs):errors.append('BASE_POPULATION_CHANGED')
        result.update(hold_seconds=(end-begin)/1e9,peer_claims_during_hold=len(peer_claims),peer_offers_during_hold=len(peer_offers),
            coalesced_episodes=[e for e in mapping if len(e['input_ids'])>1])
    if case=='R2-09':
        sender_clock=ClockMap(journals[3]);metas=[r for r in wire if r['boundary']=='meta' and r['event']=='dispatch']
        calls=Counter(m['message_id'] for m in metas)
        if any(n!=1 for n in calls.values()):errors.append('REPEATED_META_DISPATCH')
        observed=[];definite=[];possible=[]
        for m in metas:
            end=next(r for r in wire if r.get('call_id')==m['call_id'] and r['event']=='result')
            start_bounds=[m['monotonic_ns']+sender_clock.offset.lo,m['monotonic_ns']+sender_clock.offset.hi]
            end_bounds=[end['monotonic_ns']+sender_clock.offset.lo,end['monotonic_ns']+sender_clock.offset.hi]
            observed.append(dict(call_id=m['call_id'],fault_id=m['fault_id'],organization_id=m['organization_id'],
                message_id=m['message_id'],sender_role=m['role'],sender_pid=m['os_pid'],
                admission_verified=m['admission_verified'],start_bounds=start_bounds,end_bounds=end_bounds))
            if not m['fault_id']:continue
            for e in raw['episodes']:
                ready=e['ready_ns_bounds'];claim=e['claim_commit_ns_bounds'] or raw['cut_ns_bounds']
                ref=dict(fault_id=m['fault_id'],episode_id=e['episode_id'],organization_id=e['organization_id'])
                if max(ready[1],start_bounds[1])<min(claim[0],end_bounds[0]):definite.append(ref)
                if max(ready[0],start_bounds[0])<min(claim[1],end_bounds[1]):possible.append(ref)
        if not definite:errors.append('PENDING_NATURAL_READY_QUEUE_OVERLAP')
        result.update(meta_calls=observed,definite_ready_overlap=definite,possible_ready_overlap=possible,
            affected_faults=sum(bool(m['fault_id']) for m in metas),no_repeated_meta_dispatch=all(n==1 for n in calls.values()),
            previous_supplement_limitations=['Its claimed_work_ids came from absent job-result.works; this verifier uses committed claim journals.',
                '120-second queue cuts cannot decide subsecond overlap; this audit intersects every episode with every affected Meta interval.'])
    errors+=prior['errors']
    result.update(status='NOT_ACCREDITED' if errors else 'PASS',errors=sorted(set(errors)))
    write(d/'evidence-audit-v2.json',result)
    print(json.dumps({k:result[k] for k in ('case_id','status','inputs','episodes','works','claims','commits','errors')}))

if __name__=='__main__':
    audit('R2-02','authorized-r202-blocked-20261007-0002')
    audit('R2-09','authorized-r209-uncertain-meta-20261007-0002')
