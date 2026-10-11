"""Independent reconstruction of fixed-load physical evidence; no DB/load."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from apps.agent.tests.scheduling_characterization.assessment import assess, invariant_gate
from apps.agent.tests.scheduling_characterization.controller import digest
from apps.agent.tests.scheduling_characterization.evidence import NS, ClockMap, Interval, reconstruct
from apps.agent.tests.scheduling_characterization.execution import queued_samples, read_capture, read_lines
from apps.agent.tests.scheduling_characterization.recipes import verify_recipe
from apps.agent.tests.scheduling_characterization.scenario_observations import observations
from load_case import common_calendar, plan_calendar, read, sha, validate_base


def normalized(value):
    return json.loads(json.dumps(value))


def verify(job_path, directory):
    job = read(job_path)
    unsigned = dict(job)
    seal = unsigned.pop('job_sha256')
    errors = []
    base = validate_base(job['confirmed_base_reference'])
    if digest(unsigned) != seal:
        errors.append('JOB_CHANGED_AFTER_SEAL')
    executor = read(directory / 'dependent-executor-receipt.json')
    if executor['job_sha256'] != seal or executor['confirmed_base_reference'] != job['confirmed_base_reference']:
        errors.append('EXECUTOR_PROVENANCE_MISMATCH')
    common = dict(schema='d29-dependent-physical-verification-v1', run_id=job['run_id'], case_id=job['case_id'],
        variant=job['variant'], job_sha256=seal, confirmed_base_reference=job['confirmed_base_reference'],
        base_recalibrated=False, new_base_generated=False, sustainable_envelope=None, commercial_capacity=None,
        evidence_synthetic=[], physical_frontier={'status': 'NOT_ACCREDITED'},
        load_condition={'status': 'NOT_ACCREDITED'}, prerequisites=[{'name': 'CONFIRMED_BASE', 'status': 'ACCEPTED'}])
    if executor['error']:
        return dict(common, status='NOT_ACCREDITED', errors=errors+['EXECUTOR_REJECTED_SCENARIO'], cause=executor['error'],
            population_conflict=executor.get('population_conflict'), physical_evidence=[], verifier_passed=False)
    original = read(directory / 'job-result.json')
    participant = read(directory / 'participant-plan.json')
    if {k: v for k, v in participant.items() if k != 'organization_ids'} != job:
        errors.append('PARTICIPANT_JOB_CHANGED')
    orgs = participant['organization_ids']
    cuts = read_lines(directory / 'snapshots.jsonl')
    final = next(s for s in reversed(cuts) if s['stage'] == 'final')
    ledger = read_lines(directory / 'offers.jsonl')
    offers = read_lines(directory / 'schedule-offers.jsonl')
    if [{k: o[k] for k in ledger[0]} for o in offers] != ledger:
        errors.append('INGRESS_LEDGERS_DISAGREE')
    journals = read_capture(directory)
    report = reconstruct(journals, offers, final['messages'], Interval(final['db_ns'], final['db_ns']), run_id=job['run_id'])
    roles = {j[0]['worker']: j for j in journals}
    pids = {r: j[0]['os_pid'] for r, j in roles.items()}
    if len(set(pids.values())) != 4:
        errors.append('FOUR_SEPARATE_PROCESSES_REQUIRED')
    spans = {}
    for role in ('planner_1', 'planner_2'):
        polls = [r['monotonic_ns'] for r in roles[role] if r['event'] == 'poll_start']
        spans[role] = [min(polls), max(polls)] if polls else None
    if not all(spans.values()) or max(s[0] for s in spans.values()) >= min(s[1] for s in spans.values()):
        errors.append('CONCURRENT_PLANNERS_NOT_OBSERVED')
    all_wire = [r for role in ('planner_1', 'planner_2', 'sender') for r in read_lines(directory / (role+'-wire.jsonl'))]
    dispatches = [r for r in all_wire if r['event'] == 'dispatch']
    invariant = invariant_gate(report, journals, final['messages'], final['works'], dispatches, orgs)
    results = [r for r in all_wire if r['event'] == 'result']
    calls = defaultdict(list)
    for r in results:
        if r['boundary'] == 'llm':
            calls[r['turn_work_id']].append(r)
    if job['case_id'].startswith('R1-'):
        for e in report['episodes']:
            values = calls[e['turn_work_id']]
            if len(values) != 2 or {r['call_number'] for r in values} != {1, 2} or any(r['elapsed_ns'] < NS/2 for r in values):
                errors.append('BASE_LLM_COST_NOT_COMPLETELY_OBSERVED')
        metas = [r for r in results if r['boundary'] == 'meta']
        if len(metas) != len(report['episodes']) or any(r['elapsed_ns'] < NS/5 or r['result'] != 'ACCEPTED' for r in metas):
            errors.append('BASE_META_COST_NOT_COMPLETELY_OBSERVED')
    slots = read(directory / 'schedule.json')
    start = min(s['due_monotonic_ns'] for s in slots)
    expected = (common_calendar if job['case_id'] == 'R1-03' else plan_calendar)(job, start)
    if expected != slots:
        errors.append('BASE_DERIVED_CALENDAR_CHANGED')
    offsets = list(range(0, job['offer_seconds']+1, 120))
    if offsets[-1] != job['offer_seconds']:
        offsets.append(job['offer_seconds'])
    clock = ClockMap(roles['ingress'])
    intervals = [Interval(start+o*NS+clock.offset.lo, start+o*NS+clock.offset.hi) for o in offsets]
    queues = queued_samples(report, offsets, intervals)
    if job['case_id'] == 'R1-04':
        events = []
        errors.append('CONCURRENT_PRE_QUERY_FORECAST_YIELD_AND_SUPERSESSION_WITNESSES_MISSING')
    elif job['case_id'] == 'R1-05':
        markers = read_lines(directory / 'physical-phases.jsonl')
        first = next((r for r in markers if r['phase'] == 'burst'), None)
        returned = next((r for r in markers if r['phase'] == 'base-return'), None)
        events = []
        for name, row in [('burst_begin', first), ('burst_end', returned), ('base_return', returned), ('drain_cut', final)]:
            if row:
                match = next((s for s in cuts if s['stage'] == row.get('snapshot_stage')), final if name == 'drain_cut' else None)
                if match is None or match['db_ns'] != row['db_ns']:
                    errors.append('PHASE_MARKER_WITHOUT_PHYSICAL_SNAPSHOT')
                events.append(dict(event=name, run_id=job['run_id'], organization_index=0, db_ns=row['db_ns'],
                    observed=True, source='INDEPENDENT_DB_WITNESS', evidence='snapshots.jsonl', actual_boundary=True))
    else:
        events = observations(participant, report, journals, dispatches, read_lines, directory, final)
    prep = dict(fresh_database=True, participants_ready_before_offer=True, source_integrity=True,
        capture_all_participants=not report['issues'], durable_database=True, contained_provider=True)
    recomputed = assess(participant, report, offers=offers, scheduled=slots, organizations=orgs,
        offer_span=(intervals[0].lo, intervals[-1].hi), queue_samples=queues, journals=journals,
        census=final['messages'], works=final['works'], wire=dispatches, preparation=prep,
        recipe=verify_recipe(participant, events))
    for k in ('population', 'episodes', 'summary', 'gates', 'dispositions', 'issues', 'uncertain_transactions'):
        if normalized(recomputed[k]) != original[k]:
            errors.append('RAW_RECOMPUTATION_DISAGREES:'+k)
    if normalized(queues) != original['queue_samples'] or normalized(events) != original['scenario_events']:
        errors.append('SCENARIO_OR_QUEUE_RECOMPUTATION_DISAGREES')
    accepted = [o for o in offers if o['outcome'] == 'ACCEPTED_DURABLE']
    counts = Counter(orgs.index(o['organization_id']) for o in accepted)
    by_org = {str(org): sorted({e['conversation_id'] for e in report['episodes'] if e['organization_id'] == org}) for org in orgs}
    if job['case_id'] == 'R1-03':
        balanced = plan_calendar(dict(job, case_id='R1-02', offered_rates_per_minute=job['confirmed_base_rates']), start)
        if [s['due_monotonic_ns'] for s in slots] != [s['due_monotonic_ns'] for s in balanced]:
            errors.append('GLOBAL_CADENCE_NOT_PRESERVED')
        if counts[0] != 2*counts[1] or sum(counts.values()) != len(balanced):
            errors.append('ACTUAL_ACCEPTANCE_GEOMETRY_NOT_2_TO_1')
    if job['case_id'].startswith('R1-') and any(len(cs) != job['conversations_per_org'] for cs in by_org.values()):
        errors.append('ACCEPTED_THREE_CONVERSATION_POPULATION_NOT_OBSERVED')
    resolved = all(m['turn_work_id'] is not None for m in final['messages'] if m['direction'] == 'in') and all(w['status']=='COMPLETED' for w in final['works'])
    if not resolved:
        errors.append('DRAIN_OBLIGATIONS_NOT_RESOLVED')
    if recomputed['dispositions'] not in (['OBSERVED_COMPATIBLE'], ['FAULT_OBSERVATION_COMPLETE_COVERAGE_PENDING']):
        errors.extend(['OBSERVATION_GATES_NOT_SATISFIED'] + recomputed['dispositions'])
    if invariant['missing'] or invariant['violations']:
        errors.append('INVARIANTS_NOT_DECIDABLE_OR_FAILED')
    errors = sorted(set(errors))
    common['physical_frontier'] = dict(status='PHYSICALLY_ACCREDITED' if not recomputed['gates']['scenario']['missing'] and not recomputed['gates']['scenario']['violations'] else 'NOT_ACCREDITED', recipe=recomputed['gates']['scenario'])
    load_errors = [e for e in errors if e != 'CONCURRENT_PRE_QUERY_FORECAST_YIELD_AND_SUPERSESSION_WITNESSES_MISSING']
    common['load_condition'] = dict(status='PHYSICALLY_ACCREDITED' if not load_errors else 'NOT_ACCREDITED',
        gates=recomputed['gates'], rates=job['offered_rates_per_minute'], offer_seconds=job['offer_seconds'],
        actual_acceptances_by_org_index=dict(counts), conversations_by_org=by_org, obligations_resolved=resolved)
    waits = [e['wait_seconds_bounds'][1] for e in report['episodes'] if e.get('wait_seconds_bounds') and e['wait_seconds_bounds'][1] is not None]
    return dict(common, status='PHYSICALLY_ACCREDITED' if not errors else 'NOT_ACCREDITED',
        errors=errors, verifier_passed=not errors, population=report['population'], summary=report['summary'],
        maximum_wait_upper_seconds=max(waits, default=None), invariants=invariant,
        participant_pids=pids, planner_spans=spans, physical_evidence=[p.name for p in directory.iterdir() if p.suffix=='.jsonl'],
        executor_dispositions=original['dispositions'], independent_dispositions=recomputed['dispositions'],
        receipt_sha256=sha(directory/'job-result.json'))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--job', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = verify(Path(a.job), Path(a.output))
    with (Path(a.output)/'independent-verification.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({k:result[k] for k in ('case_id','variant','run_id','status','errors')}), flush=True)
