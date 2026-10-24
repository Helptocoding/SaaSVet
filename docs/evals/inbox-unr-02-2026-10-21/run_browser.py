"""Own one hidden Windows server tree; never stop a pre-existing listener."""
import json
import socket
import subprocess
import time
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]


def listening():
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(('127.0.0.1', 4178)) == 0


assert not listening(), 'Port occupied: do not reuse or terminate another server'
start = time.monotonic()
with (out / 'vite.log').open('w', encoding='utf-8') as log:
    server = subprocess.Popen(['rtk', 'proxy', 'node', 'frontend/node_modules/vite/bin/vite.js',
        'frontend', '--host', '127.0.0.1', '--port', '4178', '--strictPort'], cwd=root,
        stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    code = 1
    try:
        while not listening():
            assert server.poll() is None, 'Vite exited; inspect vite.log'
            assert time.monotonic() - start < 60
            time.sleep(0.2)
        with (out / 'browser.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(['rtk', 'proxy', 'python', '-X', 'utf8', str(out / 'check_browser.py')],
                cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                creationflags=subprocess.CREATE_NO_WINDOW)
            code = result.returncode
    finally:
        subprocess.run(['rtk', 'proxy', 'taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
        server.wait(timeout=10)
        receipt = {'exit_code': code, 'elapsed_s': time.monotonic() - start,
                   'temporary_server_listening': listening(), 'synthetic_api': True}
        (out / 'browser-run.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))
        if (out / 'browser.log').exists():
            print('\n'.join((out / 'browser.log').read_text(encoding='utf-8').splitlines()[-10:]))
raise SystemExit(code or int(receipt['temporary_server_listening']))
