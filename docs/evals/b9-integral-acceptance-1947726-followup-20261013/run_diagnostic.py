"""Run the frozen 11-test diagnostic once with original resource/clock guards."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from prepare_wsl import EVIDENCE, WORK, TREE, RTK, PYTHON, SHA, save, integrity, resources, environment


def verify(label):
    integrity(label)
    for name in ['dependency-files', 'diagnostic-seal']:
        files = json.loads((EVIDENCE/(name+'.json')).read_text())['files']
        bad = [p for p, h in files.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
        save(name+'-check-'+label+'.json', {'checked': len(files), 'mismatches': bad})
        assert not bad, (name, bad)


def last_row(path):
    with path.open('rb') as stream:
        stream.seek(0, 2); size = stream.tell(); stream.seek(max(0, size-8192))
        raw = stream.read()
    return json.loads(raw.rsplit(b'\n', 1)[0].splitlines()[-1])


def sample():
    host = last_row(EVIDENCE/'resource-observer/samples.jsonl')
    awake = last_row(EVIDENCE/'awake-request/heartbeat.jsonl')
    return {'guest': resources(), 'host': host, 'awake': awake,
            'host_age': abs(time.time()-host['utc_epoch_seconds']),
            'awake_age': abs(time.time()-awake['utc_epoch_seconds'])}


def invalid(row):
    if row['host_age'] > 10 or row['awake_age'] > 10:
        return 'Host observer or awake heartbeat unavailable/stale'
    if row['host']['physical_available'] < 2*1024**3 or row['guest']['physical_available'] < 2*1024**3:
        return 'Memory reserve exhausted'
    if row['guest']['disk_available'] < 1024**3:
        return 'Backing disk reserve exhausted'
    if row['awake']['api_previous_state'] != '0x80000001':
        return 'Awake request unavailable'
    return None


def main():
    assert not (EVIDENCE/'diagnostic.command.json').exists()
    assert json.loads((EVIDENCE/'prepared.json').read_text())['state'] == 'PASS'
    verify('before-test')
    before = sample()
    assert not invalid(before), invalid(before)
    env = environment()
    env['DATABASE_URL'] = 'postgresql://b9e@127.0.0.1:35480/test_b9i_diagnostic_control'
    env['PYTHONPATH'] = str(EVIDENCE) + ':' + str(TREE/'backend')
    argv = [str(RTK), 'proxy', str(PYTHON), '-B', str(EVIDENCE/'diagnostic_suite.py')]
    receipt = {'state': 'RUNNING', 'candidate_sha': SHA, 'test_invocations': 1,
               'argv': argv, 'resources_before': before, 'purpose': 'Diagnostic only; not integral acceptance'}
    save('diagnostic.command.json', receipt)
    start, wall = time.monotonic(), time.time()
    cause = None
    with (EVIDENCE/'diagnostic.command.log').open('xb') as log, (EVIDENCE/'diagnostic.monitor.jsonl').open('x', encoding='utf-8') as journal:
        p = subprocess.Popen(argv, cwd=TREE/'backend', env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while p.poll() is None:
            row = sample()
            row['elapsed_seconds'] = time.monotonic()-start
            row['wall_minus_monotonic_seconds'] = time.time()-wall-row['elapsed_seconds']
            journal.write(json.dumps(row)+'\n'); journal.flush()
            cause = invalid(row)
            if abs(row['wall_minus_monotonic_seconds']) > 1:
                cause = 'Clock discontinuity exceeds original 1-second guard'
            if row['elapsed_seconds'] > 1800:
                cause = 'Diagnostic maximum observation time of 1800 seconds exhausted'
            if cause:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.wait()
                save('diagnostic-STOP.json', {'state': 'PENDING_ENVIRONMENT', 'cause': cause, 'no_rerun': True})
                break
            time.sleep(1)
        code = p.wait()
    receipt.update(state='COMPLETED', exit_code=code, seconds=time.monotonic()-start,
                   invalidating_incident=cause, resources_after=sample())
    save('diagnostic.command.json', receipt)
    verify('after-test')
    print('DIAGNOSTIC_COMPLETED exit='+str(code)+' incident='+str(cause), flush=True)
    # A nonzero test result is expected diagnostic evidence, not controller failure.


if __name__ == '__main__':
    main()
