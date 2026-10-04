"""Offline diagnostic reconstruction. Never computes an acceptance gate."""
import argparse
import json
from datetime import datetime
from pathlib import Path


def read_journal(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
    if not rows or rows[0]['event'] != 'capture_start' or rows[-1]['event'] != 'capture_end':
        raise ValueError('INCOMPLETE: missing capture boundary')
    footer = rows[-1]
    if footer['failed_writes'] or footer['open_transaction']:
        raise ValueError('INCOMPLETE: sink failure or open transaction')
    queries, spans, transactions = set(), set(), set()
    starts = 0
    previous = -1
    for index, row in enumerate(rows, 1):
        if (row['seq'] != index or row['monotonic_ns'] < previous or
                row['session_id'] != rows[0]['session_id'] or row['run_id'] != rows[0]['run_id']):
            raise ValueError('INCOMPLETE: sequence, clock or correlation mismatch')
        previous = row['monotonic_ns']
        event = row['event']
        if event == 'sql_start':
            starts += 1
            if row['query_id'] != starts or row['query_id'] in queries:
                raise ValueError('Duplicate query start')
            queries.add(row['query_id'])
        elif event == 'sql_end':
            if row['query_id'] not in queries:
                raise ValueError('Unpaired SQL end')
            queries.remove(row['query_id'])
            if row['execute_end_ns'] < row['execute_start_ns']:
                raise ValueError('Reversed SQL interval')
        elif event in ('poll_start', 'selection_start', 'claim_start', 'claim_locked_start',
                       'turn_start', 'ingest_start'):
            spans.add(row['span_id'])
        elif event in ('poll_end', 'selection_end', 'claim_end', 'claim_locked_end',
                       'turn_end', 'ingest_end'):
            if row['span_id'] not in spans:
                raise ValueError('Unpaired span end')
            spans.remove(row['span_id'])
        elif event == 'transaction_begin':
            transactions.add(row['transaction_id'])
        elif event in ('commit_end', 'rollback_end') and not row['error_class']:
            transactions.discard(row['transaction_id'])
    if queries or spans or transactions or starts != footer['query_count']:
        raise ValueError('INCOMPLETE: unclosed phase or query count mismatch')
    return rows


def _timestamp(value):
    return datetime.fromisoformat(value).timestamp()


def _savepoint_rolled_back(transaction, bound):
    for index, row in enumerate(transaction):
        if row['event'] != 'savepoint_rollback' or row['savepoint_id'] not in bound['savepoint_ids']:
            continue
        following = transaction[index+1:]
        acknowledgement = next((r for r in following if r['event'] == 'savepoint_rollback_end'
                                and r['savepoint_id'] == row['savepoint_id']), None)
        if acknowledgement is not None:
            if not acknowledgement['error_class']:
                return True
            continue
        # Older development journals have the attempt marker plus the paired
        # SQL acknowledgement. The marker alone never establishes rollback.
        start = next((r for r in following if r['event'] == 'sql_start'), None)
        if start is None or start['operation'] != 'ROLLBACK':
            continue
        end = next((r for r in following if r['event'] == 'sql_end'
                    and r['query_id'] == start['query_id']), None)
        if end is not None and not end['error_class']:
            return True
    return False


def reconstruct(journals):
    rows = [row for journal in journals for row in journal]
    if len({row['run_id'] for row in rows}) != 1:
        raise ValueError('Never merge different diagnostic runs')
    if len({journal[0]['session_id'] for journal in journals}) != len(journals):
        raise ValueError('Duplicate diagnostic session')
    reports = []
    for bound in sorted((row for row in rows if row['event'] == 'claim_bound'),
                        key=lambda row: (row['turn_work_id'], row['attempts'], row['seq'])):
        local = [r for r in rows if r['session_id'] == bound['session_id']]
        attempt = [r for r in local if r.get('attempt_id') == bound['attempt_id']]
        transaction = [r for r in local if r['transaction_id'] == bound['transaction_id']]
        rolled_back = any(r['event'] == 'rollback_end' and not r['error_class'] for r in transaction)
        rolled_back |= _savepoint_rolled_back(transaction, bound)
        commit = next((r for r in transaction if r['event'] == 'commit_end' and not r['error_class']), None)
        status = 'rolled_back' if rolled_back else 'committed' if commit else 'unconfirmed'
        selection = [r for r in local if r.get('selection_id') == bound.get('selection_id')
                     and r['event'] in ('selection_start', 'selection_end', 'sql_start', 'sql_end')]
        # Pre-selection SQL is shared by all attempted candidates in that poll.
        selection = [r for r in selection if r.get('span_id') == bound.get('selection_id')]
        members = [r for r in attempt if r['event'] == 'membership_candidate']
        if not members:
            # Reclaim reuses fixed membership. Only reuse a committed, earlier
            # journal observation, never fabricate pre-existing DB history.
            previous = [p for p in reports if p['turn_work_id'] == bound['turn_work_id']
                        and p['status'] == 'committed']
            members = previous[-1]['membership'] if previous else []
        clock = next((r for r in attempt if r['event'] == 'db_clock'), None)
        existing = next((r for r in attempt if r['event'] == 'existing_work'), None)
        start = next(r for r in attempt if r['event'] in ('claim_start', 'claim_locked_start'))
        selected = next((r for r in selection if r['event'] == 'selection_start'), None)
        selected_end = next((r for r in selection if r['event'] == 'selection_end'), None)
        poll = next((r for r in local if r['event'] == 'poll_start' and
                     r.get('poll_id') == bound.get('poll_id')), None)

        def db_bounds(event):
            if event is None or clock is None:
                return None
            delta = event['monotonic_ns']
            db = _timestamp(clock['db_timestamp'])
            return [db + (delta-clock['end_ns'])/1e9, db + (delta-clock['start_ns'])/1e9]

        metrics = []
        for member in members:
            persisted = _timestamp(member['created_at'])
            eligible = max(persisted, _timestamp(member['available_at']) if member['available_at'] else persisted)
            def relative(event, origin):
                limits = db_bounds(event)
                return [x-origin for x in limits] if limits else None
            metrics.append(dict(message_id=member['message_id'],
                persisted_at=member['created_at'],
                effective_inbound_eligible_at=datetime.fromtimestamp(eligible,
                    tz=datetime.fromisoformat(member['created_at']).tzinfo).isoformat(),
                persisted_to_eligible_seconds=eligible-persisted,
                eligible_to_poll_seconds_bounds=relative(poll, eligible),
                eligible_to_selection_seconds_bounds=relative(selected, eligible),
                persisted_to_claimed_at_seconds=_timestamp(bound['claimed_at'])-persisted,
                persisted_to_commit_ack_seconds_bounds=relative(commit, persisted)))
        persisted_events = [r for r in rows if r['event'] == 'message_persisted' and
                            r['message_id'] in {m['message_id'] for m in members}]
        ingress = []
        for persisted_event in persisted_events:
            ingress_transaction = [r for r in rows if
                r['session_id'] == persisted_event['session_id'] and
                r['transaction_id'] == persisted_event['transaction_id']]
            ingress.append(dict(persisted_event=persisted_event,
                transaction_events=[r for r in ingress_transaction if r['event'] in
                    ('transaction_begin', 'commit_start', 'commit_end', 'rollback_start',
                     'rollback_end', 'savepoint_rollback')]))
        reports.append(dict(session_id=bound['session_id'], attempt_id=bound['attempt_id'],
            turn_work_id=bound['turn_work_id'], organization_id=bound['organization_id'],
            conversation_id=bound['conversation_id'], epoch=bound['epoch'],
            lease_fingerprint=bound['lease_fingerprint'], worker=bound['worker'],
            backend_pid=bound['backend_pid'], connection_id=bound['connection_id'],
            transaction_id=bound['transaction_id'], status=status, attempts=bound['attempts'],
            claim_eligibility=(dict(source='lease_expiry' if existing['status'] == 'PROCESSING'
                else 'retry_deadline', db_timestamp=existing['lease_expires_at'] if
                existing['status'] == 'PROCESSING' else existing['next_attempt_at'])
                if existing else dict(source='inbound_deadline', db_timestamp=None)),
            ingress=ingress, ingress_source='journal' if ingress else 'NOT_OBSERVED',
            membership=members, membership_source='journal' if members else 'NOT_OBSERVED',
            message_timelines=metrics,
            selection_duration_ns=(selected_end['monotonic_ns']-selected['monotonic_ns'])
                if selected and selected_end else None,
            selection_end_to_claim_start_ns=start['monotonic_ns']-selected_end['monotonic_ns']
                if selected_end else None,
            selection_sql=[r for r in selection if r['event'] == 'sql_end'],
            claim_sql=[r for r in attempt if r['event'] == 'sql_end'],
            query_count=sum(r['event'] == 'sql_start' for r in attempt),
            claim_start=start, claim_bound=bound, poll_start=poll,
            selection_start=selected, selection_end=selected_end,
            commit=commit, clock_calibration=clock))
    return dict(schema='e4-causal-report-v1', classification='DIAGNOSTIC_ONLY',
                acceptance_run=False, historical_turnwork_86_causality='NOT_INFERRED',
                run_id=rows[0]['run_id'], claims=reports,
                attempts_without_binding=[r for r in rows if r['event'] == 'claim_result'
                                          and r['result'] == 'miss'],
                warnings=['DB-to-monotonic bounds assume no clock step during the attempt.',
                          'created_at is the persisted field, not ingress commit time.',
                          'SQL duration includes server/network; it is not pure lock wait.',
                          'A new run is never evidence of historical TurnWork 86.'])


def attach_waits(report, samples):
    """Same-host perf_counter samples only. No interpolation across samples.

    Matching is by run/session/connection/PID plus the in-flight SQL interval.
    A sample straddling multiple queries is ambiguous, never attributed twice.
    A span between two observed waits does not prove continuous waiting.
    """
    if any(s['run_id'] != report['run_id'] for s in samples):
        raise ValueError('Wait samples belong to another diagnostic run')
    matched, ambiguous, unassigned = [], [], []
    for sample in samples:
        candidates = {}
        for claim in report['claims']:
            if not all(sample[key] == claim[key] for key in ('session_id','connection_id','backend_pid')):
                continue
            for query in claim['selection_sql'] + claim['claim_sql']:
                if (query['execute_start_ns'] <= sample['sample_end_ns'] and
                        query['execute_end_ns'] >= sample['sample_start_ns']):
                    candidates[(query['session_id'], query['query_id'])] = query
        item = dict(sample)
        if len(candidates) == 1:
            query = next(iter(candidates.values()))
            item['query_id'] = query['query_id']
            matched.append(item)
        elif candidates:
            ambiguous.append(item)
        else:
            unassigned.append(item)
    lock_queries = {}
    for item in matched:
        if item['wait_event_type'] != 'Lock':
            continue
        key = (item['session_id'], item['query_id'])
        query = next(q for claim in report['claims'] for q in claim['selection_sql']+claim['claim_sql']
                     if (q['session_id'], q['query_id']) == key)
        group = lock_queries.setdefault(key, dict(session_id=key[0], query_id=key[1],
            sample_count=0, first_observation_ns=item['sample_start_ns'],
            last_observation_ns=item['sample_end_ns'],
            lock_wait_total_ns_bounds=[0, query['duration_ns']], blocking_pids=[]))
        group['sample_count'] += 1
        group['first_observation_ns'] = min(group['first_observation_ns'], item['sample_start_ns'])
        group['last_observation_ns'] = max(group['last_observation_ns'], item['sample_end_ns'])
        group['blocking_pids'] = sorted(set(group['blocking_pids']) | set(item['blocking_pids']))
    report['waits'] = dict(matched=matched, ambiguous=ambiguous, unassigned=unassigned,
        lock_queries=list(lock_queries.values()),
        exact_lock_wait_seconds=None,
        limitation='Discrete same-host observations; absent samples do not prove absence of waits.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journals', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--same-host-waits', type=Path,
                        help='JSONL samples collected on the same host as the workers')
    args = parser.parse_args()
    result = reconstruct([read_journal(path) for path in args.journals])
    if args.same_host_waits:
        attach_waits(result, [json.loads(line) for line in args.same_host_waits.read_text().splitlines()])
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
