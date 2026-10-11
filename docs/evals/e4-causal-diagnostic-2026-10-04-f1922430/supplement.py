"""Complete explicit phase boundaries and scope conclusions to the new runtime."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
import infra
from finalize import csv_write, read_journal, stats


def load(name):
    return json.loads((infra.OUT/name).read_text(encoding='utf-8'))


def ns(value):
    delta = datetime.fromisoformat(value)-datetime(1970,1,1,tzinfo=timezone.utc)
    return ((delta.days*86400+delta.seconds)*1000000+delta.microseconds)*1000


def write_final(name, value):
    with (infra.OUT/name).open('w',encoding='utf-8') as target:
        json.dump(value,target,indent=2); target.write('\n')


def main():
    report = load('causal-report.json')
    assert report['run_id']=='causal-'+infra.KEY
    assert report['classification']=='DIAGNOSTIC_ONLY'
    event_indexes = {}
    for item in report['journal_integrity']:
        rows = read_journal(infra.OUT/item['path'])
        transactions = {r['transaction_id']:r for r in rows if r['event']=='transaction_begin'}
        turns = defaultdict(list)
        starts = {}
        for event in rows:
            if event['event']=='turn_start':
                starts[event['span_id']]=event
            elif event['event']=='turn_end':
                begin=starts[event['span_id']]
                turns[begin['turn_work_id']].append(dict(start=begin,end=event,
                    duration_ms=(event['monotonic_ns']-begin['monotonic_ns'])/1e6))
        event_indexes[rows[0]['session_id']]=(transactions,turns)
    claims = {c['attempt_id']:c for c in report['claims']}
    for row in report['attempt_summaries']:
        c=claims[row['attempt_id']]
        transactions,turns=event_indexes[c['session_id']]
        row.update(epoch=c['epoch'],lease_fingerprint=c['lease_fingerprint'],
            lease_expires_at=c['claim_bound']['lease_expires_at'],member_ids=c['claim_bound']['member_ids'],
            db_clock=c['clock_calibration'],transaction_begin=transactions[c['transaction_id']],
            poll_start_monotonic_ns=c['poll_start']['monotonic_ns'] if c['poll_start'] else None,
            selection_start_monotonic_ns=c['selection_start']['monotonic_ns'] if c['selection_start'] else None,
            selection_end_monotonic_ns=c['selection_end']['monotonic_ns'] if c['selection_end'] else None,
            claim_start_monotonic_ns=c['claim_start']['monotonic_ns'],
            claim_end_monotonic_ns=c['claim_end']['monotonic_ns'],
            poll_to_selection_ms=(c['selection_start']['monotonic_ns']-c['poll_start']['monotonic_ns'])/1e6
                if c['poll_start'] and c['selection_start'] else None,
            selection_start_to_claim_start_ms=(c['claim_start']['monotonic_ns']-c['selection_start']['monotonic_ns'])/1e6
                if c['selection_start'] else None,
            claim_start_to_commit_ack_ms=(c['commit']['execute_end_ns']-c['claim_start']['monotonic_ns'])/1e6,
            admitting_worker_turn_spans=turns.get(c['turn_work_id'],[]))
        c['poll_to_selection_ms']=row['poll_to_selection_ms']
        c['claim_start_to_commit_ack_ms']=row['claim_start_to_commit_ack_ms']
        c['transaction_begin']=row['transaction_begin']

    state=load('durable-state.json')
    org_by_conversation={m['conversation_id']:m['organization_id'] for m in state['messages']}
    for miss in report['missed_attempts']:
        miss['organization_id']=org_by_conversation.get(miss['conversation_id'])
    # Count only evidence-backed eligibility. Completed memberships use their
    # actual read; pending messages use the final durable deadline, explicitly labelled.
    eligibility={r['message_id']:ns(r['eligible_at']) for r in report['attempt_summaries']}
    claimed={r['message_id']:ns(r['claimed_at']) for r in report['attempt_summaries']}
    for m in state['messages']:
        if m['id'] not in eligibility:
            eligibility[m['id']]=max(ns(m['created_at']),ns(m['available_at']) if m['available_at'] else ns(m['created_at']))
    backlog=[]
    for row in report['attempt_summaries']:
        c=claims[row['attempt_id']]
        if not c['selection_start']:
            continue
        clock=c['clock_calibration']; point=c['selection_start']['monotonic_ns']
        limits=[ns(clock['db_timestamp'])+point-clock['end_ns'],ns(clock['db_timestamp'])+point-clock['start_ns']]
        counts={}
        for org in report['load_definition']['organization_ids']:
            members=[m for m in state['messages'] if m['organization_id']==org]
            definite=sum(eligibility[m['id']]<=limits[0] and claimed.get(m['id'],float('inf'))>limits[1] for m in members)
            possible=sum(eligibility[m['id']]<=limits[1] and claimed.get(m['id'],float('inf'))>limits[0] for m in members)
            counts[str(org)]=[definite,possible]
        row['eligible_unclaimed_backlog_at_selection_bounds']=counts
        backlog.append(dict(attempt_id=row['attempt_id'],organization_id=row['organization_id'],
            persisted_to_claimed_at_s=row['persisted_to_claimed_at_s'],
            eligible_to_selection_s_bounds=row['eligible_to_selection_s_bounds'],backlog_bounds=counts))
    infra.write('backlog-observations.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],
        counts='Eligible, not-yet-claimed inbounds at selection; not a count of simultaneously runnable conversations.',
        eligibility_sources='Actual membership read for claimed messages; final durable deadline for pending messages.',
        causal_limitation='Observational association only; no counterfactual isolation of noisy backlog or global worker availability.',
        attempts=backlog))
    health=[]
    for row in report['attempt_summaries']:
        if row['organization_id'] not in (1,2) or not row['over_10_seconds']:
            continue
        before=row['persisted_to_selection_start_ms_bounds']
        health.append(dict(attempt_id=row['attempt_id'],message_id=row['message_id'],organization_id=row['organization_id'],
            persisted_to_claimed_at_s=row['persisted_to_claimed_at_s'],excess_over_10_ms=row['excess_over_10_s']*1000,
            persisted_to_selection_ms_bounds=before,
            before_selection_excess_ms_bounds=[max(0,x-10000) for x in before] if before else None,
            selection_start_to_claimed_at_ms_bounds=row['selection_start_to_claimed_at_ms_bounds'],
            selector_sql_ms=row['selector_sql_ms'],commit_ms=row['commit_ms'],
            qualification='Threshold crossing and incremental post-selection cost are separate. Not every millisecond beyond 10 s is attributed to the queue.'))
    infra.write('healthy-excess-assessment.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],attempts=health))
    for name,group in (('all_bound',report['attempt_summaries']),
                       ('ordinary',[r for r in report['attempt_summaries'] if not r['safety']]),
                       ('safety',[r for r in report['attempt_summaries'] if r['safety']]),
                       ('over_10_seconds',[r for r in report['attempt_summaries'] if r['over_10_seconds']])):
        report['phase_summary'][name]['exact'].update({field:stats(r[field] for r in group) for field in
            ('poll_to_selection_ms','selection_start_to_claim_start_ms','claim_start_to_commit_ack_ms')})
    report['over_10_seconds']=[r for r in report['attempt_summaries'] if r['over_10_seconds']]
    report['historical_root_cause']='ROOT_CAUSE_NOT_CONFIRMED'
    report['historical_stop_reason']='The current HEAD includes another selector. New clocks and traces cannot reconstruct absent fine-grained historical phase boundaries or establish causal equivalence to TurnWork 86.'
    report['current_runtime_phase_conclusion']='PRECLAIM_WAIT' if report['result_classification']=='CAUSE_CONFIRMED' else 'ROOT_CAUSE_NOT_CONFIRMED'
    if report['result_classification']=='CAUSE_CONFIRMED':
        report['causal_conclusion']=('All '+str(len(report['over_10_seconds']))+' bound messages above 10 s had already crossed 10 s before selection_start. '
            'This confirms preselection threshold crossing on this new runtime. Selector/claim SQL and commit add the individually recorded costs; '
            'not every millisecond of excess is attributed to the queue. Worker occupancy and noisy backlog observations do not isolate a unique mechanism. '
            'Historical ROOT_CAUSE_NOT_CONFIRMED; no runtime correction is proposed.')
    report['healthy_excess_assessment']=health
    report['candidate_vs_miss']=dict(bound_by_organization=dict(Counter(r['organization_id'] for r in report['attempt_summaries'])),
        misses_by_organization=dict(Counter(r['organization_id'] for r in report['missed_attempts'])),
        miss_claim_ms=stats(r['duration_ms'] for r in report['missed_attempts']),
        miss_selector_ms=stats(r['selection_ms'] for r in report['missed_attempts']),
        limitation='Misses have no committed membership or claimed_at; no persisted-to-claim duration is invented.')
    report['preserved_status']=dict(B9E_historical='FAIL',PROFILE_BETA_1_historical='FAIL',B9='IN_PROGRESS',
        later_02_10_evaluation='UNMODIFIED',deployed=False,activated=False,runtime_modified=False,threshold_seconds=10)
    report['missing_historical_evidence']=['All historical selector SQL linked uniquely to TurnWork 86 and its attempt/membership.',
        'High-resolution historical poll, selector evaluation, claim, clock, transaction and commit ACK boundaries.',
        'Historical simultaneous worker occupancy and waits linked by backend/query interval.',
        'Evidence that a mechanism observed on the current selector also applied to the historical runtime.']
    report['artifact_index'].update(backlog='backlog-observations.json',healthy_excess='healthy-excess-assessment.json',
                                   complete_attempt_csv='per-attempt-complete.csv')
    write_final('causal-report.json',report)
    write_final('per-attempt.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],
        bound_attempts=report['attempt_summaries'],attempts_without_binding=report['missed_attempts']))
    csv_write('per-attempt-complete.csv',report['attempt_summaries'])
    write_final('over-10-attempts.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],attempts=report['over_10_seconds']))
    write_final('per-phase.json',dict(classification='DIAGNOSTIC_ONLY',run_id=report['run_id'],phases=report['phase_summary']))
    print(json.dumps(dict(current=report['current_runtime_phase_conclusion'],historical=report['historical_root_cause'],
                          healthy_over_10=len(health),misses=report['candidate_vs_miss'])))


if __name__=='__main__':
    main()
