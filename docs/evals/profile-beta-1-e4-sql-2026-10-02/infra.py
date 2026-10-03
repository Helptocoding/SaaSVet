"""Isolated PostgreSQL lifecycle for the frozen PROFILE-BETA-1 evaluation.

This only prepares and removes test databases. It does not implement a profile
scenario or alter its frozen runner, corpus, timings, or gates.
"""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql


PG = Path(r"C:\Users\LAP\AppData\Local\Temp\vet-b8b-pg16-bin\pgsql\bin")
DATA = Path(tempfile.gettempdir()) / "vet-profile-beta-1-e4-sql-20261002"
PORT = 35443
USER = "b9e"
PREFIX = "test_"
URI = f"postgresql://{USER}@127.0.0.1:{PORT}/postgres"


def command(*args):
    return subprocess.run(
        [str(item) for item in args], check=True, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def database_names():
    with psycopg.connect(URI, autocommit=True) as conn:
        return [row[0] for row in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE %s ORDER BY datname",
            (PREFIX + "%",),
        )]


def verify():
    with psycopg.connect(URI, autocommit=True) as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        fsync = conn.execute("SHOW fsync").fetchone()[0]
        synchronous_commit = conn.execute("SHOW synchronous_commit").fetchone()[0]
        clients = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname LIKE %s",
            (PREFIX + "%",),
        ).fetchone()[0]
        waiting_locks = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE NOT granted"
        ).fetchone()[0]
        prepared = conn.execute(
            "SELECT count(*) FROM pg_prepared_xacts"
        ).fetchone()[0]
    result = dict(port=PORT, version=version, fsync=fsync,
                  synchronous_commit=synchronous_commit,
                  databases=database_names(), clients=clients,
                  waiting_locks=waiting_locks, prepared_transactions=prepared)
    assert version.startswith("16.") and fsync == "on"
    assert synchronous_commit == "on"
    print(json.dumps(result))
    return result


def main():
    action = sys.argv[1]
    if action == "start":
        assert not DATA.exists(), f"Refusing existing data directory: {DATA}"
        command(PG / "initdb.exe", "-D", DATA, "-U", USER, "-A", "trust",
                "--encoding=UTF8", "--locale=C")
        command(PG / "pg_ctl.exe", "-D", DATA, "-l", DATA / "server.log",
                "-o", f"-p {PORT} -h 127.0.0.1 -c fsync=on -c synchronous_commit=on",
                "-w", "start")
        verify()
    elif action == "create":
        name = sys.argv[2]
        assert name.startswith(PREFIX) and name not in database_names()
        template = sys.argv[3] if len(sys.argv) > 3 else None
        with psycopg.connect(URI, autocommit=True) as conn:
            if template:
                assert template in database_names()
                conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(name), sql.Identifier(template)))
            else:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        verify()
    elif action == "verify":
        verify()
    elif action == "stop":
        observed = verify()
        assert observed["clients"] == observed["waiting_locks"] == observed["prepared_transactions"] == 0
        before = database_names()
        with psycopg.connect(URI, autocommit=True) as conn:
            for name in reversed(before):
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        verify()
        command(PG / "pg_ctl.exe", "-D", DATA, "-m", "fast", "-w", "stop")
        expected = Path(tempfile.gettempdir()).resolve()
        assert DATA.resolve().parent == expected
        shutil.rmtree(DATA)
        with socket.socket() as probe:
            port_closed = probe.connect_ex(("127.0.0.1", PORT)) != 0
        assert port_closed
        print(json.dumps(dict(status="CLEANED", dropped_databases=before,
                              data_directory_absent=not DATA.exists(), port=PORT,
                              port_closed=port_closed, clients=0,
                              waiting_locks=0, prepared_transactions=0)))
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main()
