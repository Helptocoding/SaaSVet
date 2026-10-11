"""Derive diagnosis and preparation manifests from immutable evidence only."""
import hashlib
import json
import math
from pathlib import Path
from clock_guard import ClockInvalid, Continuity
from reclaim_fixture import base_plan

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / 'docs/evals/d29-dependent-2026-10-07'
BASE = ROOT / 'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def ref(path):
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def write(name, value):
    with (HERE/name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    base = read(BASE)
    old_clock = read(PRIOR/'clock-capture-audit.json')
    clock = next(r for r in old_clock['attempts'] if r['run_id'] == 'matrix-existing-R103-unequal')
    first_failures = {}
    for role in ('ingress', 'planner_1', 'planner_2', 'sender'):
        source = PRIOR/'matrix-existing/matrix-existing-R103-unequal'/(role+'.jsonl')
        state = Continuity()
        for line, row in enumerate(lines(source), 1):
            try:
                state.feed(row)
            except ClockInvalid as exc:
                first_failures[role] = dict(reason=str(exc), line=line, seq=row['seq'],
                    db_timestamp=row.get('db_timestamp'), offset_bounds_ns=[state.lo, state.hi], source=ref(source))
                break
    write('clock-diagnosis.json', dict(scope='READ_ONLY_OLD_CAPTURE_DIAGNOSIS', prior_run_still_invalid=True,
        broken_relation='POSTGRESQL_CLOCK_TIMESTAMP_VS_SAME_HOST_PERF_COUNTER_NS_CONSTANT_OFFSET',
        raw_offset_audit=clock, first_detectable_failures=first_failures,
        host_clock_events=ref(PRIOR/'host-clock-events.json'), host_power_events=ref(HERE/'host-power-events.json'),
        cause='HOST_IDLE_SLEEP_RESUME_AND_HARDWARE_WALL_CLOCK_RESYNCHRONIZATION_OBSERVED',
        limit='17.519s host wall correction is not the approximately 55ms residual offset contradiction; no standalone PostgreSQL or runtime bug established.',
        implementation_prepared=['clock_guard.py', 'host-event-cut.ps1', 'prepared_probe.py'],
        mathematical_gate_unchanged=True, physical_resolution_demonstrated=False))

    p = PRIOR/'matrix-existing/matrix-existing-R202-blocked'
    report = read(p/'job-result.json')
    events = [r for f in p.glob('*-events.jsonl') for r in lines(f)]
    begin = next(r['db_ns'] for r in events if r['event'] == 'block_begin')
    end = next(r['db_ns'] for r in events if r['event'] == 'block_release')
    offers = lines(p/'schedule-offers.jsonl')
    in_hold = [o for o in offers if o['organization_id'] == 1 and begin < o['offered_db_ns_bounds'][0] <= o['offered_db_ns_bounds'][1] < end]
    membership = {mid: dict(conversation_id=e['conversation_id'], episode_id=e['episode_id']) for e in report['episodes'] for mid in e['member_ids']}
    for row in in_hold:
        row.update(membership[row['message_id']])
        row['seconds_after_block_begin'] = (row['offered_db_ns_bounds'][0] - begin) / 1e9
    rates = base['confirmed_base']['rates']
    write('population-analysis.json', dict(base_reference=ref(BASE), selected_option=None,
        base_population=dict(organizations=2, conversations_per_org=3, total_conversations=6, rates=rates,
            per_org_cadence_seconds=[60/r for r in rates], window_seconds=360, provider='UNCHANGED_CONTAINED_PROVIDER'),
        R106=dict(required_backlog_by_org=[math.ceil(r*2) for r in rates],
            required_distinct_conversations_per_org=4, required_total=8, extra_per_org=1, relative_increase_percent=100/3,
            actual_execution='REJECTED_BEFORE_FIRST_BACKLOG_OFFER',
            A='Three conversations cannot host four distinct unclaimed continuous READY episodes at the same pre-start cut.',
            B='Explicit evaluation-population extension to four, separately labelled; no expansion of base coverage implied.',
            C='New base only if the expanded population itself must be confirmed; not authorized.',
            D='Not a generator fix: repeating an input cannot create a fourth coexisting conversation episode.'),
        R202=dict(accepted_inputs=len(offers), ready_episodes=len(report['episodes']), observed_hold_seconds=(end-begin)/1e9,
            affected_org_inputs_during_hold=in_hold, merged_episodes=[e for e in report['episodes'] if len(e['member_ids'])>1],
            input_ledger=ref(p/'schedule-offers.jsonl'), episode_ledger=ref(p/'job-result.json'),
            actual_population_by_org={str(org):sorted({e['conversation_id'] for e in report['episodes'] if e['organization_id']==org}) for org in (1,2)},
            A='Same population/rates can naturally coalesce during the fault, but does not satisfy the current 1-input:1-episode demand gate.',
            B='Prospective fault-demand classification separating accepted inputs, READY episodes and unchanged peer base; needs explicit approval.',
            C='Expanded confirmed population would need separately authorized characterization if required as base coverage.',
            D='A rotation-only fix cannot fit four unclaimed arrivals into three conversation episodes during the observed hold; the undeclared 1:1 generator/evaluator assumption needs a decision.'),
        old_runs_reclassified=False, runtime_coalescing_changed=False))

    job_path = PRIOR/'matrix-existing/matrix-existing-R103-unequal/sealed-job.json'
    job = read(job_path)
    write('R103-probe-preparation.json', dict(status='PREPARED_NOT_EXECUTED', execution_authorized=False,
        original_job=ref(job_path), base_reference=ref(BASE), immutable_load_fields={k:job[k] for k in
            ('organization_count','conversations_per_org','confirmed_base_rates','offered_rates_per_minute','comparison_global_rate','offer_seconds','followup_seconds')},
        calendar='EXISTING_COMMON_GLOBAL_CALENDAR_AND_PER_ORG_THREE_SLOT_ROTATION',
        additional_requirements=['FRESH_RUN_ID_AND_JOB_SEAL', 'ISOLATED_ARCHIVE', 'SCOPED_IDLE_GUARD',
            'RAW_JOURNAL_MONITOR', 'HOST_EVENT_RECORD_ID_CUTS', 'UNCHANGED_CLOCKMAP', 'ORIGINAL_AND_SUPPLEMENTAL_VERIFIERS', 'CLEANUP'],
        additional_sources=[ref(HERE/name) for name in ('clock_guard.py','host-event-cut.ps1','prepared_probe.py','evaluation_provider.py','worker_entry.py')],
        production_changes=False, base_changes=False))
    write('R204-fixture-preparation.json', dict(**base_plan(BASE), base_reference=ref(BASE),
        runtime_lease_seconds=900, runtime_turn_deadline_seconds=720,
        source=ref(ROOT/'backend/apps/agent/durable.py'),
        condition_new='ONE_CAPTURED_PRELUDE_CRASHED_WORK_THEN_BASE_WINDOW_OVERLAPPING_NATURAL_EXPIRY',
        ordinary_offer_window_unchanged=True, total_wall_time_longer_than_offer_window=True,
        full_adapter_integration='PENDING_PHASE_LAYOUT_REVIEW_AND_FUTURE_LAB_WIRING',
        accepted_finite_reclaim_reopened=False,
        required_new_evidence=['REAL_ACCEPTANCES_FROM_BOTH_ORGS_BEFORE_AND_AFTER_RECLAIM', 'INDEPENDENT_BASE_WINDOW_CUTS',
            'NATURAL_ORIGINAL_LEASE_EXPIRY', 'SAME_WORK_MEMBERSHIP_HISTORY_BUDGET', 'STALE_WITNESS_FENCING',
            'AT_MOST_TWO_LIVE_PLANNER_SLOTS', 'ALL_PRELUDE_AND_BASE_OBLIGATIONS_RECONCILED', 'DRAIN_AND_CLEANUP']))
    print('Prepared four read-only diagnosis/manifest artifacts; physical runs: 0.')


if __name__ == '__main__':
    main()
