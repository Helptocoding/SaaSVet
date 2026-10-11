"""Offline reconciliation of real captures; never generate events or replay."""
import json
import runpy
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
read,sha,write=lab['read'],lab['sha'],lab['write']


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def main():
    values=[]
    for executor_path in sorted(HERE.glob('*/*/dependent-executor-receipt.json')):
        directory=executor_path.parent
        executor=read(executor_path)
        vpath=directory/'independent-verification.json'
        verification=read(vpath) if vpath.exists() else None
        value=dict(run_id=executor['run_id'],case_id=executor['case_id'],variant=executor['variant'],
            directory=directory.relative_to(HERE).as_posix(),executor_sha256=sha(executor_path),
            verifier_sha256=sha(vpath) if vpath.exists() else None,
            status=verification['status'] if verification else 'NOT_ACCREDITED',
            evidence_origin='PRESERVED_REAL_EXECUTION_ARTIFACTS',replayed_events=False,
            confirmed_base_reference=executor['confirmed_base_reference'],
            actual_execution_error=executor['error'])
        if executor['error']:
            actual_offers=lines(directory/'schedule-offers.jsonl')
            actual_cuts=lines(directory/'snapshots.jsonl')
            value['load_executed']=bool(actual_offers)
            value['actual_offers']=len(actual_offers)
            value['actual_acceptances_by_org']=dict(Counter(
                o['organization_id'] for o in actual_offers if o['outcome']=='ACCEPTED_DURABLE'))
            value['observed_snapshot_stages']=[c['stage'] for c in actual_cuts]
            value['failure_stage']=('AFTER_REAL_OFFERS; FINAL_ANALYSIS_NOT_COMPLETED'
                                    if actual_offers else 'PREPARATION_BEFORE_FIRST_OFFER')
            value['population_conflict']=executor.get('population_conflict')
            values.append(value)
            continue
        report=read(directory/'job-result.json')
        offers=lines(directory/'schedule-offers.jsonl')
        cuts=lines(directory/'snapshots.jsonl')
        slots=read(directory/'schedule.json')
        start=min(s['due_monotonic_ns'] for s in slots)
        end=start+read(directory/'participant-plan.json')['offer_seconds']*1_000_000_000
        counts=Counter(o['organization_id'] for o in offers if o['outcome']=='ACCEPTED_DURABLE')
        value.update(load_executed=True,actual_acceptances_by_org=dict(counts),
            population=report['population'],episode_outcomes=report['summary'],
            episode_origins=[dict(episode_id=e['episode_id'],organization_id=e['organization_id'],
                conversation_id=e['conversation_id'],members=e['member_ids'],
                ready_ns_bounds=e['ready_ns_bounds'],claim_commit_ns_bounds=e['claim_commit_ns_bounds'],
                wait_seconds_bounds=e['wait_seconds_bounds']) for e in report['episodes']],
            declared_offer_window_monotonic_ns=[start,end],
            actual_first_offer_to_last_ack_seconds=(offers[-1]['finished_monotonic_ns']-offers[0]['started_monotonic_ns'])/1e9,
            queue_cuts=report['queue_samples'],invariants=verification.get('invariants') if verification else None,
            actual_phase_markers=lines(directory/'physical-phases.jsonl'))
        phases=[]
        for cut in cuts:
            if cut['stage'] not in ('initial','physical-burst','physical-base-return','offer_end','final'):
                continue
            accepted=[o for o in offers if o['outcome']=='ACCEPTED_DURABLE' and o['offered_db_ns_bounds'][1]<=cut['db_ns']]
            ids={o['message_id'] for o in accepted}
            uncertain=[o['attempt'] for o in offers if o['offered_db_ns_bounds'][0]<=cut['db_ns']<o['offered_db_ns_bounds'][1]]
            observed={m['id'] for m in cut['messages']}
            orgs={}
            for org in counts:
                msgs=[m for m in cut['messages'] if m['organization_id']==org]
                works=[w for w in cut['works'] if w['organization_id']==org]
                accepted_org={o['message_id'] for o in accepted if o['organization_id']==org}
                orgs[str(org)]=dict(accepted_inputs_by_cut=len(accepted_org),
                    census_inputs=len(msgs),assigned_ids=[m['id'] for m in msgs if m['turn_work_id'] is not None],
                    unassigned_ids=[m['id'] for m in msgs if m['turn_work_id'] is None],
                    nonterminal_work_ids=[w['id'] for w in works if w['status']!='COMPLETED'],
                    missing_accepted_ids=sorted(accepted_org-observed))
            phases.append(dict(stage=cut['stage'],actual_db_ns=cut['db_ns'],organizations=orgs,
                acceptance_interval_crossing_cut=uncertain,missing_accepted_ids=sorted(ids-observed)))
        value['phase_reconciliation']=phases
        if (directory/'causal-observation-summary.json').exists():
            value['causal_observations']=read(directory/'causal-observation-summary.json')
        values.append(value)
    write(HERE/'actual-attempt-audit.json',dict(
        scope='OFFLINE_RECONCILIATION_OF_PHYSICAL_CAPTURE_NOT_NEW_EXECUTION_OR_REPLAY',
        attempts=values,failures_retained=True,base_modified=False))
    print('Audited preserved actual attempts:',len(values),flush=True)


if __name__=='__main__':
    main()
