"""Evaluation copy of execute_job: natural R209 initial cohort and full followup.
Original gates and analysis remain in use. See adaptation-seal.json.
"""
from apps.agent.tests.scheduling_characterization.execution import *
from apps.agent.tests.scheduling_characterization import execution
from launch_bridge import participants

def offer(*args, **kwargs):
    return execution.offer(*args, **kwargs)

def health(processes):
    return execution.health(processes)

def execute_job(directory, job, *, finite=False):
    """Run a fresh isolated job; each calibration episode waits its real claim."""
    bootstrap()
    require_empty_database()
    verify_sources()
    if not finite and job['case_id'] not in DIRECT_LOAD_CASES:
        raise RuntimeError('This scenario needs its boundary injection adapter; ordinary fallback is forbidden')
    directory.mkdir(parents=True, exist_ok=False)
    source_manifest(directory)
    write_json(directory / 'sealed-job.json', job)
    from apps.agent.tests.test_b9a_e2e import seed_domain
    from apps.agent import durable
    fixtures = [seed_domain('D29C-' + job['run_id'] + '-' + str(i)) for i in range(job['organization_count'])]
    job = dict(job, organization_ids=[f[0].pk for f in fixtures])
    recorder = Recorder(directory, job['run_id'])
    slots, offsets, mono_cuts = [], [], []
    events = []
    with network_denied(), recorder.capture('ingress'):
      if not finite and job['case_id'] == 'R1-06':
        for org, rate in enumerate(job['offered_rates_per_minute']):
            needed = math.ceil(rate * 2)
            if needed > job['conversations_per_org']:
                raise ValueError('Backlog needs distinct conversations; seal a new plan with sufficient fixture size')
            for slot in range(needed):
                row = offer(recorder, fixtures[org], slot, phase='BACKLOG')
                if row is None:
                    raise RuntimeError('Backlog ingress unresolved')
        from apps.agent.tests.scheduling_characterization.runner import wait_ready
        for row in __import__('apps.channels.models', fromlist=['Message']).Message.objects.filter(direction='in'):
            wait_ready(row)
        recorder.snapshot('backlog_ready_before_workers')
      if not finite and job['case_id'] == 'R2-09':
        from apps.agent.tests.scheduling_characterization.runner import wait_ready
        initial_rows = []
        for fixture in fixtures:
            for slot in range(3):
                row = offer(recorder, fixture, slot, phase='INITIAL_READY')
                if row is None:
                    raise RuntimeError('INITIAL_READY_INGRESS_UNRESOLVED')
                initial_rows.append(row)
        for row in initial_rows:
            wait_ready(row)
        recorder.snapshot('initial_ready_before_workers')
      with participants(directory, job) as processes:
        first = recorder.snapshot('initial')
        start = time.perf_counter_ns()
        if finite or job['phase'] == 'CALIBRATE':
            count = 1 if finite else job['calibration_episodes_per_org']
            for n in range(count):
                for f in fixtures:
                    row = offer(recorder, f, n % job['conversations_per_org'])
                    if row is None or wait_claim(row, processes) is None:
                        raise RuntimeError('Calibration/probe input unresolved; no reference can be derived')
            # Claims alone are not a service witness. Wait for this finite
            # population to finish and for sender disposition to be visible.
            # A finite R2-02 probe must observe the declared real provider hold
            # before stopping participants. This changes no lease/load policy.
            followup = 45 + (job['blocked_llm_hold_seconds'] if finite and job['case_id'] == 'R2-02' else 0)
            end = time.monotonic() + followup
            while True:
                snap = recorder.snapshot('finite_followup')
                if snap['works'] and all(w['status'] == 'COMPLETED' for w in snap['works']):
                    from apps.channels.models import Message
                    resolved = Message.objects.filter(direction='out', provider_accepted_at__isnull=False).count()
                    # The finite negative sender probe must retain uncertainty;
                    # it is a terminal observation, never provider acceptance.
                    if finite and job['case_id'] == 'R2-09' and job['variant'] == 'uncertain_meta':
                        resolved += Message.objects.filter(direction='out', status='uncertain',
                            organization_id=job['organization_ids'][0]).count()
                    if resolved == count * len(fixtures):
                        break
                health(processes)
                if time.monotonic() >= end:
                    raise RuntimeError('Finite service/sender did not resolve')
                time.sleep(.1)
        else:
            slots = schedule(job, start)
            offsets = list(range(0, job['offer_seconds'] + 1, 120))
            if offsets[-1] != job['offer_seconds']:
                offsets.append(job['offer_seconds'])
            mono_cuts = [start + offset * NS for offset in offsets]
            write_json(directory / 'schedule.json', slots)
            for n, slot in enumerate(slots):
                while time.perf_counter_ns() < slot['due_monotonic_ns']:
                    health(processes)
                    time.sleep(min(.05, (slot['due_monotonic_ns'] - time.perf_counter_ns()) / NS))
                offer(recorder, fixtures[slot['organization_index']], n % job['conversations_per_org'], slot)
            offer_end = start + job['offer_seconds'] * NS
            while time.perf_counter_ns() < offer_end:
                health(processes)
                time.sleep(.05)
            recorder.snapshot('offer_end')
            follow_end = time.monotonic() + job['followup_seconds']
            while time.monotonic() < follow_end:
                health(processes)
                snap = recorder.snapshot('followup')
                time.sleep(.25)
        final = recorder.snapshot('final')
    journals = read_capture(directory)
    report = reconstruct(journals, recorder.offers, final['messages'], Interval(final['db_ns'], final['db_ns']), run_id=job['run_id'])
    dispatches = [e for role in ('planner_1', 'planner_2', 'sender')
                  for e in read_lines(directory / (role + '-wire.jsonl')) if e['event'] == 'dispatch']
    from apps.agent.tests.scheduling_characterization.assessment import invariant_gate
    invariant = invariant_gate(report, journals, final['messages'], final['works'], dispatches, job['organization_ids'])
    preparation = dict(fresh_database=True, participants_ready_before_offer=True, source_integrity=verify_sources(),
                       capture_all_participants=not report['issues'], durable_database=True, contained_provider=True)
    if finite:
        result = dict(report, job_sha256=job['job_sha256'], source_kind='ISOLATED_LIVE',
                      dispositions=['FINITE_PIPELINE_PROBE_NOT_LEVEL_ACCEPTANCE'], benchmark=False,
                      checks=dict(inputs=len(recorder.offers) == job['organization_count'],
                          cohort_complete=not report['issues'], within_observed=report['summary']['OBSERVED_WITHIN_TARGET'] == len(fixtures),
                          independent_wire_invariants=not invariant['missing'] and not invariant['violations'],
                          participants_exited_normally=all(p.returncode == 0 for p in processes)),
                      invariants=invariant, calibration_reference_by_org_index=None)
    elif job['phase'] == 'CALIBRATE':
        refs = []
        for org in job['organization_ids']:
            episodes = [e for e in report['episodes'] if e['organization_id'] == org]
            duration = max(e['claim_commit_ns_bounds'][1] for e in episodes) - min(e['ready_ns_bounds'][0] for e in episodes)
            refs.append(60 * NS * len(episodes) / duration if duration > 0 else None)
        valid = (not report['issues'] and not invariant['missing'] and not invariant['violations']
                 and report['summary']['OBSERVED_WITHIN_TARGET'] == len(fixtures) * job['calibration_episodes_per_org'])
        result = dict(report, job_sha256=job['job_sha256'], source_kind='ISOLATED_LIVE', invariants=invariant,
                      dispositions=['CALIBRATION_REFERENCE_OBSERVED'] if valid else ['INDETERMINATE'],
                      calibration_reference_by_org_index=refs if valid else None)
    else:
        clock = ClockMap(next(j for j in journals if j[0]['worker'] == 'ingress'))
        if clock.offset is None:
            raise RuntimeError('Offer/window clock not calibrated')
        intervals = [Interval(t + clock.offset.lo, t + clock.offset.hi) for t in mono_cuts]
        queues = queued_samples(report, offsets, intervals)
        # Required boundaries are derived from observations. Missing advanced
        # cases remain INDETERMINATE instead of being inferred from case IDs.
        from apps.agent.tests.scheduling_characterization.scenario_observations import observations
        events = observations(job, report, journals, dispatches, read_lines, directory, final)
        result = assess(job, report, offers=recorder.offers, scheduled=slots, organizations=job['organization_ids'],
                        offer_span=(intervals[0].lo, intervals[-1].hi), queue_samples=queues,
                        journals=journals, census=final['messages'], works=final['works'], wire=dispatches,
                        preparation=preparation, recipe=verify_recipe(job, events))
        result.update(job_sha256=job['job_sha256'], scenario_events=events, queue_samples=queues,
                      rates_note='Nominal input pacing and actual READY episodes are reported separately; natural deadlines unchanged.')
    write_json(directory / 'job-result.json', result)
    return result
