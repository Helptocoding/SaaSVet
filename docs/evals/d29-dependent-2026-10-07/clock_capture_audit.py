"""Inspect preserved clock calibrations without altering their interpretation."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def timestamp(value):
    delta = datetime.fromisoformat(value).astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def inspect(directory):
    directory = directory.resolve()
    roles = {}
    for role in ('ingress', 'planner_1', 'planner_2', 'sender'):
        path = directory / (role + '.jsonl')
        if not path.exists():
            roles[role] = dict(observed=False)
            continue
        rows = []
        for line, text in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            row = json.loads(text)
            if row['event'] == 'db_clock':
                db = timestamp(row['db_timestamp'])
                rows.append(dict(line=line, lo=db-row['end_ns'], hi=db-row['start_ns'],
                                 monotonic_start_ns=row['start_ns'], db_timestamp=row['db_timestamp']))
        value = dict(observed=True, calibrations=len(rows), journal=str(path.relative_to(HERE)),
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if rows:
            lo, hi = max(rows, key=lambda r:r['lo']), min(rows, key=lambda r:r['hi'])
            value.update(common_offset_bounds_ns=[lo['lo'], hi['hi']],
                         valid_constant_offset=lo['lo'] <= hi['hi'],
                         contradiction_ns=max(0, lo['lo']-hi['hi']),
                         limiting_lower_sample=lo, limiting_upper_sample=hi)
        roles[role] = value
    offers = directory / 'schedule-offers.jsonl'
    ledger = [json.loads(s) for s in offers.read_text(encoding='utf-8').splitlines()] if offers.exists() else []
    return dict(run_id=directory.name, roles=roles, actual_offers=len(ledger),
                accepted_durable_inputs=sum(r['outcome']=='ACCEPTED_DURABLE' for r in ledger),
                interpretation='CONSTANT_OFFSET_ASSUMPTION_TEST_ONLY; NO_REPAIR_OR_CLOCK_STEP_CAUSE_INFERRED')


def main():
    attempts = [inspect(p.parent) for p in sorted(HERE.glob('*/*/dependent-executor-receipt.json'))]
    with (HERE/'clock-capture-audit.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(scope='READ_ONLY_RAW_CAPTURE_AUDIT', attempts=attempts,
                       calibration_modified=False, synthetic_evidence=[]), stream, indent=2)
        stream.write('\n')
    return attempts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.directory) if args.directory else main(), indent=2))
