"""Complete the one corrected healthy + noisy fixture on isolated PG16."""
import json
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg import sql

import benchmark as b

assert subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'],
                               cwd=b.ROOT, text=True).strip() == b.BASELINE
assert not b.DATA.exists()
assert not (b.OUT / 'explain/mixed_ready-354.json').exists()
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
b.write('environment-mixed-ready.json', dict(baseline=b.BASELINE, runtime_sha=b.RUNTIME,
    postgresql='16.15', python='3.13.2', django='6.0.5', port=port,
    correction='Both healthy orgs have ready inbound; noisy org retains 229 pending messages',
    isolated=True, no_production=True))
started = False
server = None
try:
    b.command([b.PG / 'initdb.exe', '-D', b.DATA, '-U', 'e4bench', '-A', 'trust',
               '--encoding=UTF8', '--locale=C'], stdout=subprocess.DEVNULL)
    with (b.DATA / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen([str(b.PG / 'postgres.exe'), '-D', str(b.DATA),
            '-p', str(port), '-h', '127.0.0.1'], stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(uri, connect_timeout=1) as conn:
                version, fsync, commit, data = conn.execute(
                    "SELECT version(), current_setting('fsync'), current_setting('synchronous_commit'), current_setting('data_directory')").fetchone()
                assert '16.15' in version and (fsync, commit) == ('on', 'on')
                assert Path(data).resolve() == b.DATA.resolve()
                break
        except psycopg.OperationalError:
            if server.poll() is not None:
                raise RuntimeError(f'PostgreSQL exited: {server.returncode}')
            time.sleep(.2)
    else:
        raise RuntimeError('PostgreSQL did not become ready')
    started = True
    template = b.PREFIX + 'template'
    with psycopg.connect(uri, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(template)))
    with (b.OUT / 'migrate-mixed-ready.log').open('x', encoding='utf-8') as log:
        b.command([b.PY, '-X', 'utf8', 'manage.py', 'migrate', '--noinput'],
                  cwd=b.ROOT / 'backend', env=b.environment(port, template),
                  stdout=log, stderr=subprocess.STDOUT)
    database = b.PREFIX + 'mixed_ready_354'
    with psycopg.connect(uri, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(database), sql.Identifier(template)))
    proc = subprocess.run(['rtk', 'proxy', str(b.PY), '-X', 'utf8', b.__file__,
                           'point', 'mixed_ready', '354'], cwd=b.ROOT / 'backend',
                           env=b.environment(port, database), capture_output=True, text=True)
    if proc.returncode:
        b.write('mixed-ready-failure.json', dict(exit_code=proc.returncode,
                stderr=proc.stderr[-4000:]))
        raise RuntimeError('Mixed ready point failed')
    result = json.loads(proc.stdout)
    b.write('matrix-mixed-ready.json', [result])
    print(json.dumps(dict(kind='mixed_ready', ms=result['selector_sql_ms'])), flush=True)
finally:
    if started:
        with psycopg.connect(uri, autocommit=True) as conn:
            names = [row[0] for row in conn.execute('SELECT datname FROM pg_database')
                     if row[0].startswith(b.PREFIX)]
            clients = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchone()[0]
            assert clients == 0
            for name in names:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        b.command([b.PG / 'pg_ctl.exe', '-D', b.DATA, '-m', 'fast', '-w', 'stop'],
                  stdout=subprocess.DEVNULL)
        server.wait(timeout=15)
    if b.DATA.exists():
        assert b.DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(b.DATA)
    b.write('cleanup-mixed-ready.json', dict(status='CLEANED', stopped=started,
            data_directory_absent=not b.DATA.exists(), port=port))
