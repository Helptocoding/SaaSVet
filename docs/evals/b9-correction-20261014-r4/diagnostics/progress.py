"""Read-only preparation/execution snapshot; never alters campaign receipts."""
from pathlib import Path
import collections
import json
import shutil
import time

p = Path(__file__).resolve().parents[1]
blocks = p / 'blocks'
full_labels = ['full-' + family for family in ('b8b', 'b8c', 'b8d', 'b8e', 'general')]


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def journal_rows(path):
    if not path.exists():
        return []
    # Writers append newline-terminated records; ignore a row still being written.
    raw = path.read_bytes()
    lines = raw.rsplit(b'\n', 1)[0].splitlines() if b'\n' in raw else []
    return [json.loads(line) for line in lines if line.strip()]


def last_row(path):
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 8192))
            raw = stream.read()
    except FileNotFoundError:
        return None
    if b'\n' not in raw:
        return None
    for line in reversed(raw.rsplit(b'\n', 1)[0].splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


commands = {}
for path in sorted(blocks.glob('*.command.json')):
    row = read_json(path)
    if row is not None:
        commands[row['label']] = row['state']
active = [label for label, state in commands.items() if state == 'RUNNING']
gates = {}
for path in sorted(blocks.glob('*.gate.json')):
    row = read_json(path)
    if row is not None:
        gates[path.name.split('.')[0]] = row['state']

counts, last_completed, full_ids = {}, {}, set()
for label in ['directed', 'b0', 'b3', 'b4', 'b5', *full_labels]:
    path = blocks / (label + '.ids.jsonl')
    if path.exists():
        rows = journal_rows(path)
        counts[label] = dict(collections.Counter(row['outcome'] for row in rows))
        if rows:
            last_completed[label] = rows[-1]['id']
        if label in full_labels:
            full_ids.update(row['id'] for row in rows)
directed = journal_rows(blocks / 'directed.results.passed.jsonl')
if directed:
    counts['directed'] = {'PASS': len(directed)}
    last_completed['directed'] = directed[-1]['test_id']

host = last_row(p / 'resource-observer/samples.jsonl')
awake = last_row(p / 'awake-request/heartbeat.jsonl')
formal = read_json(p / 'invocation-formal.json')
preflight = read_json(p / 'preflight.json')
seal = read_json(p / 'evaluation-seal.json')
stop = read_json(p / 'STOP.json')
print(json.dumps({
    'phase': 'PREPARING' if formal is None else 'FORMAL',
    'formal': formal['state'] if formal else 'NOT_STARTED',
    'preflight': preflight['state'] if preflight else None,
    'seal_files': len(seal['files']) if seal else None,
    'active': active,
    'counts': counts,
    'full_observed_unique': len(full_ids),
    'last_completed_in_active_block': {label: last_completed.get(label) for label in active},
    'gates': gates,
    'host_free_GiB': round(host['physical_available'] / 1024**3, 2) if host else None,
    'C_free_GiB': round(shutil.disk_usage('C:/').free / 1024**3, 2),
    'awake_age': round(time.time() - awake['utc_epoch_seconds'], 2) if awake else None,
    'STOP': stop,
}))
