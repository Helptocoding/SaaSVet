"""Capture each preparation/test/cleanup invocation without duplicate execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LINUX = '/mnt/c/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/' + HERE.name
WORK = '/home/lap/b9i-correction-20261013'


def main():
    step = sys.argv[1]
    commands = {
        'setup': ['/usr/bin/python3', '-B', LINUX+'/prepare_diagnostic.py', 'setup'],
        'postgres': [WORK+'/tools/rtk', 'proxy', WORK+'/venv/bin/python', '-B', LINUX+'/prepare_diagnostic.py', 'postgres'],
        'run': [WORK+'/tools/rtk', 'proxy', WORK+'/venv/bin/python', '-B', LINUX+'/run_diagnostic.py'],
        'cleanup': [WORK+'/tools/rtk', 'proxy', WORK+'/venv/bin/python', '-B', LINUX+'/cleanup_diagnostic.py'],
    }
    path = HERE/('invocation-'+step+'.json')
    assert not path.exists(), 'Refusing duplicate invocation: '+step
    data = {'state': 'RUNNING', 'step': step, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    argv = ['rtk', 'proxy', 'wsl.exe', '-d', 'Ubuntu-24.04', '--exec', *commands[step]]
    start = time.monotonic()
    with (HERE/('invocation-'+step+'.log')).open('xb') as stream:
        code = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT).returncode
    data.update(state='COMPLETED', exit_code=code, seconds=time.monotonic()-start, argv=argv)
    temporary = path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(data, indent=2)+'\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    print(json.dumps(data), flush=True)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
