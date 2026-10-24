"""Capture each WSL invocation once, including its original output bytes."""
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LINUX = '/mnt/c/Users/LAP/Desktop/VeterinariaSaaS/docs/evals/' + HERE.name
WORK = '/home/lap/b9i-wsl-1947726-20261012-r9'

def main():
    step = sys.argv[1]
    args = {
        'preseal-prepare': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/preseal_prepare.py'],
        'assemble': ['/usr/bin/python3', '-B', LINUX + '/prepare_wsl.py', 'assemble'],
        'interpreters': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/interpreter_preflight.py'],
        'runtimes': ['/usr/bin/python3', '-B', LINUX + '/prepare_wsl.py', 'runtimes'],
        'postgres-packages': ['/usr/bin/python3', '-B', LINUX + '/prepare_wsl.py', 'postgres-packages'],
        'stage': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/stage_wsl.py'],
        'validate': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/launch_campaign.py', '--validate-only'],
        'formal': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/launch_campaign.py'],
        'cleanup': [WORK + '/tools/rtk', 'proxy', WORK + '/venv/bin/python', '-B', LINUX + '/cleanup_linux.py'],
    }[step]
    receipt = HERE / ('invocation-' + step + '.json')
    if receipt.exists():
        raise RuntimeError('Refusing duplicate invocation: ' + step)
    argv = ['rtk', 'proxy', 'wsl.exe', '-d', 'Ubuntu-24.04', '--exec', *args]
    start = time.monotonic()
    data = {'step': step, 'state': 'RUNNING', 'argv': argv, 'utc_started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    receipt.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    with (HERE / ('invocation-' + step + '.log')).open('wb') as stream:
        code = subprocess.run(argv, cwd=HERE.parents[2], stdin=subprocess.DEVNULL,
                              stdout=stream, stderr=subprocess.STDOUT).returncode
    data.update(state='COMPLETED', exit_code=code, seconds=time.monotonic() - start)
    receipt.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(data), flush=True)
    raise SystemExit(code)

if __name__ == '__main__':
    main()
