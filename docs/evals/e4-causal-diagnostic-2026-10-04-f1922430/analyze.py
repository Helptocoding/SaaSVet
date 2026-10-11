"""Offline per-attempt decomposition. No acceptance gates or code mutations."""
import argparse
import bisect
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import infra

OUT=infra.OUT
sys.path.insert(0,str(infra.ROOT/'backend'))
from apps.agent.claim_diagnostic_report import read_journal,reconstruct

def load(name): return json.loads((OUT/name).read_text(encoding='utf-8'))
def timestamp(value): return datetime.fromisoformat(value).timestamp()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def ms(ns): return ns/1e6

def build():
    paths=[OUT/(role+'.jsonl') for role in ('ingress','planner-1','planner-2','sender')]
    journals=[read_journal(p) for p in paths]
    integrity=[dict(path=p.name,sha256=sha(p),events=len(rows),queries=rows[-1]['query_count'],
        failed_writes=rows[-1]['failed_writes'],closed=not rows[-1]['open_transaction'],
        session_id=rows[0]['session_id'],run_id=rows[0]['run_id']) for p,rows in zip(paths,journals)]
    for path in paths:
        text=path.read_text(encoding='utf-8')
        for forbidden in ('"sql":','"params":','"body":','"prompt":','SELECT ',
                          'INSERT INTO','Mi perro','Qué servicios','5512345678'):
            assert forbidden not in text
    assert len({r['run_id'] for r in integrity})==1
    assert load('load.exit.json')['exit_code']==0
    assert all(row['exit_code']==0 and row['reader_stopped'] for row in load('process-exits.json'))
    observer=load('waits.summary.json'); assert observer['complete'] and observer['partial_journal_lines']==0
    assert observer['run_id']==integrity[0]['run_id']
    before,after=load('protected-sources-before.json'),load('protected-sources-after.json')
    assert before==after and before['head']==infra.HEAD and not before['drift']
    cleanup=load('cleanup.json'); assert cleanup['status']=='CLEANED'
    assert load('functional.exit.json')['exit_code']==0
    functional=load('functional-results.results.json')
    assert all(functional[k]==0 for k in ('failures','errors','skips','xfail')) and functional['tests']==6
    comparisons={}
    for name in ('concurrency','lock-wait','blocked-llm','rollback'):
        record=load('functional-artifacts/'+name+'-equivalence.json')
        assert record['on_off_equal'] and record['on']==record['off']; comparisons[name]='EQUIVALENT'
    report=reconstruct(journals)
    local={rows[0]['session_id']:rows for rows in journals}
    queries=[]
    for rows in journals:
        starts={r['query_id']:r for r in rows if r['event']=='sql_start'}
        for row in rows:
            if row['event']=='sql_end':
                start=starts[row['query_id']]
                queries.append(dict(row,operation=start['operation'],tables=start['tables'],
                    for_update=start['for_update'],no_key_update=start['no_key_update'],skip_locked=start['skip_locked']))
    query_map={(q['session_id'],q['query_id']):q for q in queries}
    grouped=defaultdict(list)
    for q in queries: grouped[(q['session_id'],q['connection_id'],q['backend_pid'])].append(q)
    index={}
    for key,rows in grouped.items():
        rows.sort(key=lambda q:q['execute_start_ns'])
        index[key]=(rows,[q['execute_start_ns'] for q in rows],[q['execute_end_ns'] for q in rows])
    wait_stats=defaultdict(lambda:dict(samples=0,lock_samples=0,blocking_pids=set(),wait_events=defaultdict(int)))
    wait_counts=defaultdict(int); total_samples=0
    with (OUT/'waits.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            sample=json.loads(line); total_samples+=1
            assert sample['run_id']==report['run_id']
            key=(sample['session_id'],sample['connection_id'],sample['backend_pid'])
            rows,starts,ends=index.get(key,([],[],[]))
            candidates=rows[bisect.bisect_left(ends,sample['sample_start_ns']):
                bisect.bisect_right(starts,sample['sample_end_ns'])]
            wait_counts['matched' if len(candidates)==1 else 'ambiguous' if candidates else 'unassigned']+=1
            if len(candidates)!=1: continue
            query=candidates[0]; stats=wait_stats[(query['session_id'],query['query_id'])]
            stats['samples']+=1
            stats['wait_events'][(sample['wait_event_type'] or 'NONE')+':'+(sample['wait_event'] or 'NONE')]+=1
            if sample['wait_event_type']=='Lock':
                stats['lock_samples']+=1; stats['blocking_pids'].update(sample['blocking_pids'])
    assert total_samples==observer['samples']
    for key,stats in wait_stats.items():
        stats['blocking_pids']=sorted(stats['blocking_pids']); stats['wait_events']=dict(stats['wait_events'])
        stats['exact_lock_wait_ms']=None
        stats['lock_wait_ms_bounds']=[0,ms(query_map[key]['duration_ns'])] if stats['lock_samples'] else None
    state=load('durable-state.json'); messages={m['id']:m for m in state['messages']}
    works={w['id']:w for w in state['works']}
    for m in state['messages']:
        if m['turn_work_id'] is not None:
            w=works[m['turn_work_id']]
            assert m['organization_id']==w['organization_id'] and m['conversation_id']==w['conversation_id']
    assert all(w['llm_calls_admitted']<=30 and w['llm_output_tokens_reserved']<=18000 for w in state['works'])
    for claim in report['claims']:
        rows=local[claim['session_id']]; attempt=[r for r in rows if r.get('attempt_id')==claim['attempt_id']]
        kind=claim['claim_start']['event'].removesuffix('_start')
        end=next(r for r in attempt if r['event']==kind+'_end')
        result=next(r for r in attempt if r['event']=='claim_result' and r['boundary']==kind)
        commit=claim['commit']
        commit_start=next((r for r in rows if r['event']=='commit_start' and
            r['transaction_id']==claim['transaction_id']),None)
        claim['claim_end']=end; claim['claim_result']=result; claim['commit_start']=commit_start
        claim['claim_duration_ms']=ms(end['monotonic_ns']-claim['claim_start']['monotonic_ns'])
        claim['commit_duration_ms']=ms(commit['duration_ns']) if commit else None
        claim['claim_result_to_commit_ack_ms_signed']=ms(commit['execute_end_ns']-result['monotonic_ns']) if commit else None
        claim['result_commit_order']='COMMIT_BEFORE_RESULT' if commit and commit['execute_end_ns']<result['monotonic_ns'] else 'RESULT_BEFORE_COMMIT' if commit else 'NOT_OBSERVED'
        for field in ('selection_sql','claim_sql'):
            values=[query_map[(q['session_id'],q['query_id'])] for q in claim[field]]
            claim[field]=values
            claim[field+'_gaps_ms']=[ms(b['execute_start_ns']-a['execute_end_ns']) for a,b in zip(values,values[1:])]
        claim['selection_query_count']=len(claim['selection_sql'])
        claim['selection_sql_ms']=sum(ms(q['duration_ns']) for q in claim['selection_sql'])
        claim['claim_sql_ms']=sum(ms(q['duration_ns']) for q in claim['claim_sql'])
        claim['selection_duration_ms']=ms(claim['selection_duration_ns']) if claim['selection_duration_ns'] is not None else None
        claim['selection_end_to_claim_start_ms']=ms(claim['selection_end_to_claim_start_ns']) if claim['selection_end_to_claim_start_ns'] is not None else None
        for q in claim['selection_sql']+claim['claim_sql']:
            q['wait_observations']=wait_stats.get((q['session_id'],q['query_id']),dict(samples=0,lock_samples=0,exact_lock_wait_ms=None))
        clock=claim['clock_calibration']
        def db_bounds(point):
            if clock is None or point is None: return None
            db=timestamp(clock['db_timestamp'])
            return [db+(point-clock['end_ns'])/1e9,db+(point-clock['start_ns'])/1e9]
        claim['claimed_at_to_commit_ack_ms_bounds']=[(x-timestamp(claim['claim_bound']['claimed_at']))*1000
            for x in db_bounds(commit['execute_end_ns'])] if commit and clock else None
        for metric,member in zip(claim['message_timelines'],claim['membership']):
            eligible=timestamp(metric['effective_inbound_eligible_at'])
            metric['organization_id']=claim['organization_id']; metric['conversation_id']=claim['conversation_id']
            metric['safety']=messages[metric['message_id']]['semantic_type']=='safety_signal'
            metric['over_10_seconds']=metric['persisted_to_claimed_at_seconds']>10
            metric['eligible_to_claimed_at_ms']=(timestamp(claim['claim_bound']['claimed_at'])-eligible)*1000
            metric['persisted_to_commit_ack_ms_bounds']=[(x-timestamp(member['created_at']))*1000
                for x in db_bounds(commit['execute_end_ns'])] if commit and clock else None
            # Occupancy of the admitting worker before its SELECT, bounded by
            # the same existing DB-clock bracket. Never infer global availability.
            occupancy=[]
            if clock and claim['selection_start']:
                eligible_ns=[clock['start_ns']+(eligible-timestamp(clock['db_timestamp']))*1e9,
                    clock['end_ns']+(eligible-timestamp(clock['db_timestamp']))*1e9]
                cutoff=claim['selection_start']['monotonic_ns']
                spans={}
                polls=[]
                for event in rows:
                    if event['event']=='turn_start': spans[event['span_id']]=event
                    elif event['event']=='turn_end' and event['span_id'] in spans:
                        begin=spans[event['span_id']]
                        bounds=[max(0,min(event['monotonic_ns'],cutoff)-max(begin['monotonic_ns'],limit))/1e6
                            for limit in reversed(eligible_ns)]
                        if bounds[1]>0: occupancy.append(dict(kind='processing_previous_turn',
                            turn_work_id=begin['turn_work_id'],duration_ms_bounds=bounds))
                    if event['event'] in ('poll_start','poll_end'): polls.append(event)
                previous=None
                for event in polls:
                    if event['event']=='poll_end': previous=event
                    elif previous is not None:
                        bounds=[max(0,min(event['monotonic_ns'],cutoff)-max(previous['monotonic_ns'],limit))/1e6
                            for limit in reversed(eligible_ns)]
                        if bounds[1]>0: occupancy.append(dict(kind='between_polls_including_configured_1s_pause',duration_ms_bounds=bounds))
                        previous=None
            metric['admitting_worker_preselection_occupancy']=occupancy
    missed_attempts=[]
    for session,rows in local.items():
        starts={r['attempt_id']:r for r in rows if r['event']=='claim_start'}
        bound_ids={r['attempt_id'] for r in rows if r['event']=='claim_bound'}
        for attempt_id,start in starts.items():
            if attempt_id in bound_ids: continue
            events=[r for r in rows if r.get('attempt_id')==attempt_id]
            end=next(r for r in events if r['event']=='claim_end')
            result=next((r for r in events if r['event']=='claim_result' and r['boundary']=='claim'),None)
            sql_queries=[query_map[(session,r['query_id'])] for r in events if r['event']=='sql_end']
            missed_attempts.append(dict(attempt_id=attempt_id,session_id=session,worker=start['worker'],
                conversation_id=start['conversation_id'],outcome=result['result'] if result else 'error',
                duration_ms=ms(end['monotonic_ns']-start['monotonic_ns']),query_count=len(sql_queries),
                sql_timings=sql_queries,clock=next((r for r in events if r['event']=='db_clock'),None),
                membership='NOT_BOUND',persisted_to_claimed_at='NOT_APPLICABLE'))
    summaries=[]
    for c in report['claims']:
        for metric in c['message_timelines']:
            summaries.append(dict(attempt_id=c['attempt_id'],worker=c['worker'],turn_work_id=c['turn_work_id'],
                attempts=c['attempts'],status=c['status'],message_id=metric['message_id'],organization_id=c['organization_id'],
                safety=metric['safety'],persisted_to_claimed_at_s=metric['persisted_to_claimed_at_seconds'],
                persisted_to_eligible_s=metric['persisted_to_eligible_seconds'],
                eligible_to_poll_s_bounds=metric['eligible_to_poll_seconds_bounds'],
                eligible_to_selection_s_bounds=metric['eligible_to_selection_seconds_bounds'],
                selection_ms=c['selection_duration_ms'],selector_query_count=c['selection_query_count'],
                selector_sql_ms=c['selection_sql_ms'],selection_end_to_claim_start_ms=c['selection_end_to_claim_start_ms'],
                claim_ms=c['claim_duration_ms'],claim_sql_ms=c['claim_sql_ms'],commit_ms=c['commit_duration_ms'],
                claim_result_to_commit_ack_ms_signed=c['claim_result_to_commit_ack_ms_signed'],
                claimed_at_to_commit_ack_ms_bounds=c['claimed_at_to_commit_ack_ms_bounds'],
                observable_lock_samples=sum(q['wait_observations']['lock_samples'] for q in c['claim_sql']+c['selection_sql']),
                over_10_seconds=metric['over_10_seconds']))
    phase_summary={}
    for field in ('persisted_to_claimed_at_s','persisted_to_eligible_s','selection_ms','selector_sql_ms',
                  'claim_ms','claim_sql_ms','commit_ms','selection_end_to_claim_start_ms'):
        values=[s[field] for s in summaries if s[field] is not None]
        phase_summary[field]=dict(n=len(values),min=min(values),median=statistics.median(values),max=max(values)) if values else dict(n=0)
    report.update(head=infra.HEAD,journal_integrity=integrity,observer_integrity=observer,
        functional_comparison=dict(result='EQUIVALENT',controlled_scenarios=6,receipts=comparisons,
            limitation='Controlled identical-state OFF/ON proof; no claim of identical scheduling in separate timed loads.'),
        source_protection=dict(before='protected-sources-before.json',after='protected-sources-after.json',
            protected_files=before['protected_files'],changed=0),infrastructure_cleanup=cleanup,
        privacy=dict(raw_sql_or_parameters=False,conversational_content=False,forbidden_patterns_found=0),
        attempt_summaries=summaries,missed_attempts=missed_attempts,phase_summary=phase_summary,
        over_10_seconds=[s for s in summaries if s['over_10_seconds']],
        unclaimed_inbounds=[m for m in state['messages'] if m['turn_work_id'] is None],
        waits_summary=dict(sample_count=total_samples,**wait_counts,
            observable_lock_queries=[dict(session_id=k[0],query_id=k[1],**v) for k,v in wait_stats.items() if v['lock_samples']],
            exact_lock_wait_ms=None,raw_samples='waits.jsonl'),
        all_sql_query_count=len(queries),all_sql_query_timings=queries,
        limits=['Same-host DB/monotonic calibration assumes no clock step.',
                'Instrumented elapsed times include observation overhead.',
                'Selection queries are shared across candidates; never charged exclusively to each inbound.',
                'Sampling cannot establish exact lock duration or absence of waits.',
                'Unclaimed backlog has no claimed_at; no synthetic end timestamp.',
                'claim_result may occur after commit for ordinary claims and before commit for safety.'])
    infra.write('attempt-summary.json',summaries)
    with (OUT/'attempt-summary.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summaries[0]) if summaries else ['attempt_id'])
        writer.writeheader()
        for row in summaries:
            writer.writerow({key:json.dumps(value) if isinstance(value,list) else value for key,value in row.items()})
    infra.write('phase-summary.json',phase_summary)
    infra.write('integrity.json',dict(journals=integrity,observer=observer,source_files_unchanged=before['protected_files']))
    return report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--result',choices=('CAUSE_CONFIRMED','CAUSE_NOT_CONFIRMED','INCOMPLETE'))
    parser.add_argument('--reason'); args=parser.parse_args()
    try: report=load('causal-analysis.json') if args.result else build()
    except Exception as exc:
        infra.write('causal-report.json',dict(classification='DIAGNOSTIC_ONLY',result_classification='INCOMPLETE',
            head=infra.HEAD,reason_type=type(exc).__name__,reason=str(exc),acceptance_run=False,
            historical_turnwork_86_causality='NOT_INFERRED'))
        raise
    if args.result:
        report['result_classification']=args.result;report['causal_conclusion']=args.reason
        infra.write('causal-report.json',report)
    else: infra.write('causal-analysis.json',report)
    print(json.dumps(dict(claims=len(report['claims']),attempt_message_rows=len(report['attempt_summaries']),
        over_10_seconds=len(report['over_10_seconds']),unclaimed=len(report['unclaimed_inbounds']),
        observable_lock_queries=len(report['waits_summary']['observable_lock_queries']),
        phase_summary=report['phase_summary'])))

if __name__=='__main__': main()
