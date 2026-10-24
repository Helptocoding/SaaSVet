"""Read the owned Windows awake heartbeat without spawning Windows processes."""
import json
import time
from native_support import EVIDENCE, sha256

def status():
    try:
        directory = EVIDENCE / 'awake-request'
        if (directory / 'closure.json').exists() or (directory / 'stop.request').exists():
            raise RuntimeError('Owned awake request closed or release requested')
        control = json.loads((directory / 'control.json').read_text(encoding='utf-8'))
        if control['state'] != 'ACTIVE_API_CONFIRMED':
            raise RuntimeError('Awake request was not confirmed')
        if control['source_sha256'] != sha256((EVIDENCE / 'awake_guard.py').read_bytes()):
            raise RuntimeError('Awake source differs from acquired request')
        with (directory / 'heartbeat.jsonl').open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 8192))
            complete = stream.read().rsplit(b'\n', 1)[0].splitlines()
        if not complete:
            raise RuntimeError('No complete awake heartbeat')
        row = json.loads(complete[-1])
        age = abs(time.time() - row['utc_epoch_seconds'])
        if age > 10:
            raise RuntimeError('Awake heartbeat stale or clock mismatch')
        if row['pid'] != control['pid'] or row['thread_id'] != control['thread_id']:
            raise RuntimeError('Awake heartbeat ownership mismatch')
        if int(row['api_previous_state'], 16) & 0x80000001 != 0x80000001:
            raise RuntimeError('Awake heartbeat does not confirm both required flags')
        return {'state': 'ACTIVE_CONFIRMED', 'sample': row, 'sample_age_seconds': age}
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return {'state': 'UNAVAILABLE', 'reason': type(exc).__name__ + ': ' + str(exc)}
