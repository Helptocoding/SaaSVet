"""Separate readonly PG observer; sample bounds, never exact lock durations.

No query text, parameters, users, application names or lock keys are selected.
Call sample() on a dedicated autocommit psycopg connection, not the worker's.
The caller chooses the diagnostic sampling cadence; worker polling is untouched.
"""
import time


def sample(connection, targets, *, run_id):
    """targets: [{session_id, connection_id, backend_pid}] from worker journals."""
    if not connection.autocommit or not connection.read_only:
        raise ValueError('A dedicated readonly autocommit observer is required')
    start = time.perf_counter_ns()
    rows = connection.execute(
        'SELECT clock_timestamp(), pid, backend_start, state, wait_event_type, '
        'wait_event, pg_blocking_pids(pid), query_start, xact_start '
        'FROM pg_stat_activity WHERE datname=current_database() AND pid=ANY(%s)',
        ([target['backend_pid'] for target in targets],)).fetchall()
    end = time.perf_counter_ns()
    result = []
    for target in targets:
        row = next((r for r in rows if r[1] == target['backend_pid']), None)
        result.append(dict(schema='e4-wait-sample-v1', run_id=run_id, **target,
            sample_start_ns=start, sample_end_ns=end, observed=row is not None,
            db_timestamp=row[0].isoformat() if row else None,
            backend_start=row[2].isoformat() if row else None,
            state=row[3] if row else None, wait_event_type=row[4] if row else None,
            wait_event=row[5] if row else None, blocking_pids=row[6] if row else [],
            query_start=row[7].isoformat() if row and row[7] else None,
            xact_start=row[8].isoformat() if row and row[8] else None))
    return result


def main():
    import argparse
    import json
    from pathlib import Path
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop', type=Path, required=True)
    parser.add_argument('--interval', type=float, default=.02)
    parser.add_argument('journals', nargs='+', type=Path)
    args = parser.parse_args()
    if args.interval < .001:
        parser.error('Observer interval must be at least 1 ms')
    # Standard PG* environment identifies the separate diagnostic DB; never
    # serialize the DSN/password or read application message/query content.
    with psycopg.connect(autocommit=True) as observer, args.output.open('x', encoding='utf-8') as out:
        observer.read_only = True
        handles = {}
        partial = {}
        targets = {}
        count = 0
        try:
            while not args.stop.exists():
                for path in args.journals:
                    if path not in handles and path.exists():
                        handles[path] = path.open(encoding='utf-8')
                        partial[path] = ''
                    if path not in handles:
                        continue
                    data = partial[path] + handles[path].read()
                    lines = data.split('\n')
                    partial[path] = lines.pop()
                    for line in lines:
                        row = json.loads(line)
                        if row['run_id'] != args.run_id:
                            raise ValueError('Journal run_id mismatch')
                        if row['event'] == 'capture_end':
                            targets.pop(row['session_id'], None)
                        elif row.get('backend_pid') is not None:
                            targets[row['session_id']] = {key:row[key] for key in
                                ('session_id', 'connection_id', 'backend_pid')}
                if targets:
                    for row in sample(observer, list(targets.values()), run_id=args.run_id):
                        out.write(json.dumps(row)+'\n')
                        count += 1
                    out.flush()
                time.sleep(args.interval)
        finally:
            for handle in handles.values():
                handle.close()
        # A missing summary means an interrupted observer; never claim absence
        # of waits from an interrupted or empty sample series.
        with args.output.with_suffix('.summary.json').open('x', encoding='utf-8') as summary:
            json.dump(dict(run_id=args.run_id, samples=count, interval_seconds=args.interval,
                classification='DIAGNOSTIC_ONLY', complete=True,
                partial_journal_lines=sum(bool(value) for value in partial.values())), summary)


if __name__ == '__main__':
    main()
