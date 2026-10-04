"""Resume only tests without a successful per-ID receipt after host interruption."""
import json
import subprocess
import sys
import time

import psycopg

import verify


def main():
    for _ in range(120):
        try:
            with psycopg.connect(verify.URI+'postgres', connect_timeout=3):
                break
        except psycopg.OperationalError:
            time.sleep(5)
    else:
        raise RuntimeError('Isolated PostgreSQL recovery did not finish')
    (verify.OUT/'resumed-environment.json').write_text(
        json.dumps(verify.verify(), indent=2)+'\n')
    selection = json.loads((verify.OUT/'recovery-selection.json').read_text())
    command = [sys.executable, str(verify.OUT/'verify.py'), 'test',
               *selection['remaining'], '--tag', 'recovery-regression']
    return subprocess.call(command, creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    raise SystemExit(main())
