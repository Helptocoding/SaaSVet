import argparse
import json
import sys
import time
from pathlib import Path

from apps.agent.tests.scheduling_characterization.runner import bootstrap, network_denied, source_manifest, write_json
from apps.agent.tests.scheduling_characterization.physical import Session, independent, read, timestamp, wait_db
from apps.agent.tests.scheduling_characterization.physical_cases import crash_committed
from apps.agent.tests.scheduling_characterization import execution

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--run-id', required=True)
a = parser.parse_args()
bootstrap()
from apps.agent import durable
directory = Path(a.output)
directory.mkdir(parents=True, exist_ok=False)
source_manifest(directory)
case, variant, run_id = 'R2-04', 'postcommit_base_concurrent', a.run_id
s = Session(directory, case, variant, run_id)
result = {'case_id':case,'variant':variant,'run_id':run_id,'status':'NOT_ACCREDITED','baseline':execution.BASELINE,
          'lease_seconds':900,'followup_seconds':240,'offer_seconds':360,'base_recalibrated':False,'new_base_generated':False,
          'characterization':False,'synthetic_evidence':[],'checks':[],'events':[]}
try:
    with network_denied(), s.recorder.capture('driver'):
        s.seed(2)
        row, witness, old, before, before_path = crash_committed(s)
        exitfile = s.kill('crash')
        due = timestamp(old['lease_expires_at'])
        s.event('postcommit_crash', [exitfile], source='PROCESS_EXIT')
        s.check('lease_is_900_seconds', abs((timestamp(old['lease_expires_at']) - timestamp(old['claimed_at'])) / 1_000_000_000 - 900) < 2, [before_path])
        base_job = dict(case_id=case, variant=variant, run_id=run_id, organization_ids=[f[0].pk for f in s.fixtures],
                        organization_count=2, conversations_per_org=3, offered_rates_per_minute=[1.9607508002652434,1.9607508002652434],
                        offer_seconds=360, followup_seconds=240, burst_multiplier=2.0, burst_seconds=120,
                        slow_multiplier=2, blocked_llm_hold_seconds=120)
        start_due = due - 240 * 1_000_000_000
        from datetime import datetime, timezone
        wait_db(datetime.fromtimestamp(start_due / 1_000_000_000, tz=timezone.utc))
        start = time.perf_counter_ns()
        slots = execution.schedule(base_job, start)
        write_json(directory/'base-schedule.json', slots)
        s.event('base_offer_window_open', ['base-schedule.json'], due_db_ns=due, start_monotonic_ns=start)
        expiry_mono = None
        reclaimed = None
        before_orgs, after_orgs = set(), set()
        with execution.participants(directory, base_job) as processes:
            for n, slot in enumerate(slots):
                while time.perf_counter_ns() < slot['due_monotonic_ns']:
                    execution.health(processes)
                    if expiry_mono is None and timestamp(durable.db_now().isoformat()) >= due:
                        expiry_mono = time.perf_counter_ns(); _, path = s.snap('natural-expiry'); s.event('natural_expiry',[path],due_db_ns=due)
                    time.sleep(min(.05, max(.001, (slot['due_monotonic_ns']-time.perf_counter_ns())/1_000_000_000)))
                execution.offer(s.recorder, s.fixtures[slot['organization_index']], n % 3, slot, phase='BASE_CONCURRENT')
                finished = s.recorder.offers[-1].get('finished_monotonic_ns', time.perf_counter_ns())
                if expiry_mono is None and timestamp(durable.db_now().isoformat()) >= due:
                    expiry_mono = finished; _, path = s.snap('natural-expiry'); s.event('natural_expiry',[path],due_db_ns=due)
                (after_orgs if expiry_mono is not None and finished >= expiry_mono else before_orgs).add(slot['organization_index'])
                snap = independent()
                candidate = next((w for w in snap['works'] if w['id']==old['id'] and w['attempts']>old['attempts'] and w['lease_fingerprint']!=old['lease_fingerprint']), None)
                if candidate and reclaimed is None:
                    reclaimed = candidate; _, path = s.snap('reclaimed'); s.event('natural_reclaim',[path],same_work=True)
            offer_end = start + 360 * 1_000_000_000
            while time.perf_counter_ns() < offer_end:
                execution.health(processes)
                if expiry_mono is None and timestamp(durable.db_now().isoformat()) >= due:
                    expiry_mono = time.perf_counter_ns(); _, path = s.snap('natural-expiry'); s.event('natural_expiry',[path],due_db_ns=due)
                snap = independent()
                candidate = next((w for w in snap['works'] if w['id']==old['id'] and w['attempts']>old['attempts'] and w['lease_fingerprint']!=old['lease_fingerprint']), None)
                if candidate and reclaimed is None:
                    reclaimed = candidate; _, path = s.snap('reclaimed'); s.event('natural_reclaim',[path],same_work=True)
                time.sleep(.25)
            s.snap('offer-end')
            follow_start = time.monotonic()
            while time.monotonic() - follow_start < 240:
                execution.health(processes)
                snap = independent()
                candidate = next((w for w in snap['works'] if w['id']==old['id'] and w['attempts']>old['attempts'] and w['lease_fingerprint']!=old['lease_fingerprint']), None)
                if candidate and reclaimed is None:
                    reclaimed = candidate; _, path = s.snap('reclaimed'); s.event('natural_reclaim',[path],same_work=True)
                time.sleep(.5)
            final, final_path = s.snap('final')
        s.check('expiry_observed', expiry_mono is not None, [next((p for p in s.snapshots if 'natural-expiry' in p), before_path)])
        s.check('natural_reclaim_observed', reclaimed is not None, [next((p for p in s.snapshots if 'reclaimed' in p), before_path)])
        s.check('base_offer_before_and_after_expiry', bool(before_orgs) and bool(after_orgs), ['schedule-offers.jsonl','base-schedule.json'])
        s.check('both_orgs_before_after', before_orgs == {0,1} and after_orgs == {0,1}, ['schedule-offers.jsonl'])
        s.check('full_followup_240_seconds', time.monotonic() - follow_start >= 240, [final_path])
        passed = bool(reclaimed) and before_orgs == {0,1} and after_orgs == {0,1}
        result.update(status='PHYSICALLY_ACCREDITED' if passed else 'NOT_ACCREDITED', checks=s.checks, events=s.events,
                      old_work=old, reclaimed_work=reclaimed, before_orgs=sorted(before_orgs), after_orgs=sorted(after_orgs),
                      expiry_monotonic_ns=expiry_mono, physical_evidence=True,
                      load_condition={'status':'PHYSICALLY_ACCREDITED' if passed else 'NOT_ACCREDITED'})
except Exception as exc:
    result.update(status='NOT_ACCREDITED', error={'class':type(exc).__name__,'message':str(exc)}, checks=s.checks, events=s.events)
finally:
    s.cleanup()
    result['cleanup'] = read(directory/'participants-cleanup.json') if (directory/'participants-cleanup.json').exists() else None
    write_json(directory/'r204-receipt.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
