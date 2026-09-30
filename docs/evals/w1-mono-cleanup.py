"""Retire only this task's isolated PostgreSQL cluster and disposable fixtures."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('C:/Users/LAP/AppData/Local/Temp/vet-w1-mono-pg16-data').resolve()
LOG = Path('C:/Users/LAP/AppData/Local/Temp/vet-w1-mono-pg16.log').resolve()
PG = Path('C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin')
EXPECTED_PARENT = Path('C:/Users/LAP/AppData/Local/Temp').resolve()
assert DATA.parent == EXPECTED_PARENT and DATA.name == 'vet-w1-mono-pg16-data'
assert LOG.parent == EXPECTED_PARENT and LOG.name == 'vet-w1-mono-pg16.log'

with psycopg.connect('postgresql://w1mono@127.0.0.1:35442/postgres', autocommit=True) as conn:
    row = conn.execute("SELECT version(), current_setting('data_directory'), current_setting('fsync'), current_setting('synchronous_commit')").fetchone()
    assert Path(row[1]).resolve() == DATA
    assert row[2:] == ('on', 'on')
    clients = conn.execute("SELECT pid, datname FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
    assert not clients, clients
    waiting = conn.execute('SELECT count(*) FROM pg_locks WHERE NOT granted').fetchone()[0]
    prepared = conn.execute('SELECT count(*) FROM pg_prepared_xacts').fetchone()[0]
    assert waiting == prepared == 0
    names = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'test_b8b_w1_mono_%' ORDER BY datname")]
    counts = {}
    for name in names:
        with psycopg.connect('postgresql://w1mono@127.0.0.1:35442/' + name) as fixture:
            counts[name] = {table: fixture.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                for table in ('organizations_organization', 'agent_turnwork', 'channels_message', 'agent_llmcall')}
        conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    remaining = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'test_b8b_w1_mono_%'").fetchall()
    assert not remaining
receipt = dict(status='CLEANED', cluster=str(DATA), port=35442, version=row[0],
    fsync=row[2], synchronous_commit=row[3], other_clients=clients, waiting_locks=waiting,
    prepared_transactions=prepared, dropped_databases=names, fixture_counts=counts,
    remaining_databases=remaining, server_log_sha256=hashlib.sha256(LOG.read_bytes()).hexdigest())
stopped = subprocess.run([str(PG/'pg_ctl.exe'), '-D', str(DATA), '-m', 'fast', '-w', 'stop'], capture_output=True, text=True)
assert stopped.returncode == 0, stopped.stderr
receipt['stop_exit_code'] = stopped.returncode
receipt['stop_output'] = stopped.stdout.strip()
receipt['server_log_sha256'] = hashlib.sha256(LOG.read_bytes()).hexdigest()
with socket.socket() as probe:
    assert probe.connect_ex(('127.0.0.1', 35442)) != 0
receipt['port_closed'] = True
# Resolve and recheck immediately before recursive deletion. Other clusters,
# shared binaries and the locked Python environment are deliberately retained.
assert DATA.resolve() == EXPECTED_PARENT/'vet-w1-mono-pg16-data'
shutil.rmtree(DATA)
LOG.unlink()
receipt['data_directory_absent'] = not DATA.exists()
receipt['log_absent'] = not LOG.exists()
(ROOT/'docs/evals/w1-mono/cleanup.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(databases=len(names), port_closed=True, data_directory_absent=True)))
