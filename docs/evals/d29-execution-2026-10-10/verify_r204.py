"""Offline R2-04 evidence verifier; planned times never prove overlap."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from load_case import validate_base
from reclaim_fixture import base_plan, anchor_window, verify_overlap
from evaluation_provider import verify_wire
from clock_guard import Continuity
from apps.agent.claim_diagnostic_report import read_journal
from apps.agent.tests.scheduling_characterization.evidence import NS, Interval, ClockMap, reconstruct, transactions, timestamp
from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.assessment import demand_gate, invariant_gate, window_gate
from apps.agent.tests.scheduling_characterization.physical import same_history
from apps.agent.tests.scheduling_characterization.runner import write_json

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def verify(job,d):
    errors=[];receipt=dict(status='NOT_ACCREDITED',case_id='R2-04',run_id=job['run_id'],
        confirmed_base_reference=job['confirmed_base_reference'],synthetic_evidence=[],physical_evidence=[],
        base_recalibrated=False,new_base_generated=False,characterization=False)
    clock=read(d.with_name(d.name+'-clock')/'clock-receipt.json')
    receipt['clock']=clock
    if not clock['gate_passed']:
        return dict(receipt,status='INVALID_RUN',errors=['CLOCK_OR_CAPTURE_INVALID'],execution=read(d/'execution-receipt-v2.json'))
    done=read(d/'execution-receipt-v2.json')
    if done['error']:
        return dict(receipt,errors=['EXECUTION_DID_NOT_COMPLETE'],execution=done)
    validate_base(job['confirmed_base_reference'])
    if job['job_sha256']!=execution.digest({k:v for k,v in job.items() if k!='job_sha256'}):errors.append('JOB_SEAL_INVALID')
    for name,h in job['evaluation_source_hashes'].items():
        if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=h:errors.append('EVALUATION_SOURCE_CHANGED:'+name)
    part=read(d/'participant-plan.json');orgs=part['organization_ids']
    if {k:v for k,v in part.items() if k!='organization_ids'}!=job:errors.append('PARTICIPANT_JOB_CHANGED')
    journals=[read_journal(d/(r+'.jsonl')) for r in ('ingress','planner_1','planner_2','sender')]
    crash=execution.read_lines(d/'crash.jsonl');exit_receipt=read(d/'crash-exit.json')
    continuity=Continuity()
    for row in crash:continuity.feed(row)
    if continuity.error or not continuity.calibrations or not exit_receipt['backend_absent'] or exit_receipt['exit_code']==0:
        errors.append('CRASH_NOT_ACCOUNTED')
    # No fabricated footer: deliberately killed capture is preserved as partial.
    ClockMap(crash)
    all_journals=journals+[crash]
    ids={j[0]['os_pid'] for j in all_journals}
    if len(ids)!=5:errors.append('PARTICIPANT_IDENTITY_NOT_ISOLATED')
    old=read(d/'prelude-history.json');prep=read(d/'reclaim-base-preparation.json')
    plan=base_plan(job['confirmed_base_reference']['path'])
    expected=anchor_window(plan,timestamp(old['lease_expires_at']))
    anchor=read(d/'fixed-anchor.json');window=read(d/'observed-window.json')
    if prep['window']!=expected or anchor['target_db_ns']!=expected['start_db_ns'] or anchor['cadence_ns']!=plan['lead_to_natural_expiry_ns']:
        errors.append('S_NOT_L_MINUS_BASE_PERIOD')
    if timestamp(old['lease_expires_at'])-timestamp(old['claimed_at'])!=900*NS:errors.append('LEASE_CHANGED')
    if anchor['start_monotonic_ns']!=anchor['sample_monotonic_ns_bounds'][1]+anchor['target_db_ns']-anchor['sample_db_ns']:
        errors.append('CALENDAR_WAS_REANCHORED')
    slots=read(d/'schedule.json')
    if slots!=execution.schedule(job,anchor['start_monotonic_ns']):errors.append('BASE_CALENDAR_CHANGED')
    final=window['final_cut'];inbound=[m for m in final['messages'] if m['direction']=='in']
    offers=execution.read_lines(d/'offers.jsonl');ordinary=execution.read_lines(d/'schedule-offers.jsonl')
    if len(offers)!=len(ordinary)+1 or offers[0]['message_id']!=prep['message_id'] or any({k:o[k] for k in offers[0]}!=offers[i+1] for i,o in enumerate(ordinary)):
        errors.append('OFFER_LEDGER_NOT_RECONCILED')
    report=reconstruct(all_journals,offers,inbound,Interval(final['db_ns'],final['db_ns']),run_id=job['run_id'])
    effects,unknown=transactions(all_journals)
    claims=[(tx,r) for tx in effects for r in tx['rows'] if r['event']=='claim_bound']
    oldclaims=[(tx,r) for tx,r in claims if r['turn_work_id']==old['id']]
    if unknown or report['issues']:errors.extend(['UNRESOLVED_CAUSAL_EVIDENCE']+report['issues'])
    reclaimed=[(tx,r) for tx,r in oldclaims if r['attempts']>old['attempts'] and r['lease_fingerprint']!=old['lease_fingerprint']]
    if len(reclaimed)!=1:errors.append('ONE_NATURAL_RECLAIM_NOT_OBSERVED')
    overlap=verify_overlap(window,reclaimed[0][0]['commit'].json() if reclaimed else [None,None],ordinary,orgs,prep['message_id'])
    errors+=overlap['issues']
    if reclaimed:
        context=reclaimed[0][0]['context_rows']
        previous=next((r for r in context if r['event']=='existing_work' and r['turn_work_id']==old['id']),None)
        if not previous or previous['status']!='PROCESSING' or timestamp(previous['lease_expires_at'])!=expected['natural_expiry_db_ns']:
            errors.append('RECLAIM_CAUSE_NOT_ORIGINAL_NATURAL_EXPIRY')
    new=next(w for w in final['works'] if w['id']==old['id'])
    if not same_history(old,new):errors.append('RECOVERY_HISTORY_OR_BUDGET_CHANGED')
    if [m['id'] for m in inbound if m['turn_work_id']==old['id']]!=[prep['message_id']]:errors.append('RECOVERY_MEMBERSHIP_CHANGED')
    for w in final['works']:
        calls=[c for c in final['calls'] if c['turn_work_id']==w['id']]
        if w['llm_calls_admitted']!=len(calls) or w['llm_output_tokens_reserved']!=sum(c['reserved_output_tokens'] for c in calls):errors.append('BUDGET_LEDGER_MISMATCH')
    cohort=dict(report,episodes=[e for e in report['episodes'] if prep['message_id'] not in e['member_ids']])
    cohort['population']=dict(report['population'],accepted_durable_inputs=len(ordinary),represented_inputs=sum(len(e['member_ids']) for e in cohort['episodes']))
    cohort['organization_counts']={str(o):sum(e['organization_id']==o for e in cohort['episodes']) for o in orgs}
    wire=[r for role in ('planner_1','planner_2','sender') for r in execution.read_lines(d/(role+'-wire.jsonl'))]
    dispatch=[r for r in wire if r['event']=='dispatch']
    invariants=invariant_gate(cohort,all_journals,inbound,final['works'],dispatch,orgs)
    demand=demand_gate(job,cohort,ordinary,slots,orgs,(window['begin_cut']['db_ns'],window['end_cut']['db_ns']))
    services=verify_wire(part,wire,[e['turn_work_id'] for e in cohort['episodes'] if e['turn_work_id']])
    for gate in (invariants,demand):errors+=gate['missing']+gate['violations']
    errors+=services['issues']
    for e in cohort['episodes']:
        results=[r for r in wire if r['event']=='result' and r['boundary']=='llm' and r['turn_work_id']==e['turn_work_id']]
        if len(results)!=2 or {r['call_number'] for r in results}!={1,2} or any(r['elapsed_ns']<NS/2 or r['result']!='ACCEPTED' for r in results):errors.append('ORDINARY_FULL_SERVICE_MISSING')
        if e['disposition']!='OBSERVED_WITHIN_TARGET':errors.append('ORDINARY_WAIT_NOT_WITHIN_TARGET')
    populations={str(o):sorted({e['conversation_id'] for e in cohort['episodes'] if e['organization_id']==o}) for o in orgs}
    population_slots=execution.read_lines(d/'population-slots.jsonl')
    if any(len(v)!=3 for v in populations.values()) or [r['slot'] for r in population_slots]!=[i%3 for i in range(len(slots))]:errors.append('ORDINARY_POPULATION_ROTATION_CHANGED')
    if window['follow_end_ns']-window['follow_start_ns']<240*NS or final['db_ns']-window['end_cut']['db_ns']<240*NS:errors.append('FULL_240_SECOND_FOLLOWUP_MISSING')
    if any(w['status']!='COMPLETED' for w in final['works']) or any(not m['turn_work_id'] for m in inbound):errors.append('UNRESOLVED_DRAIN')
    outbound=[m for m in final['messages'] if m['direction']=='out']
    if any(not m['provider_accepted_at'] for m in outbound):errors.append('UNRESOLVED_OUTBOX')
    fences=[c for c in done['checks'] if c['name']=='stale_witness_has_no_effect']
    if len(fences)!=1 or not fences[0]['passed']:errors.append('STALE_FENCE_NOT_OBSERVED')
    if done['worker_exit_codes']!=[0,0,0] or not read(d/'participants-cleanup.json')['all_reaped']:errors.append('PARTICIPANT_CLEANUP_FAILED')
    clockmap=ClockMap(journals[0]);offsets=[0,120,240,360]
    intervals=[Interval(anchor['start_monotonic_ns']+i*NS+clockmap.offset.lo,anchor['start_monotonic_ns']+i*NS+clockmap.offset.hi) for i in offsets]
    queues=execution.queued_samples(cohort,offsets,intervals)
    windows=window_gate(job,cohort,queues,orgs)
    errors+=windows['missing']+windows['violations']
    receipt.update(status='NOT_ACCREDITED' if errors else 'PASS',errors=sorted(set(errors)),population=report['population'],
        episodes=len(report['episodes']),ordinary_episodes=len(cohort['episodes']),works=len(final['works']),claims=len(claims),commits=len(effects),
        ordinary_acceptances_by_org=dict(Counter(o['organization_id'] for o in ordinary)),conversations_by_org=populations,
        causal_reclaim=[dict(commit=tx['commit'].json(),event=r) for tx,r in reclaimed],overlap=overlap,
        demand=demand,invariants=invariants,provider=services,queue_samples=queues,window_gate=windows,
        followup_monotonic_seconds=(window['follow_end_ns']-window['follow_start_ns'])/NS,
        prelude_partial_journal=dict(expected=True,os_pid=exit_receipt['os_pid'],calibrations=continuity.calibrations),
        observed_anchor=anchor,physical_evidence=[p.name for p in d.iterdir() if p.suffix in ('.json','.jsonl')])
    write_json(d/'reconstructed-cohort-v2.json',report)
    return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();d=Path(a.output)
    try:r=verify(read(a.job),d)
    except Exception as exc:r=dict(status='NOT_ACCREDITED',errors=['VERIFICATION_INCOMPLETE'],error_type=type(exc).__name__,error=str(exc))
    write_json(d/'authorized-verification-v2.json',r)
    print(json.dumps(r),flush=True)

if __name__=='__main__':main()
