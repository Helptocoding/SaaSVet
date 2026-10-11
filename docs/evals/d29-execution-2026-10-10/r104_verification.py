"""Admit only a complete observed sequence on the unchanged base calendar."""
import json
import sys
from pathlib import Path
from apps.agent.tests.scheduling_characterization.execution import read_lines,schedule
from apps.agent.tests.scheduling_characterization.evidence import ClockMap,Interval,reconstruct,timestamp,NS,transactions
from apps.agent.tests.scheduling_characterization.recipes import verify_recipe
from evaluation_provider import verify_wire


def verify(folder):
    d=folder/'capture'
    read=lambda p:json.loads(p.read_text())
    job=read(folder/'job.json');participant=read(d/'participant-plan.json')
    done=read(d/'finite-investigation.json');clock=read(folder/'capture-clock/clock-receipt.json')
    final=read(d/'full-durable-final.json');offers=read_lines(d/'schedule-offers.jsonl')
    journals=[read_lines(d/(r+'.jsonl')) for r in ('ingress','planner_1','planner_2','sender')]
    report=reconstruct(journals,offers,final['messages'],Interval(final['db_ns'],final['db_ns']),run_id=job['run_id'])
    effects,unresolved=transactions(journals)
    errors=list(report['issues'])
    if unresolved:errors.append('UNRESOLVED_TRANSACTION_EVIDENCE')
    if not clock['gate_passed']:errors.append('CLOCK_OR_CAPTURE_INVALID')
    if done['error']:errors.append('INVESTIGATION_INCOMPLETE')
    if done.get('worker_exit_codes')!=[0,0,0]:errors.append('PARTICIPANT_EXIT_NOT_CLEAN')
    if not done.get('full_base_window_executed'):errors.append('FULL_BASE_WINDOW_NOT_COMPLETED')
    if not read(d/'participants-cleanup.json')['all_reaped']:errors.append('PARTICIPANT_CLEANUP_FAILED')
    if read(d/'sealed-job.json')!=job or {k:v for k,v in participant.items() if k!='organization_ids'}!=job:
        errors.append('SEALED_EXECUTOR_JOB_CHANGED')
    slots=read(d/'schedule.json');start=min(s['due_monotonic_ns'] for s in slots)
    if schedule(participant,start)!=slots:errors.append('BASE_CALENDAR_CHANGED')
    rotation=read_lines(d/'population-slots.jsonl')
    if [r['slot'] for r in rotation]!=[i%3 for i in range(len(slots))] or len(offers)!=len(slots):
        errors.append('ORDINARY_POPULATION_OR_PACING_CHANGED')
    if final['db_ns']<start+600*NS+ClockMap(journals[0]).offset.hi:
        errors.append('FULL_FOLLOWUP_NOT_OBSERVED')
    original=read(d/'job-result.json')
    for name,gate in original['gates'].items():
        if name!='scenario':errors += [name+':'+e for e in gate['missing']+gate['violations']]
    wire=[r for role in ('planner_1','planner_2','sender') for r in read_lines(d/(role+'-wire.jsonl'))]
    sys.path.append(str(Path(__file__).parent.parent/'d29-offline-preparation-2026-10-09'))
    import r106_verifier
    from native_verifier_bridge import installed
    with installed():
        causal=r106_verifier.causal_events(journals,effects)
        obligations=r106_verifier.reconcile(report,final['messages'],final['works'],wire,final['calls'],causal)
    errors+=obligations['errors']
    provider=verify_wire(participant,wire,[e['turn_work_id'] for e in report['episodes']])
    errors+=provider['issues']
    observations=[];prequeries=[]
    for journal in journals[1:3]:
        mapping=ClockMap(journal)
        for row in journal:
            if row['event']=='forecast_prequery':prequeries.append(row)
            if row['event']!='forecast_empty_poll_returned':continue
            poll=row['native_poll_id'];native=[e for e in journal if e.get('poll_id')==poll]
            empty=[e for e in native if e['event']=='selection_result' and e['conversation_ids']==[]]
            selected=[e for e in native if e['event']=='selection_start']
            ended=[e for e in native if e['event']=='poll_end' and e.get('outcome')=='returned']
            if len(empty)!=1 or len(selected)!=1 or len(ended)!=1 or any(e['event']=='claim_result' for e in native):
                errors.append('EMPTY_POLL_NOT_NATIVE_OR_CONTAINS_CLAIM');continue
            msgs={m['id']:m for m in row['prequery']['messages']}
            f,w=msgs[row['arm']['future']],msgs[row['arm']['waiter']]
            bounds=mapping.execution(dict(execute_start_ns=selected[0]['monotonic_ns'],execute_end_ns=row['monotonic_ns'])).json()
            old=timestamp(f['available_at']);ready=timestamp(w['available_at'])
            valid=(row['prequery_monotonic_bounds'][1]<=selected[0]['monotonic_ns'] and ready<=bounds[0]<=bounds[1]<old<=bounds[0]+NS)
            # A competing committed write during the witnessed query makes its
            # forecast cause ambiguous; no later census can repair that race.
            relevant={w['organization_id'],f['organization_id']}
            for tx in effects:
                if tx['commit'].lo<=bounds[1] and tx['commit'].hi>=row['prequery']['db_ns']:
                    if any(e['event'] in ('claim_bound','message_persisted','work_terminal') and e.get('organization_id') in relevant for e in tx['rows']):
                        valid=False
            observations.append(dict(role=row['worker'],poll_id=poll,prequery_db_ns=row['prequery']['db_ns'],
                forecast_deadline_ns=old,waiter_ready_ns=ready,yield_db_ns_bounds=bounds,
                future_id=f['id'],waiter_id=w['id'],future_conversation_id=f['conversation_id'],
                waiter_organization_id=w['organization_id'],raw_event_seq=row['seq'],cause_unambiguous=valid))
    first=None;second=None;correction=None
    by_id={m['id']:m for m in final['messages']}
    for candidate in observations:
        if not candidate['cause_unambiguous']:continue
        matching=[o for o in offers if o.get('message_id')!=candidate['future_id'] and o.get('message_id') in by_id
            and by_id[o['message_id']]['conversation_id']==candidate['future_conversation_id']
            and candidate['yield_db_ns_bounds'][1]<o['offered_db_ns_bounds'][0]<=o['offered_db_ns_bounds'][1]<candidate['forecast_deadline_ns']]
        if matching:
            first=candidate;correction=matching[0]
            second=next((o for o in observations if o['cause_unambiguous'] and o['future_id']==first['future_id']
                and o['waiter_id']==first['waiter_id'] and first['forecast_deadline_ns']<=o['prequery_db_ns']<o['forecast_deadline_ns']
                and o['forecast_deadline_ns']>first['forecast_deadline_ns'] and o['waiter_ready_ns']==first['waiter_ready_ns']),None)
            break
    if first is None:errors.append('NATIVE_FORECAST_YIELD_THEN_ORDINARY_CORRECTION_NOT_OBSERVED')
    if second is None:errors.append('OLD_FORECAST_MISS_AND_SECOND_NATIVE_YIELD_NOT_OBSERVED')
    events=[]
    if first and second:
        future=by_id[first['future_id']];cap=timestamp(future['created_at'])+25*NS
        w=next((e for e in report['episodes'] if first['waiter_id'] in e['member_ids']),None)
        f=next((e for e in report['episodes'] if first['future_id'] in e['member_ids']),None)
        if not (second['forecast_deadline_ns']==cap and first['waiter_ready_ns']>=cap-NS
                and correction['offered_db_ns_bounds'][0]+8*NS>=cap):
            errors.append('NATIVE_SUPERSESSION_CAP_AND_HORIZON_NOT_PROVEN')
        if not(w and f and f.get('claim_commit_ns_bounds') and w.get('claim_commit_ns_bounds')
               and cap<=f['claim_commit_ns_bounds'][0]<=f['claim_commit_ns_bounds'][1]<=w['claim_commit_ns_bounds'][0]
               and w['claim_commit_ns_bounds'][1]-first['waiter_ready_ns']<=120*NS):
            errors.append('NEW_ELIGIBILITY_THEN_PEER_THEN_WAITER_CLAIMS_NOT_DEFINITE')
        org_index=participant['organization_ids'].index(first['waiter_organization_id'])
        for name,at in [('ready_waiter',first['waiter_ready_ns']),('future_eligibility',first['prequery_db_ns']),
                        ('forecast_miss',second['prequery_db_ns']),('future_eligibility_again',second['prequery_db_ns'])]:
            events.append(dict(event=name,run_id=job['run_id'],organization_index=org_index,db_ns=at,
                source='INDEPENDENT_DB_WITNESS',observed=True,evidence=['planner_1.jsonl','planner_2.jsonl','schedule-offers.jsonl']))
    recipe=verify_recipe(participant,events)
    errors+=recipe['missing']+recipe['violations']
    return dict(status='PENDING' if errors else 'ACCREDITED',errors=sorted(set(errors)),physical_execution=True,
        source_kind='NATIVE_FREE_PLANNER_INVESTIGATION',clock_gate=clock,prequeries=len(prequeries),
        native_forecast_yields=observations,ordinary_correction=correction,first_forecast=first,second_forecast=second,
        population=report['population'],counts=obligations['counts'],original_base_gates=original['gates'],
        native_scenario_gate=recipe,provider=provider,planner_holds=False,extra_fixture_inputs=0,
        nominal_offsets_used_as_evidence=False,synthetic_evidence=[],
        next_step='REVIEW_SINGLE_ATTEMPT_PHYSICAL_WINDOW_AND_DECIDE_MINIMUM_FOLLOWUP' if errors else 'NEXT_SPECIAL_SCENARIO')
