"""Finite committed-crash prelude plus immutable base window S=L-P."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from guarded import guarded
from reclaim_fixture import prepare_prelude, base_plan
from load_case import validate_base
from apps.agent.tests.scheduling_characterization import execution
from apps.agent.tests.scheduling_characterization.runner import bootstrap, require_empty_database, network_denied, source_manifest, write_json
from apps.agent.tests.scheduling_characterization.physical import Session
from apps.agent.tests.scheduling_characterization.evidence import timestamp, NS

def main():
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();job=json.loads(Path(a.job).read_text());d=Path(a.output)
    validate_base(job['confirmed_base_reference'])
    plan=base_plan(job['confirmed_base_reference']['path'])
    assert job['case_id']=='R2-04' and job['offered_rates_per_minute']==plan['rates']
    assert job['conversations_per_org']==3 and job['offer_seconds']==360 and job['followup_seconds']==240
    assert job['job_sha256']==execution.digest({k:v for k,v in job.items() if k!='job_sha256'})
    bootstrap();require_empty_database();execution.verify_sources()
    from apps.agent import durable
    d.mkdir(parents=True,exist_ok=False);source_manifest(d);write_json(d/'sealed-job.json',job)
    s=Session(d,'R2-04',job['variant'],job['run_id'])
    receipt=dict(status='NOT_ACCREDITED',error=None,phase='PRELUDE',base_reference=job['confirmed_base_reference'])
    processes=[]
    def progress(phase, **data):
        execution.append(d/'phase-observations.jsonl',dict(phase=phase,monotonic_ns=time.perf_counter_ns(),**data))
    try:
        with guarded(d), network_denied(), s.recorder.capture('ingress'):
            s.seed(2)
            prep,witness,old=prepare_prelude(s,job['confirmed_base_reference']['path'])
            write_json(d/'prelude-history.json',old)
            due=prep['window']['natural_expiry_db_ns'];target=prep['window']['start_db_ns']
            participant=dict(job,organization_ids=[f[0].pk for f in s.fixtures])
            # Crash has exited before replacement planners are launched.
            with execution.participants(d,participant) as processes:
                low=time.perf_counter_ns();db=timestamp(durable.db_now().isoformat());high=time.perf_counter_ns()
                if db>=target:raise RuntimeError('PARTICIPANTS_PREPARATION_MISSED_FIXED_S')
                # Latest bound of the physical DB calibration anchors the calendar
                # once. Subsequent observations never move S or scheduled slots.
                start=high+target-db
                anchor=dict(sample_db_ns=db,sample_monotonic_ns_bounds=[low,high],
                    target_db_ns=target,start_monotonic_ns=start,lease_expiry_db_ns=due,
                    cadence_ns=plan['lead_to_natural_expiry_ns'])
                write_json(d/'fixed-anchor.json',anchor)
                slots=execution.schedule(job,start);write_json(d/'schedule.json',slots)
                progress('WAIT_FIXED_S',target_db_ns=target)
                while time.perf_counter_ns()<start:
                    execution.health(processes)
                    # Real DB clocks remain observed throughout the long lease.
                    durable.db_now()
                    time.sleep(min(.2,max(.001,(start-time.perf_counter_ns())/NS)))
                begin,bp=s.snap('base-begin');s.recorder.snapshot('base-begin')
                progress('BASE_OPEN',db_ns=begin['db_ns'],snapshot=bp)
                expiry_seen=False
                def check():
                    nonlocal expiry_seen
                    execution.health(processes)
                    now=timestamp(durable.db_now().isoformat())
                    if not expiry_seen and now>=due:
                        expiry_seen=True
                        snap,path=s.snap('natural-expiry')
                        progress('EXPIRY_OBSERVED',db_ns=snap['db_ns'],snapshot=path)
                for n,slot in enumerate(slots):
                    while time.perf_counter_ns()<slot['due_monotonic_ns']:
                        check();time.sleep(min(.05,max(.001,(slot['due_monotonic_ns']-time.perf_counter_ns())/NS)))
                    row=execution.offer(s.recorder,s.fixtures[slot['organization_index']],n%3,slot,phase='ORDINARY')
                    if row is None:raise RuntimeError('BASE_INGRESS_NOT_ACCEPTED')
                    execution.append(d/'population-slots.jsonl',dict(message_id=row.pk,slot=n%3,
                        organization_id=row.organization_id,conversation_id=row.conversation_id,schedule_id=slot['id']))
                    check()
                end=start+job['offer_seconds']*NS
                while time.perf_counter_ns()<end:
                    check();time.sleep(.05)
                closed,cp=s.snap('base-end');s.recorder.snapshot('offer_end')
                follow_start=time.perf_counter_ns()
                progress('BASE_CLOSED_FOLLOWUP_BEGIN',db_ns=closed['db_ns'],snapshot=cp,follow_start_ns=follow_start)
                follow_end=follow_start+job['followup_seconds']*NS
                while time.perf_counter_ns()<follow_end:
                    check();time.sleep(.2)
                final,fp=s.snap('final');s.recorder.snapshot('final')
                finished=time.perf_counter_ns()
                progress('FOLLOWUP_END',db_ns=final['db_ns'],snapshot=fp,finished_ns=finished)
            # A stale witness is tested after participant exit, so no competing
            # output can invalidate the before/after no-effect observation.
            s.fence(witness)
            write_json(d/'observed-window.json',dict(begin_cut=begin,end_cut=closed,
                final_cut=final,natural_expiry_db_ns=due,follow_start_ns=follow_start,follow_end_ns=finished))
            receipt.update(status='OBSERVED_PENDING_INDEPENDENT_VERIFICATION',phase='COMPLETE',
                expiry_observed=expiry_seen,worker_exit_codes=[p.returncode for p in processes])
    except Exception as exc:
        receipt.update(status='INVALID_RUN' if (d/'clock-invalid.json').exists() else 'NOT_ACCREDITED',
            error=dict(type=type(exc).__name__,message=str(exc)))
    finally:
        s.cleanup()
        receipt.update(events=s.events,checks=s.checks)
        write_json(d/'execution-receipt-v2.json',receipt)
    print(json.dumps(receipt),flush=True)

if __name__=='__main__':main()
