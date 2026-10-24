"""Capture each native preparation/formal/cleanup invocation without retries."""
import json
from pathlib import Path
import subprocess
import sys
import time
from native_support import EVIDENCE, REPO, PYTHON, RTK, environment, save


def main():
    step = sys.argv[1]
    if step == 'setup':
        args = [sys.executable, '-B', EVIDENCE / 'prepare_native.py', step]
    elif step in ('frontend', 'stage'):
        args = [PYTHON, '-B', EVIDENCE / 'prepare_native.py', step]
    else:
        args = {'clock': [PYTHON, '-B', EVIDENCE / 'clock_probe.py'],
                'recover': [PYTHON, '-B', EVIDENCE / 'recover_preparation.py'],
                'retire-cache': [PYTHON, '-B', EVIDENCE / 'retire_install_cache.py'],
                'finalize': [PYTHON, '-B', EVIDENCE / 'finalize_preflight.py'],
                'validate': [PYTHON, '-B', EVIDENCE / 'launch_native.py', '--validate-only'],
                'formal': [PYTHON, '-B', EVIDENCE / 'launch_native.py'],
                'cleanup': [Path('C:/Users/LAP/AppData/Local/Temp/vet-b8b-locked/Scripts/python.exe'),
                            '-B', EVIDENCE / 'cleanup_native.py']}[step]
    path = EVIDENCE / ('invocation-' + step + '.json')
    assert not path.exists(), 'Refusing duplicate invocation: ' + step
    argv = [str(RTK), 'proxy', *map(str, args)]
    info = {'step': step, 'state': 'RUNNING', 'argv': argv,
            'utc_started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'wsl_invoked': False}
    save(path.name, info)
    started = time.monotonic()
    with (EVIDENCE / ('invocation-' + step + '.log')).open('wb') as stream:
        result = subprocess.run(argv, cwd=REPO, env=environment(), stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    info.update(state='COMPLETED', exit_code=result.returncode, seconds=time.monotonic() - started)
    save(path.name, info)
    print(json.dumps(info), flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
