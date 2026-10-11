"""Read closed diagnostics offline. No Django setup, database, worker or runtime mutation.

The output contains interval observations, not counterfactual latency predictions.
All timestamps are integer nanoseconds on the original host's monotonic clock.
"""
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
HEAD = '825db75df68bf076929fa787e77beefe96803350'
RUNS = [ROOT / 'docs/evals' / n for n in (
    'e4-causal-diagnostic-2026-10-03-dded711c',
    'e4-causal-diagnostic-2026-10-04-f1239f89',
    'e4-causal-diagnostic-2026-10-04-f1922430')]
sys.path.insert(0, str(ROOT / 'backend'))
from apps.agent.claim_diagnostic_report import read_journal


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def delta_ns(a, b):
    d = datetime.fromisoformat(a) - datetime.fromisoformat(b)
    return ((d.days * 86400 + d.seconds) * 1000000 + d.microseconds) * 1000


def db_to_mono(value, clock):
    d = delta_ns(value, clock['db_timestamp'])
    return [clock['start_ns'] + d, clock['end_ns'] + d]


def stats(values):
    values = list(values)
    return {'n': len(values), 'min': min(values), 'median': statistics.median(values), 'max': max(values)} if values else {'n': 0}


def union_length(intervals, lo, hi):
    intervals = sorted((max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi)
    total = 0
    previous_end = lo
    for a, b in intervals:
        if b > max(a, previous_end):
            total += b - max(a, previous_end)
        previous_end = max(b, previous_end)
    return total


def contains(intervals, point):
    return any(a <= point < b for a, b in intervals)


def partition(lo, hi, definite, possible, workers, worker_gaps):
    boundaries = {lo, hi}
    for intervals in [definite, possible, *workers.values(), *worker_gaps.values()]:
        for a, b in intervals:
            if lo < a < hi:
                boundaries.add(a)
            if lo < b < hi:
                boundaries.add(b)
    points = sorted(boundaries)
    durations = Counter()
    for a, b in zip(points, points[1:]):
        # State is constant on the half-open interval, so its integer midpoint is sufficient.
        mid = (a + b) // 2
        if contains(definite, mid):
            state = 'organization_definitely_occupied'
        elif contains(possible, mid):
            state = 'organization_commit_visibility_uncertain'
        else:
            n = sum(contains(spans, mid) for spans in workers.values())
            state = {2: 'organization_free_both_planners_in_turn',
                     1: 'organization_free_one_planner_in_turn',
                     0: 'organization_free_neither_planner_in_turn'}[n]
            if n == 0:
                g = sum(contains(spans, mid) for spans in worker_gaps.values())
                state = ('organization_free_both_between_polls' if g == 2
                         else 'organization_free_neither_in_turn_at_least_one_polling_or_claiming')
        durations[state] += b - a
    assert sum(durations.values()) == hi - lo
    return {k: v / 1e9 for k, v in durations.items()}


def integrity():
    receipts = []
    for run in RUNS:
        m = load(run / 'manifest.sha256.json')
        mismatches = [name for name, item in m['files'].items()
                      if not (run / name).is_file() or sha(run / name) != item['sha256']
                      or (run / name).stat().st_size != item['bytes']]
        assert not mismatches, (str(run), mismatches)
        receipts.append({'run_directory': run.relative_to(ROOT).as_posix(),
                         'manifest_sha256': sha(run / 'manifest.sha256.json'),
                         'verified_files': len(m['files']), 'mismatches': mismatches,
                         'causal_report_sha256': sha(run / 'causal-report.json')})
    protected = load(RUNS[-1] / 'protected-sources-before.json')
    assert protected == load(RUNS[-1] / 'protected-sources-after.json')
    changed = [name for name, value in protected['hashes'].items()
               if not (ROOT / name).is_file() or sha(ROOT / name) != value['raw_sha256']]
    assert not changed, changed
    preexisting_changed = [name for name, expected in protected['preexisting_user_files'].items()
                           if (sha(ROOT/name) if (ROOT/name).is_file() else None) != expected]
    assert not preexisting_changed, preexisting_changed
    return {'head': HEAD, 'previous_runs': receipts,
            'protected_head_files': len(protected['hashes']), 'changed_protected_files': changed,
            'preexisting_user_files': protected['preexisting_user_files'],
            'changed_preexisting_user_files': preexisting_changed,
            'runtime_sha256': {name: protected['hashes'][name]['raw_sha256'] for name in (
                'backend/apps/agent/services.py', 'backend/apps/agent/worker.py',
                'backend/apps/agent/durable.py', 'backend/apps/agent/claim_diagnostics.py',
                'backend/apps/agent/claim_diagnostic_report.py',
                'backend/apps/agent/claim_diagnostic_waits.py')}}


def analyze(run):
    state = load(run / 'durable-state.json')
    attempts = load(run / 'per-attempt.json')
    claims = [a for a in attempts['bound_attempts'] if not a['safety']]
    works = {w['id']: w for w in state['works']}
    messages = {m['id']: m for m in state['messages']}
    conv_org = {m['conversation_id']: m['organization_id'] for m in messages.values()}
    journals = {}
    counts = {}
    for name in ('planner-1', 'planner-2', 'ingress', 'sender'):
        rows = read_journal(run / (name + '.jsonl'))
        assert rows[-1]['event'] == 'capture_end' and rows[-1]['failed_writes'] == 0
        assert not rows[-1]['open_transaction']
        counts[name] = {'events': len(rows), 'footer_complete': True, 'failed_writes': 0}
        journals[name] = rows
    provider_by_work = defaultdict(list)
    turns = {}
    worker_intervals = {}
    org_intervals = defaultdict(list)
    capacity_rows = []
    selections = []
    poll_gaps = {}
    worker_gaps = {}
    all_gaps = []
    all_claims = {a['turn_work_id']: a for a in attempts['bound_attempts']}
    for worker in ('planner-1', 'planner-2'):
        rows = journals[worker]
        by_span = defaultdict(list)
        sql_starts = {}
        ends = {}
        poll_starts, poll_ends = [], {}
        for e in rows:
            by_span[e.get('span_id')].append(e)
            if e['event'] == 'sql_start':
                sql_starts[e['query_id']] = e
            if e['event'] == 'sql_end':
                ends[e['query_id']] = e
            if e['event'] == 'poll_start':
                poll_starts.append(e)
            if e['event'] == 'poll_end':
                poll_ends[e['poll_id']] = e
            if e['event'] in ('provider_start', 'provider_end'):
                provider_by_work[e.get('turn_work_id')].append(e)
        # Older derived receipts omit raw event anchors. Recover them only from
        # the unchanged, footer-validated original journal, never from log lines.
        by_attempt = defaultdict(list)
        by_selection = {}
        for e in rows:
            if e.get('attempt_id'):
                by_attempt[e['attempt_id']].append(e)
            if e['event'] == 'selection_start':
                by_selection[e['selection_id']] = e
        for claim in claims:
            if claim['worker'] != worker:
                continue
            attempt_rows = by_attempt[claim['attempt_id']]
            clocks = [r for r in attempt_rows if r['event'] == 'db_clock'
                      and delta_ns(r['db_timestamp'], claim['claimed_at']) == 0]
            commits = [r for r in attempt_rows if r['event'] == 'commit_end']
            claim_starts = [r for r in attempt_rows if r['event'] == 'claim_start']
            assert len(clocks) == len(commits) == len(claim_starts) == 1
            assert commits[0]['error_class'] is None
            claim['db_clock'] = clocks[0]
            claim['commit_end'] = commits[0]
            claim['commit_ack_monotonic_ns'] = commits[0]['execute_end_ns']
            selection = by_selection[claim_starts[0]['selection_id']]
            claim['selection_start_monotonic_ns'] = selection['monotonic_ns']
        gaps = []
        for prior, following in zip(poll_starts, poll_starts[1:]):
            end = poll_ends[prior['poll_id']]
            assert end['monotonic_ns'] < following['monotonic_ns']
            gaps.append([end['monotonic_ns'], following['monotonic_ns']])
        all_gaps.extend(gaps)
        worker_gaps[worker] = gaps
        poll_gaps[worker] = stats((b-a)/1e9 for a, b in gaps)
        spans = []
        for e in rows:
            if e['event'] == 'selection_start':
                span = by_span[e['span_id']]
                result = [r for r in span if r['event'] == 'selection_result']
                finish = [r for r in span if r['event'] == 'selection_end']
                queries = [r for r in span if r['event'] == 'sql_end']
                assert len(result) == len(finish) == len(queries) == 1
                selections.append({'worker': worker, 'session_id': e['session_id'],
                    'selection_id': e['selection_id'], 'start_ns': e['monotonic_ns'],
                    'end_ns': finish[0]['monotonic_ns'], 'query_id': queries[0]['query_id'],
                    'sql_start_ns': queries[0]['execute_start_ns'], 'sql_end_ns': queries[0]['execute_end_ns'],
                    'conversation_ids': result[0]['conversation_ids'],
                    'candidate_organizations': [conv_org[conv]
                                                for conv in result[0]['conversation_ids']],
                    'claims_started': [{'conversation_id': r['conversation_id'],
                                        'organization_id': conv_org[r['conversation_id']],
                                        'attempt_id': r['attempt_id'], 'monotonic_ns': r['monotonic_ns']}
                                       for r in rows if r['event'] == 'claim_start'
                                       and r.get('selection_id') == e['selection_id']]})
            if e['event'] != 'turn_start':
                continue
            work = e['turn_work_id']
            span = by_span[e['span_id']]
            finished = [r for r in span if r['event'] == 'turn_end']
            assert len(finished) == 1 and finished[0]['outcome'] == 'returned'
            assert works[work]['status'] == 'COMPLETED' and works[work]['attempts'] == 1
            assert works[work]['ownership_epoch'] == e['epoch'] == 0
            # The last TurnWork UPDATE in this successful turn belongs to finalize_turn.
            updates = [r for r in span if r['event'] == 'sql_start' and r['operation'] == 'UPDATE'
                       and 'agent_turnwork' in r['tables']]
            final_update = updates[-1]
            tx = final_update['transaction_id']
            tx_rows = [r for r in span if r.get('transaction_id') == tx]
            commits = [r for r in tx_rows if r['event'] == 'commit_end']
            starts = [r for r in tx_rows if r['event'] == 'commit_start']
            assert len(commits) == len(starts) == 1 and commits[0]['error_class'] is None
            assert not any(r['event'].startswith('rollback') for r in tx_rows)
            assert any(r['event'] == 'sql_start' and r['operation'] == 'UPDATE'
                       and 'channels_message' in r['tables'] for r in tx_rows)
            begin_commit, ack_commit = commits[0]['execute_start_ns'], commits[0]['execute_end_ns']
            claim = all_claims[work]
            claim_begin, claim_ack = claim['commit_end']['execute_start_ns'], claim['commit_ack_monotonic_ns']
            assert claim_ack < e['monotonic_ns'] < begin_commit < ack_commit <= finished[0]['monotonic_ns']
            entry = {'turn_work_id': work, 'organization_id': e['organization_id'], 'worker': worker,
                     'conversation_id': e['conversation_id'], 'claim_commit_start_ns': claim_begin,
                     'claim_commit_ack_ns': claim_ack, 'release_commit_start_ns': begin_commit,
                     'release_commit_ack_ns': ack_commit, 'release_transaction_id': tx,
                     'release_turnwork_update_query_id': final_update['query_id'],
                     'release_turnwork_update_execute_interval_ns': [ends[final_update['query_id']]['execute_start_ns'],
                                                                    ends[final_update['query_id']]['execute_end_ns']],
                     'completed_at_db': works[work]['completed_at'],
                     'guaranteed_active_s': (begin_commit-claim_ack)/1e9,
                     'possible_active_s': (ack_commit-claim_begin)/1e9,
                     'turn_start_ns': e['monotonic_ns'], 'turn_end_ns': finished[0]['monotonic_ns'],
                     'turn_processing_s': (finished[0]['monotonic_ns']-e['monotonic_ns'])/1e9}
            capacity_rows.append(entry)
            org_intervals[e['organization_id']].append(entry)
            turns[work] = entry
            spans.append([e['monotonic_ns'], finished[0]['monotonic_ns']])
        worker_intervals[worker] = spans
    assert len(turns) == len(claims)
    overlap = []
    possible_overlap = []
    for org, entries in org_intervals.items():
        entries.sort(key=lambda x: x['claim_commit_start_ns'])
        for prior, following in zip(entries, entries[1:]):
            if prior['release_commit_start_ns'] > following['claim_commit_ack_ns']:
                overlap.append([org, prior['turn_work_id'], following['turn_work_id']])
            if prior['release_commit_ack_ns'] > following['claim_commit_start_ns']:
                possible_overlap.append([org, prior['turn_work_id'], following['turn_work_id']])
    assert not overlap, overlap

    provider_proof = []
    for work, turn in turns.items():
        rows = provider_by_work[work]
        calls = defaultdict(dict)
        for r in rows:
            if r['provider_kind'] == 'llm':
                calls[r['call']][r['event']] = r['monotonic_ns']
        assert sorted(calls) == [1, 2]
        intervals = [[calls[k]['provider_start'], calls[k]['provider_end']] for k in (1, 2)]
        assert intervals[0][1] < intervals[1][0]
        assert turn['claim_commit_ack_ns'] < intervals[0][0] < intervals[-1][1] < turn['release_commit_start_ns']
        provider_proof.append({'turn_work_id': work, 'organization_id': turn['organization_id'],
                              'llm_intervals_ns': intervals,
                              'total_serial_llm_s': sum(b-a for a,b in intervals)/1e9})

    observations = []
    for claim in claims:
        work, org = claim['turn_work_id'], claim['organization_id']
        eligible = db_to_mono(claim['eligible_at'], claim['db_clock'])
        end = claim['selection_start_monotonic_ns']
        assert eligible[1] < end
        assert abs((end-eligible[1])/1e9 - claim['eligible_to_selection_s_bounds'][0]) < 0.000001
        definite = [[r['claim_commit_ack_ns'], r['release_commit_start_ns']]
                    for r in org_intervals[org] if r['turn_work_id'] != work]
        possible = [[r['claim_commit_start_ns'], r['release_commit_ack_ns']]
                    for r in org_intervals[org] if r['turn_work_id'] != work]
        states = partition(eligible[1], end, definite, possible, worker_intervals, worker_gaps)
        observed = [s for s in selections if s['start_ns'] >= eligible[1] and s['end_ns'] <= end]
        predecessors = [r for r in org_intervals[org] if eligible[1] <= r['claim_commit_ack_ns'] < end]
        older_predecessors = [r for r in predecessors
            if delta_ns(works[r['turn_work_id']]['claimed_at'], claim['claimed_at']) < 0
            and min(datetime.fromisoformat(m['created_at']) for m in messages.values()
                    if m['turn_work_id'] == r['turn_work_id']) < datetime.fromisoformat(claim['persisted_at'])]
        per_worker = {}
        for worker, spans in worker_intervals.items():
            gaps = [(max(a, eligible[1]), min(b,end), b-a) for a,b in worker_gaps[worker]
                    if b > eligible[1] and a < end]
            assert all(total >= 1000000000 for a,b,total in gaps)
            per_worker[worker] = {'turn_processing_s': union_length(spans, eligible[1], end)/1e9,
                                 'outside_turn_s': (end-eligible[1]-union_length(spans, eligible[1], end))/1e9,
                                 'between_poll_gaps_s': sum(b-a for a,b,total in gaps)/1e9,
                                 'configured_1s_pause_overlap_s_bounds': [
                                     sum(max(0, b-a-(total-1000000000)) for a,b,total in gaps)/1e9,
                                     sum(min(b-a,1000000000) for a,b,total in gaps)/1e9],
                                 'complete_1s_pauses_within_window': sum(total == b-a for a,b,total in gaps)}
        observations.append({'run_id': state['run_id'], 'turn_work_id': work, 'organization_id': org,
                             'conversation_id': claim['conversation_id'], 'message_id': claim['message_id'],
                             'worker': claim['worker'], 'attempt_id': claim['attempt_id'],
                             'persisted_to_claimed_at_s': claim['persisted_to_claimed_at_s'],
                             'eligible_to_selection_s_bounds': claim['eligible_to_selection_s_bounds'],
                             'eligible_monotonic_ns_bounds': eligible,
                             'eligibility_boundary_uncertainty_s': (eligible[1]-eligible[0])/1e9,
                             'selection_start_ns': end,
                             'observation_window_s': (end-eligible[1])/1e9,
                             'disjoint_observed_states_s': states, 'worker_observations': per_worker,
                             'prior_other_turns_admitted_same_org': len(predecessors),
                             'older_messages_admitted_same_org': len(older_predecessors),
                             'selector_evaluations_during_wait': len(observed),
                             'empty_selector_evaluations_during_wait': sum(not s['conversation_ids'] for s in observed),
                             'target_conversation_in_candidates_during_wait': sum(claim['conversation_id'] in s['conversation_ids'] for s in observed),
                             'selection_ms': claim['selection_ms'], 'selector_sql_ms': claim['selector_sql_ms'],
                             'selection_to_claimed_at_ms_bounds': claim['selection_start_to_claimed_at_ms_bounds'],
                             'interpretation': 'Disjoint observed occupancy states; no attribution of all free time to polling or yield.'})

    noisy_intervals = org_intervals[3]
    provider_noisy = [p for p in provider_proof if p['organization_id'] == 3]
    wire_proofs = []
    for worker in ('planner-1', 'planner-2'):
        lines = (run/(worker+'.log')).read_text(encoding='utf-8').splitlines()
        result_lines = [l.split('CAUSAL_RESULT ',1)[1] for l in lines if l.startswith('CAUSAL_RESULT ')]
        assert len(result_lines) == 1
        result = json.loads(result_lines[0])
        handled = {w for w,t in turns.items() if t['worker'] == worker}
        assert {int(k) for k in result['calls_per_work']} == handled
        assert set(result['calls_per_work'].values()) == {2}
        assert result['wire']['domain_http'] == len(handled)
        assert result['wire']['llm'] == 2*len(handled)
        wire_proofs.append({'worker': worker, 'ordinary_works': len(handled), 'wire': result['wire'],
                            'log_sha256': sha(run/(worker+'.log')),
                            'scope': 'Counts only. Latencies derive from provider journal events; deterministic adapter makes one serial READ per turn.'})
    summary = {'run_id': state['run_id'], 'head': HEAD, 'classification': 'OFFLINE_PRECLAIM_ANALYSIS',
               'journal_integrity': counts, 'ordinary_claims_by_org': dict(Counter(a['organization_id'] for a in claims)),
               'ordinary_claims_by_org_and_worker': dict(Counter(str((a['organization_id'], a['worker'])) for a in claims)),
               'offered_inbounds_by_org': dict(Counter(m['organization_id'] for m in messages.values())),
               'pending_inbounds_by_org': dict(Counter(m['organization_id'] for m in messages.values() if m['status'] == 'pending')),
               'selector_evaluations': len(selections), 'empty_selector_evaluations': sum(not s['conversation_ids'] for s in selections),
               'poll_gaps_s': poll_gaps, 'definite_same_org_capacity_overlaps': overlap,
               'possible_same_org_capacity_overlaps': possible_overlap,
               'noisy_guaranteed_capacity_hold_s': stats(r['guaranteed_active_s'] for r in noisy_intervals),
               'noisy_possible_capacity_hold_s': stats(r['possible_active_s'] for r in noisy_intervals),
               'noisy_two_serial_llm_s': stats(p['total_serial_llm_s'] for p in provider_noisy),
               'all_ordinary_turns_two_serial_llm_calls': len(provider_proof),
               'optimistic_rate_if_every_turn_matched_shortest_observed_hold_per_s':
                    1 / min(r['guaranteed_active_s'] for r in noisy_intervals),
               'capacity_only_provider_bound_per_s': 1.0,
               'controlled_provider_plus_read_service_lower_bound_s': 1.1,
               'controlled_provider_plus_read_rate_upper_bound_per_s': 1/1.1,
               'provider_bound_explanation': 'Two serial controlled sleeps of 0.5 s and one serial READ sleep of 0.1 s hold N=1. Local work adds time. Static adapter plus journal and count proof; no invented READ timestamps and no production benchmark.',
               'wire_count_proof': wire_proofs,
               'high_latency_attempts': sum(o['persisted_to_claimed_at_s'] > 10 for o in observations)}
    return summary, observations, capacity_rows, selections, provider_proof


def main():
    verified = integrity()
    summaries, observations, capacity, selections, provider = [], [], [], [], []
    # Reconstruct every closed run; no new synthetic execution is necessary.
    for run in RUNS:
        summary, obs, cap, sels, prov = analyze(run)
        summaries.append(summary)
        observations.extend(obs)
        capacity.extend(dict(run_id=summary['run_id'], **r) for r in cap)
        selections.extend(dict(run_id=summary['run_id'], **r) for r in sels)
        provider.extend(dict(run_id=summary['run_id'], **r) for r in prov)
    save('input-integrity.json', verified)
    save('scheduling-evidence.json', {'schema': 'e4-preclaim-scheduling-analysis-v1',
                                   'classification': 'OFFLINE_PRECLAIM_ANALYSIS', 'head': HEAD,
                                   'method': {'time_resolution': 'integer nanoseconds; DB eligibility translated through existing DB clock execution brackets',
                                              'occupancy_window': 'latest possible eligibility to original selection_start',
                                              'definite_occupied': 'claim commit_ack to completion commit_start',
                                              'possible_occupied': 'claim commit_start to completion commit_ack',
                                              'commit_uncertainty': 'actual server commit visibility point lies inside driver execution; ACK is not that point',
                                              'worker_state': 'turn_start/end spans; outside a turn includes polling, SQL, sleeping and process overhead',
                                              'limits': ['Original host monotonic clocks are comparable across processes.',
                                                         'DB mapping inherits original no-clock-step assumption and measured sub-millisecond brackets.',
                                                         'No exact per-organization SQL predicate evaluation reason or snapshot is recorded.',
                                                         'No sum across overlapping worker clocks or percentile cohorts.',
                                                         'Safety inline work is excluded from ordinary slot intervals; it updates organization recency in the selector.']},
                                   'run_summaries': summaries, 'per_attempt': observations})
    save('capacity-intervals.json', capacity)
    save('selector-observations.json', selections)
    save('provider-proof.json', provider)
    flattened = []
    for r in observations:
        flattened.append({k: v for k, v in r.items() if k not in ('disjoint_observed_states_s', 'worker_observations')}
                         | r['disjoint_observed_states_s'])
    keys = list(dict.fromkeys(k for r in flattened for k in r))
    with (OUT / 'per-attempt-scheduling.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in flattened:
            writer.writerow({k: json.dumps(v) if isinstance(v, (list,dict)) else v for k,v in row.items()})
    save('output-summary.json', {'run_summaries': summaries, 'key_attempts': [o for o in observations
         if (o['run_id'].endswith('f1922430c60348e8adce24196c02bf5a') and o['turn_work_id'] in (4,125,195))
         or (o['run_id'].endswith('f1239f896754491c8998d56e43356aa1') and o['turn_work_id'] == 165)]})
    print(json.dumps(load(OUT/'output-summary.json'), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
