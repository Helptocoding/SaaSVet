"""Read-only technical shape inventory of the preserved historical capture."""
from common import PRIOR, lines, read
import json

case = PRIOR / 'r1-06/authorized-r106-2x4-20261007-0002'
for name in ('job-result.json', 'full-durable-final.json'):
    v = read(case / name)
    print(name, list(v) if isinstance(v, dict) else type(v).__name__)
    if name == 'full-durable-final.json':
        for key, rows in v.items():
            if isinstance(rows, list):
                print(key, len(rows), list(rows[0]) if rows else [])
for name in ('offers.jsonl', 'population-slots.jsonl', 'snapshots.jsonl'):
    rows = lines(case / name)
    print(name, len(rows), list(rows[0]) if rows else [])
for path in sorted(case.rglob('*.jsonl')):
    if path.name in ('offers.jsonl', 'population-slots.jsonl', 'snapshots.jsonl', 'schedule-offers.jsonl'):
        continue
    rows = lines(path)
    events = {}
    for row in rows:
        if row.get('event') in ('message_persisted', 'deadline_set', 'claim_bound', 'dispatch', 'result'):
            events.setdefault(row['event'], row)
    print(str(path.relative_to(case)), len(rows), json.dumps(events))
print('first_episode', json.dumps(read(case/'job-result.json')['episodes'][0]))
print('first_offer', json.dumps(lines(case/'schedule-offers.jsonl')[0]))
print('first_slot', json.dumps(lines(case/'population-slots.jsonl')[0]))
