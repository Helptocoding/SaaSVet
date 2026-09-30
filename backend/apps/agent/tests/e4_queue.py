"""Derive global queue snapshots from closed diagnostic journals, without a database."""
import argparse
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('Refusing to overwrite queue collection')
    series = []
    for path in (args.repository/'docs/evals').glob('e4-diagnostic-baseline-planner-*.timing.json'):
        journal = json.loads(path.read_text())
        for event in journal['events']:
            if event['event'] != 'poll' or 'queue' not in event:
                continue
            series.append(dict(time=event['time'], role=journal['role'], **{
                key: sum(row[key] for row in event['queue'].values())
                for key in ('pending', 'eligible', 'blocked', 'claimable')}))
    if not series:
        raise RuntimeError('No closed diagnostic poll snapshots')
    series.sort(key=lambda row: row['time'])
    stats = {}
    for key in ('pending', 'eligible', 'blocked', 'claimable'):
        values = sorted(row[key] for row in series)
        stats[key] = dict(n=len(values), p50=values[math.ceil(.5*(len(values)-1))],
            p95=values[math.ceil(.95*(len(values)-1))], max=values[-1])
    result = dict(schema='e4-global-queue-v1', classification='DIAGNOSTIC_ONLY',
        source='e4-diagnostic-baseline-planner-*.timing.json',
        definition='Sum organizations within each original poll snapshot; not sum of maxima',
        statistics=stats, series=series)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
