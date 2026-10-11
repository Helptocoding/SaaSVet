"""Finalize this run from immutable journals; never invoke a runtime or PROFILE."""
import bisect
import csv
import hashlib
import json
import socket
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

import infra

OUT = infra.OUT
sys.path.insert(0, str(infra.ROOT / 'backend'))
from apps.agent.claim_diagnostic_report import read_journal


def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dt(value):
    return datetime.fromisoformat(value)


def delta_ns(later, earlier):
    delta = dt(later) - dt(earlier)
    return ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) * 1000


def relative_ns(point, origin, clock):
    if point is None:
        return None
    offset = delta_ns(clock['db_timestamp'], origin)
    return [offset + point - clock['end_ns'], offset + point - clock['start_ns']]


def scale(bounds, divisor):
    return [x / divisor for x in bounds] if bounds is not None else None


def stats(values):
    values = [x for x in values if x is not None]
    return dict(n=len(values), min=min(values), median=statistics.median(values), max=max(values)) if values else dict(n=0)


def bound_stats(values):
    values = [x for x in values if x is not None]
    return dict(n=len(values), lower=stats(x[0] for x in values), upper=stats(x[1] for x in values))


def csv_write(name, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / name).open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, separators=(',', ':')) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def main():
    draft = load('causal-analysis.json')
    assert draft['classification'] == 'DIAGNOSTIC_ONLY' and draft['head'] == infra.HEAD
    assert not draft['acceptance_run']
    before = load('protected-sources-before.json')
    assert before == load('protected-sources-after.json') == infra.snapshot()
    assert load('cleanup.json')['status'] == 'CLEANED' and not infra.DATA.exists()
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', infra.PORT)) != 0
    assert load('load.exit.json')['exit_code'] == 0
    assert all(x['exit_code'] == 0 and x['reader_stopped'] for x in load('process-exits.json'))
    functional = load('functional-results.results.json')
    assert load('functional.exit.json')['exit_code'] == 0 and functional['tests'] == 6
    assert all(functional[k] == 0 for k in ('failures', 'errors', 'skips', 'xfail'))
    for scenario in ('concurrency', 'lock-wait', 'blocked-llm', 'rollback'):
        receipt = load('functional-artifacts/' + scenario + '-equivalence.json')
        assert receipt['on_off_equal'] and receipt['off'] == receipt['on']

    query_map = {(q['session_id'], q['query_id']): q for q in draft.pop('all_sql_query_timings')}
    assert len(query_map) == draft['all_sql_query_count'] == 75600
    raw_queries = defaultdict(list)
    events_by_session = {}
    event_by_key = {}
    offset_ranges = {}
    provider_counts = Counter()
    retained_events = {'poll_start', 'poll_end', 'selection_start', 'selection_end', 'claim_start',
                       'claim_locked_start', 'claim_bound', 'claim_result', 'claim_end', 'claim_locked_end',
                       'commit_start', 'commit_end', 'rollback_start', 'rollback_end', 'db_clock',
                       'turn_start', 'turn_end', 'message_persisted', 'membership_candidate'}
    observed_raw_queries = 0
    for integrity in draft['journal_integrity']:
        path = OUT / integrity['path']
        assert sha(path) == integrity['sha256']
        rows = read_journal(path)
        assert len(rows) == integrity['events'] and rows[-1]['failed_writes'] == 0
        session = rows[0]['session_id']
        kept = [r for r in rows if r['event'] in retained_events]
        events_by_session[session] = kept
        event_by_key.update({(session, r['seq']): r for r in kept})
        offsets = [r['utc_ns'] - r['monotonic_ns'] for r in rows]
        offset_ranges[session] = dict(min_ns=min(offsets), max_ns=max(offsets), range_ms=(max(offsets)-min(offsets))/1e6)
        provider_counts.update(r['event'] for r in rows if r['event'].startswith('provider_'))
        for r in rows:
            if r['event'] != 'sql_end':
                continue
            q = query_map[(session, r['query_id'])]
            assert all(q[k] == v for k, v in r.items())
            raw_queries[session].append(q)
            observed_raw_queries += 1
        del rows
    assert observed_raw_queries == len(query_map)

    # Match readonly samples to actual SQL execution intervals, never across PIDs/connections.
    groups = defaultdict(list)
    for q in query_map.values():
        groups[(q['session_id'], q['connection_id'], q['backend_pid'])].append(q)
    indexes = {}
    for key, rows in groups.items():
        rows.sort(key=lambda q: q['execute_start_ns'])
        starts = [q['execute_start_ns'] for q in rows]
        ends = [q['execute_end_ns'] for q in rows]
        assert ends == sorted(ends)
        indexes[key] = rows, starts, ends
    wait_stats = defaultdict(lambda: dict(samples=0, lock_samples=0, blocking_pids=set(), wait_events=Counter()))
    observed_wait_counts, matching_counts = Counter(), Counter()
    observer = load('waits.summary.json')
    assert observer['complete'] and observer['partial_journal_lines'] == 0
    with (OUT / 'waits.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            sample = json.loads(line)
            assert sample['run_id'] == draft['run_id']
            event = (sample['wait_event_type'] or 'NONE') + ':' + (sample['wait_event'] or 'NONE')
            observed_wait_counts[event] += 1
            key = sample['session_id'], sample['connection_id'], sample['backend_pid']
            rows, starts, ends = indexes.get(key, ([], [], []))
            candidates = rows[bisect.bisect_left(ends, sample['sample_start_ns']):
                              bisect.bisect_right(starts, sample['sample_end_ns'])]
            matching_counts['matched' if len(candidates) == 1 else 'ambiguous' if candidates else 'unassigned'] += 1
            if len(candidates) != 1:
                continue
            q = candidates[0]
            observation = wait_stats[(q['session_id'], q['query_id'])]
            observation['samples'] += 1
            observation['wait_events'][event] += 1
            if sample['wait_event_type'] == 'Lock':
                observation['lock_samples'] += 1
                observation['blocking_pids'].update(sample['blocking_pids'])
    assert sum(matching_counts.values()) == observer['samples']
    for key, q in query_map.items():
        observation = wait_stats.get(key, dict(samples=0, lock_samples=0, blocking_pids=set(), wait_events={}))
        q['wait_observations'] = dict(**observation)
        q['wait_observations']['blocking_pids'] = sorted(observation['blocking_pids'])
        q['wait_observations']['wait_events'] = dict(observation['wait_events'])
        q['wait_observations']['exact_lock_wait_ms'] = None
        q['wait_observations']['lock_wait_ms_bounds'] = [0, q['duration_ns']/1e6] if observation['lock_samples'] else None
        q['duration_ms'] = q['duration_ns']/1e6

    corrections, summaries = [], []
    claims = draft['claims']
    for claim in claims:
        session, attempt_id = claim['session_id'], claim['attempt_id']
        events = events_by_session[session]
        clock = claim['clock_calibration']
        assert clock is not None and claim['status'] == 'committed'
        for name in ('claim_start', 'claim_bound', 'clock_calibration', 'claim_end', 'claim_result', 'commit'):
            item = claim[name]
            assert event_by_key[(session, item['seq'])] == item
        selection_id = claim['claim_bound'].get('selection_id')
        if selection_id is None:
            assert claim['selection_start'] is None and claim['selection_end'] is None
            corrections.append(dict(attempt_id=attempt_id, previous_draft_query_count=len(claim['selection_sql']),
                                    corrected_query_count=0, reason='NULL selection_id is absence of selector scope.'))
            claim['selection_sql'] = []
            claim['selection_duration_ns'] = claim['selection_duration_ms'] = None
            claim['selection_end_to_claim_start_ns'] = claim['selection_end_to_claim_start_ms'] = None
        else:
            assert claim['selection_start']['selection_id'] == selection_id
            actual = [q for q in raw_queries[session] if q.get('selection_id') == selection_id and q.get('span_id') == selection_id]
            assert [q['query_id'] for q in actual] == [q['query_id'] for q in claim['selection_sql']]
            claim['selection_sql'] = actual
            assert len(actual) == claim['selection_end']['query_count'] == 1
            assert all(q['operation'] == 'SELECT' for q in actual)
        actual_claim = [q for q in raw_queries[session] if q.get('attempt_id') == attempt_id]
        assert len(actual_claim) == claim['query_count']
        assert [q['query_id'] for q in actual_claim] == [q['query_id'] for q in claim['claim_sql']]
        claim['claim_sql'] = actual_claim
        claim['selection_query_count'] = len(claim['selection_sql'])
        for name in ('selection_sql', 'claim_sql'):
            queries = claim[name]
            claim[name + '_gaps_ms'] = [(b['execute_start_ns']-a['execute_end_ns'])/1e6 for a,b in zip(queries, queries[1:])]
        claim['selection_sql_ms'] = sum(q['duration_ms'] for q in claim['selection_sql'])
        claim['claim_sql_ms'] = sum(q['duration_ms'] for q in claim['claim_sql'])
        claimed_mono = [clock[k] + delta_ns(claim['claim_bound']['claimed_at'], clock['db_timestamp'])
                        for k in ('start_ns', 'end_ns')]
        claim['claimed_at_monotonic_ns_bounds'] = claimed_mono
        claim['clock_bracket_ms'] = (clock['end_ns']-clock['start_ns'])/1e6
        start_ns = claim['claim_start']['monotonic_ns']
        ack_ns = claim['commit']['execute_end_ns']
        claim['claim_start_to_claimed_at_ms_bounds'] = [(x-start_ns)/1e6 for x in claimed_mono]
        claim['claimed_at_to_commit_ack_ms_bounds'] = scale(relative_ns(ack_ns, claim['claim_bound']['claimed_at'], clock), 1e6)
        claim['selection_overhead_ms'] = claim['selection_duration_ms'] - claim['selection_sql_ms'] if selection_id else None
        claim['selection_start_to_first_sql_ms'] = (claim['selection_sql'][0]['execute_start_ns']-claim['selection_start']['monotonic_ns'])/1e6 if selection_id else None
        claim['last_selection_sql_to_selection_end_ms'] = (claim['selection_end']['monotonic_ns']-claim['selection_sql'][-1]['execute_end_ns'])/1e6 if selection_id else None
        claim['claim_start_to_first_sql_ms'] = (actual_claim[0]['execute_start_ns']-start_ns)/1e6
        claim['last_claim_sql_to_commit_start_ms'] = (claim['commit_start']['monotonic_ns']-actual_claim[-1]['execute_end_ns'])/1e6
        claim['sql_position_relative_to_claimed_at'] = [dict(query_id=q['query_id'],
            position='DEFINITELY_BEFORE' if q['execute_end_ns'] <= claimed_mono[0] else
                     'DEFINITELY_AFTER' if q['execute_start_ns'] >= claimed_mono[1] else 'OVERLAPS_DB_CLOCK_BRACKET')
            for q in actual_claim]
        for metric, member in zip(claim['message_timelines'], claim['membership']):
            assert metric['message_id'] == member['message_id']
            created = member['created_at']
            eligible = max(dt(created), dt(member['available_at']) if member['available_at'] else dt(created)).isoformat()
            metric['effective_inbound_eligible_at'] = eligible
            metric['persisted_to_eligible_seconds'] = delta_ns(eligible, created)/1e9
            metric['persisted_to_claimed_at_seconds'] = delta_ns(claim['claim_bound']['claimed_at'], created)/1e9
            metric['eligible_to_claimed_at_ms'] = delta_ns(claim['claim_bound']['claimed_at'], eligible)/1e6
            for name, point in (('eligible_to_poll_seconds_bounds', claim['poll_start']),
                                ('eligible_to_selection_seconds_bounds', claim['selection_start'])):
                metric[name] = scale(relative_ns(point['monotonic_ns'] if point else None, eligible, clock), 1e9)
            metric['persisted_to_commit_ack_ms_bounds'] = scale(relative_ns(ack_ns, created, clock), 1e6)
            metric['persisted_to_commit_ack_seconds_bounds'] = scale(relative_ns(ack_ns, created, clock), 1e9)
            metric['over_10_seconds'] = metric['persisted_to_claimed_at_seconds'] > 10
            occupancy = []
            if selection_id:
                eligible_mono = [clock[k]+delta_ns(eligible, clock['db_timestamp']) for k in ('start_ns','end_ns')]
                cutoff = claim['selection_start']['monotonic_ns']
                turns, previous_poll_end = {}, None
                for event in events:
                    name = event['event']
                    if name == 'turn_start':
                        turns[event['span_id']] = event
                    elif name == 'turn_end' and event['span_id'] in turns:
                        begin = turns[event['span_id']]
                        limits = [max(0, min(event['monotonic_ns'], cutoff)-max(begin['monotonic_ns'], limit))
                                  for limit in reversed(eligible_mono)]
                        if limits[1] > 0:
                            occupancy.append(dict(kind='processing_previous_turn', turn_work_id=begin['turn_work_id'],
                                span_id=begin['span_id'], start_ns=begin['monotonic_ns'], end_ns=event['monotonic_ns'],
                                duration_ms_bounds=scale(limits, 1e6)))
                    if name == 'poll_end':
                        previous_poll_end = event
                    elif name == 'poll_start' and previous_poll_end is not None:
                        limits = [max(0, min(event['monotonic_ns'], cutoff)-max(previous_poll_end['monotonic_ns'], limit))
                                  for limit in reversed(eligible_mono)]
                        if limits[1] > 0:
                            occupancy.append(dict(kind='between_polls_including_configured_1s_pause',
                                start_ns=previous_poll_end['monotonic_ns'], end_ns=event['monotonic_ns'],
                                duration_ms_bounds=scale(limits, 1e6)))
                        previous_poll_end = None
            metric['admitting_worker_preselection_occupancy'] = occupancy
            occupancy_totals = {}
            for kind in {x['kind'] for x in occupancy}:
                intervals = [x for x in occupancy if x['kind'] == kind]
                occupancy_totals[kind] = [sum(x['duration_ms_bounds'][i] for x in intervals) for i in (0,1)]
            preselect = scale(relative_ns(claim['selection_start']['monotonic_ns'] if selection_id else None, created, clock), 1e6)
            afterselect = [(x-claim['selection_start']['monotonic_ns'])/1e6 for x in claimed_mono] if selection_id else None
            if selection_id:
                # Anti-correlated clock bounds close the DB-to-DB total exactly; do not add independent extremes.
                total_ms = metric['persisted_to_claimed_at_seconds']*1000
                assert abs(preselect[0]+afterselect[1]-total_ms) < 1e-8
                assert abs(preselect[1]+afterselect[0]-total_ms) < 1e-8
            summaries.append(dict(attempt_id=attempt_id, session_id=session, worker=claim['worker'],
                backend_pid=claim['backend_pid'], turn_work_id=claim['turn_work_id'], attempts=claim['attempts'],
                message_id=member['message_id'], organization_id=claim['organization_id'],
                conversation_id=claim['conversation_id'], status=claim['status'], safety=metric['safety'],
                persisted_at=created, eligible_at=eligible, claimed_at=claim['claim_bound']['claimed_at'],
                persisted_to_claimed_at_s=metric['persisted_to_claimed_at_seconds'],
                persisted_to_eligible_s=metric['persisted_to_eligible_seconds'],
                eligible_to_poll_s_bounds=metric['eligible_to_poll_seconds_bounds'],
                eligible_to_selection_s_bounds=metric['eligible_to_selection_seconds_bounds'],
                persisted_to_selection_start_ms_bounds=preselect, selection_start_to_claimed_at_ms_bounds=afterselect,
                selection_ms=claim['selection_duration_ms'], selector_query_count=claim['selection_query_count'],
                selector_query_timings_ms=[q['duration_ms'] for q in claim['selection_sql']],
                selector_query_ids=[q['query_id'] for q in claim['selection_sql']], selector_sql_ms=claim['selection_sql_ms'],
                selector_inter_query_gaps_ms=claim['selection_sql_gaps_ms'],
                selection_start_to_first_sql_ms=claim['selection_start_to_first_sql_ms'],
                last_selection_sql_to_selection_end_ms=claim['last_selection_sql_to_selection_end_ms'],
                selection_end_to_claim_start_ms=claim['selection_end_to_claim_start_ms'],
                claim_start_to_claimed_at_ms_bounds=claim['claim_start_to_claimed_at_ms_bounds'],
                claim_ms=claim['claim_duration_ms'], claim_query_count=len(actual_claim),
                claim_query_ids=[q['query_id'] for q in actual_claim], claim_query_timings_ms=[q['duration_ms'] for q in actual_claim],
                claim_inter_query_gaps_ms=claim['claim_sql_gaps_ms'], claim_sql_ms=claim['claim_sql_ms'],
                commit_ms=claim['commit_duration_ms'], claim_result_to_commit_ack_ms_signed=claim['claim_result_to_commit_ack_ms_signed'],
                result_commit_order=claim['result_commit_order'], claimed_at_to_commit_ack_ms_bounds=claim['claimed_at_to_commit_ack_ms_bounds'],
                observable_lock_samples=sum(q['wait_observations']['lock_samples'] for q in actual_claim+claim['selection_sql']),
                worker_occupancy_ms_bounds=occupancy_totals, clock_bracket_ms=claim['clock_bracket_ms'],
                over_10_seconds=metric['over_10_seconds'],
                threshold_crossed_before_selection=bool(preselect and preselect[0] > 10000),
                excess_over_10_s=max(0, metric['persisted_to_claimed_at_seconds']-10)))

    # Misses also retain their selection and real transaction boundary, but have no claimed_at.
    for miss in draft['missed_attempts']:
        session = miss['session_id']
        events = [r for r in events_by_session[session] if r.get('attempt_id') == miss['attempt_id']]
        start = next(r for r in events if r['event'] == 'claim_start')
        selection_id = start['selection_id']
        selection_events = [r for r in events_by_session[session] if r.get('span_id') == selection_id]
        selection_start = next(r for r in selection_events if r['event'] == 'selection_start')
        selection_end = next(r for r in selection_events if r['event'] == 'selection_end')
        miss['selection_sql'] = [q for q in raw_queries[session] if q.get('span_id') == selection_id]
        miss['sql_timings'] = [q for q in raw_queries[session] if q.get('attempt_id') == miss['attempt_id']]
        miss['selector_query_count'] = len(miss['selection_sql'])
        miss['selection_ms'] = (selection_end['monotonic_ns']-selection_start['monotonic_ns'])/1e6
        miss['selection_end_to_claim_start_ms'] = (start['monotonic_ns']-selection_end['monotonic_ns'])/1e6
        commits = [r for r in events if r['event'] == 'commit_end']
        miss['commit'] = commits[-1] if commits else None
        miss['claim_result'] = next(r for r in events if r['event'] == 'claim_result' and r['boundary'] == 'claim')
        miss['claim_result_to_commit_ack_ms_signed'] = (commits[-1]['execute_end_ns']-miss['claim_result']['monotonic_ns'])/1e6 if commits else None
        assert miss['outcome'] == 'miss' and miss['selector_query_count'] == 1

    over = [row for row in summaries if row['over_10_seconds']]
    assert len(claims) == len(summaries) == 189 and len(over) == 122
    assert all(row['organization_id'] == 3 and row['threshold_crossed_before_selection'] for row in over)
    assert all(row['observable_lock_samples'] == 0 for row in summaries)
    assert len(corrections) == 22 and len(draft['missed_attempts']) == 20
    numeric = ('persisted_to_claimed_at_s', 'persisted_to_eligible_s', 'selection_ms', 'selector_sql_ms',
               'selection_start_to_first_sql_ms', 'last_selection_sql_to_selection_end_ms',
               'selection_end_to_claim_start_ms', 'claim_ms', 'claim_sql_ms', 'commit_ms',
               'claim_result_to_commit_ack_ms_signed', 'clock_bracket_ms')
    bounded = ('eligible_to_poll_s_bounds', 'eligible_to_selection_s_bounds', 'persisted_to_selection_start_ms_bounds',
               'selection_start_to_claimed_at_ms_bounds', 'claim_start_to_claimed_at_ms_bounds', 'claimed_at_to_commit_ack_ms_bounds')
    phases = {}
    for name, group in (('all_bound', summaries), ('ordinary', [r for r in summaries if not r['safety']]),
                        ('safety', [r for r in summaries if r['safety']]), ('over_10_seconds', over)):
        phases[name] = dict(rows=len(group), exact={k:stats(r[k] for r in group) for k in numeric},
                           bounded={k:bound_stats(r[k] for r in group) for k in bounded},
                           selector_query_counts=dict(Counter(r['selector_query_count'] for r in group)))
    lock_queries = []
    pid_roles = {row['backend_pid']:row['role'] for row in load('load-definition.json')['processes']}
    pid_roles[28340] = 'ingress'
    for q in query_map.values():
        if not q['wait_observations']['lock_samples']:
            continue
        lock_queries.append(dict(session_id=q['session_id'], query_id=q['query_id'], worker=q['worker'],
            tables=q['tables'], operation=q['operation'], for_update=q['for_update'], skip_locked=q['skip_locked'],
            duration_ms=q['duration_ms'], ingest_id=q.get('ingest_id'), turn_work_id=q.get('turn_work_id'),
            attempt_id=q.get('attempt_id'), span_id=q.get('span_id'), **q['wait_observations'],
            blocker_roles={str(pid):pid_roles.get(pid,'NOT_IDENTIFIED') for pid in q['wait_observations']['blocking_pids']}))
    waits = dict(classification='DIAGNOSTIC_ONLY', run_id=draft['run_id'], sample_count=observer['samples'],
        **matching_counts, observed_wait_events=dict(observed_wait_counts), observable_lock_queries=lock_queries,
        exact_lock_wait_ms=None, no_lock_samples_in_bound_claim_or_selection=True, raw_samples='waits.jsonl',
        limitation='20 ms requested sampling; no interpolation and no proof of absence. Ambiguous samples are unassigned.')

    state = load('durable-state.json')
    inputs = load('load-inputs.json')
    assert not inputs['errors']
    counts = []
    for org in (1,2,3):
        rows = [r for r in summaries if r['organization_id'] == org]
        pending = [m for m in draft['unclaimed_inbounds'] if m['organization_id'] == org]
        counts.append(dict(organization_id=org, ingested=inputs['sent'][org-1], claimed=len(rows),
            safety=sum(r['safety'] for r in rows), over_10_seconds=sum(r['over_10_seconds'] for r in rows),
            unclaimed=len(pending), persisted_to_claimed_at_s=stats(r['persisted_to_claimed_at_s'] for r in rows)))
    assert sum(r['claimed']+r['unclaimed'] for r in counts) == sum(inputs['sent']) == 396
    assert all(w['llm_calls_admitted'] <= 30 and w['llm_output_tokens_reserved'] <= 18000 for w in state['works'])

    draft.update(schema='e4-causal-report-v2', result_classification='CAUSE_CONFIRMED',
        causal_conclusion='In this new run all 122 claimed inbounds above 10 s cross 10 s before selection_start. '
            'The excess is localized to the eligible queue before the admitting poll/SELECT, after approximately '
            '7.95 s of the existing eligibility deadline. Selector SQL, claim SQL and commit do not account for '
            'the multi-second excess. This confirms the phase, not a historical cause or a uniquely identified tuning change.',
        confirmation_scope='NEW_RUN_PRESELECTION_PHASE_ONLY', historical_turnwork_86_causality='NOT_INFERRED',
        baseline=dict(branch='codex/e4-capacity-scheduling', authorized_runtime_baseline='66702168439b9841a2c988238638a42e6aaee43d',
            instrumented_head=infra.HEAD, instrumentation_commit=infra.HEAD,
            historical_fail_runtime='83ee3b24c84b170e22e401cb09a34da5320ae0a3', threshold_seconds=10,
            current_task_runtime_commits=0),
        source_protection=dict(protected_files=before['protected_files'],changed=0,before='protected-sources-before.json',
            after='protected-sources-after.json', before_sha256=sha(OUT/'protected-sources-before.json'),
            after_sha256=sha(OUT/'protected-sources-after.json')),
        offline_association_audit=dict(runtime_modified=False, journals_modified=False,
            issue='HEAD reconstructor equates missing selection_id and missing span_id with NULL; this includes unscoped ingress SQL for safety.',
            final_rule='Only non-null selection_id matching an actual selection_start/end span may associate selector SQL.',
            corrected_safety_attempts=corrections,
            superseded_drafts=['causal-analysis.json','attempt-summary.json','attempt-summary.csv','phase-summary.json'],
            exact_db_durations='datetime subtraction with integer microseconds; cross-clock intervals retain brackets; commit ACK is execute_end_ns.'),
        attempt_summaries=summaries, phase_summary=phases, over_10_seconds=over, organization_summary=counts,
        waits_summary=waits, load_definition=load('load-definition.json'), environment=load('environment.json'),
        clock_observation=dict(same_host=True, utc_minus_monotonic_ranges=offset_ranges,
            limitation='No clock-step proof from OS time service. DB/monotonic attribution uses existing query brackets and assumes no clock step.'),
        causal_checks=dict(over_10_count=122, crossed_threshold_before_selection=122, bound_memberships=189,
            unresolved_claim_outcomes=0, functional_discrepancies_observed=0, source_drift=0),
        query_timing_file='query-timings.jsonl', provider_event_counts=dict(provider_counts),
        minimal_correction=dict(runtime_change=None, reason='No correction is implemented or optimization proposed in this diagnostic execution. '
            'Localization to a queue phase alone does not identify a unique semantics-preserving correction.'),
        stop=dict(runtime_changes_after_confirmation=0, further_load_runs=0, acceptance_gate_evaluated=False),
        artifact_index=dict(report='causal-report.json', human_report='report.md', per_attempt='per-attempt.json',
            per_attempt_csv='per-attempt.csv', over_10='over-10-attempts.json', over_10_csv='over-10-attempts.csv',
            per_phase='per-phase.json', waits='waits-summary.json', all_queries='query-timings.jsonl',
            integrity='integrity.json', functional='functional-results.results.json', cleanup='cleanup.json'))
    draft['limits'] += ['Functional equivalence covers controlled identical-state scenarios; wall-clock scheduling under uncontrolled loads is not proven identical.',
        'Worker occupancy describes the admitting worker, not simultaneous global unavailability of both planners.',
        'Full claim SQL and commit occur partly after claimed_at; do not add them to persisted-to-claimed_at.',
        '207 unclaimed noisy inbounds are right-censored; their final latency is not fabricated.',
        'Log formatter timestamps are not used for causal intervals.',
        'Null safety selector association was corrected only in this evaluation adapter; HEAD reporter remains unchanged.']
    infra.write('per-attempt.json',dict(classification='DIAGNOSTIC_ONLY',run_id=draft['run_id'],bound_attempts=summaries,
        attempts_without_binding=draft['missed_attempts']))
    csv_write('per-attempt.csv', summaries)
    infra.write('over-10-attempts.json',dict(classification='DIAGNOSTIC_ONLY',run_id=draft['run_id'],attempts=over))
    csv_write('over-10-attempts.csv', over)
    infra.write('per-phase.json',dict(classification='DIAGNOSTIC_ONLY',run_id=draft['run_id'],phases=phases))
    infra.write('waits-summary.json',waits)
    with (OUT/'query-timings.jsonl').open('x',encoding='utf-8') as stream:
        for q in sorted(query_map.values(),key=lambda q:(q['session_id'],q['query_id'])):
            stream.write(json.dumps(q,separators=(',',':'))+'\n')
    draft['query_timing_sha256'] = sha(OUT/'query-timings.jsonl')
    infra.write('causal-report.json',draft)
    infra.write('closure-summary.json',dict(classification='DIAGNOSTIC_ONLY',result_classification='CAUSE_CONFIRMED',
        head=infra.HEAD,run_id=draft['run_id'],organizations=counts,phases=phases,waits=waits,
        representative_attempts=[r for r in summaries if r['turn_work_id'] in (4,100,149,189)],
        footer_events=sum(x['events'] for x in draft['journal_integrity']),
        all_query_count=len(query_map),corrected_safety_attempts=len(corrections)))
    print(json.dumps(dict(result_classification=draft['result_classification'], organizations=counts,
        footer_events=sum(x['events'] for x in draft['journal_integrity']),all_query_count=len(query_map),
        corrected_safety_attempts=len(corrections),phases_over_10=phases['over_10_seconds'],
        report_bytes=(OUT/'causal-report.json').stat().st_size),indent=2))


if __name__ == '__main__':
    main()
