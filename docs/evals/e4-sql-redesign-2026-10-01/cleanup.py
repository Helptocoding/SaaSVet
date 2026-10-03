"""Inspect or remove only this experiment's verified local PostgreSQL cluster."""
import json
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

from benchmark import DATA, OUT, PG, command


def main():
    port = json.loads((OUT / 'environment-full.json').read_text())['port']
    expected = Path(tempfile.gettempdir()) / 'vet-e4-sql-redesign-2026-10-01-data'
    assert DATA.resolve() == expected.resolve()
    assert DATA.resolve().parent == Path(tempfile.gettempdir()).resolve()
    uri = f'postgresql://e4bench@127.0.0.1:{port}/postgres'
    with psycopg.connect(uri, autocommit=True) as conn:
        version, actual = conn.execute("SELECT version(),current_setting('data_directory')").fetchone()
        assert 'PostgreSQL 16.15' in version and Path(actual).resolve() == DATA.resolve()
        if sys.argv[1:] == ['inspect']:
            rows = conn.execute("""SELECT datname,state,wait_event_type,wait_event,
                extract(epoch from now()-query_start)::int,left(query,160)
                FROM pg_stat_activity
                WHERE datname LIKE 'test_b8b_e4sql20261001_regression%'""").fetchall()
            print(json.dumps(rows, default=str, indent=2))
            return
        assert sys.argv[1:] == ['clean']
        assert json.loads((OUT / 'verification-summary.json').read_text())['status'] == 'OPTIMIZATION_VERIFIED'
        assert not (OUT / 'cleanup.json').exists()
        clients = conn.execute("""SELECT pid,datname FROM pg_stat_activity
            WHERE backend_type='client backend' AND pid<>pg_backend_pid()""").fetchall()
        assert not clients, clients
        names = [r[0] for r in conn.execute('SELECT datname FROM pg_database')]
        owned = [n for n in names if n.startswith(('test_e4_sql_redesign_', 'test_b8b_e4sql20261001_'))]
        assert set(names) - set(owned) == {'postgres', 'template0', 'template1'}, names
        pid = int((DATA / 'postmaster.pid').read_text().splitlines()[0])
        for name in owned:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    command([PG / 'pg_ctl.exe', '-D', DATA, '-m', 'fast', '-w', 'stop'])
    assert not (DATA / 'postmaster.pid').exists()
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0
    # Exact absolute target checked above before recursive removal.
    shutil.rmtree(DATA)
    assert not DATA.exists()
    receipt = dict(stopped=True, port=port, server_pid=pid, postgres=version,
        databases_dropped=owned, data_directory=str(DATA.resolve()), data_directory_absent=True,
        no_remaining_clients=True, unrelated_servers_untouched=True,
        shared_binaries_and_python_environment_preserved=True)
    (OUT / 'cleanup.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('ISOLATED_INFRA_CLEANED', flush=True)


if __name__ == '__main__':
    main()
