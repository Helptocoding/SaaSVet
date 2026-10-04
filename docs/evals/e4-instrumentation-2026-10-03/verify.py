"""Local instrumentation verification only; never executes a PROFILE runner."""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DATA = Path(tempfile.gettempdir()) / 'vet-e4-instrumentation-20261003'
PG = Path(tempfile.gettempdir()) / 'vet-b8b-pg16-bin/pgsql/bin'
PORT = 35447
USER = 'e4trace'
TEMPLATE = 'test_b8b_e4trace_template'
PREFIX = 'test_b8b_e4trace_'
URI = f'postgresql://{USER}@127.0.0.1:{PORT}/'


def env():
    result = dict(os.environ, DATABASE_URL=URI+TEMPLATE, SECRET_KEY=secrets.token_urlsafe(48),
        DEBUG='False', ENVIRONMENT='dev', DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='',
        DISCORD_WEBHOOK_URL='', HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
        PYTHONIOENCODING='utf-8', DJANGO_SETTINGS_MODULE='config.settings')
    return result


def run(command, log, evidence=None):
    environment = env()
    if evidence:
        environment['E4_TRACE_EVIDENCE_DIR'] = str(evidence)
    with log.open('x', encoding='utf-8') as output:
        result = subprocess.run([str(x) for x in command], cwd=ROOT/'backend', env=environment,
            stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode


def verify():
    with psycopg.connect(URI+'postgres', autocommit=True) as conn:
        row = conn.execute("SELECT current_setting('data_directory'), version(), "
            "current_setting('fsync'), current_setting('synchronous_commit')").fetchone()
        assert Path(row[0]).resolve() == DATA.resolve() and row[2:] == ('on', 'on')
        return dict(data_directory=str(DATA), port=PORT, postgresql=row[1], fsync=row[2],
                    synchronous_commit=row[3], classification='DIAGNOSTIC_ONLY')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start','resume','test','checks','stop'))
    parser.add_argument('--tag', default='targeted-1')
    parser.add_argument('modules', nargs='*')
    args = parser.parse_args()
    if args.action == 'start':
        assert not DATA.exists()
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', PORT)) != 0
        code = run([PG/'initdb.exe', '-D', DATA, '-U', USER, '-A','trust',
                    '--encoding=UTF8', '--locale=C'], OUT/'init.log')
        assert code == 0
        code = run([PG/'pg_ctl.exe','-D', DATA, '-l', DATA/'server.log','-o',
            f'-p {PORT} -h 127.0.0.1 -c fsync=on -c synchronous_commit=on', '-w','start'], OUT/'start.log')
        assert code == 0
        receipt = verify()
        with psycopg.connect(URI+'postgres', autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(TEMPLATE)))
        code = run([sys.executable,'manage.py','migrate','--noinput'], OUT/'migrate.log')
        receipt['migration_exit'] = code
        (OUT/'environment.json').write_text(json.dumps(receipt, indent=2)+'\n')
        assert code == 0
    elif args.action == 'resume':
        receipt = json.loads((OUT/'environment.json').read_text())
        assert DATA.resolve() == Path(receipt['data_directory']).resolve()
        assert (DATA/'PG_VERSION').read_text().strip() == '16'
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', PORT)) != 0
        code = run([PG/'pg_ctl.exe','-D', DATA, '-l', DATA/'server.log','-o',
            f'-p {PORT} -h 127.0.0.1 -c fsync=on -c synchronous_commit=on', '-w','start'],
            OUT/'resume.log')
        assert code == 0
        (OUT/'resumed-environment.json').write_text(json.dumps(verify(), indent=2)+'\n')
    elif args.action in ('test','checks'):
        verify()
        output = OUT/args.tag
        assert not output.with_suffix('.exit.json').exists()
        database = TEMPLATE if args.action == 'checks' else PREFIX+args.tag.replace('-', '_')
        if args.action == 'test':
            with psycopg.connect(URI+'postgres', autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
                    sql.Identifier(database), sql.Identifier(TEMPLATE)))
        command = [sys.executable,'-m','apps.agent.tests.run_b9a_acceptance', '--suite',
            'checks' if args.action == 'checks' else 'targeted', '--database',
            database, '--output', output]
        if args.action == 'test':
            assert args.modules
            selected = OUT/(args.tag+'-ids.json')
            selected.write_text(json.dumps(args.modules, indent=2)+'\n')
            command += ['--ids-file', selected]
        code = run(command, OUT/(args.tag+'-launch.log'), OUT/'artifacts'/args.tag)
        print(json.dumps(dict(action=args.action, tag=args.tag, exit_code=code)), flush=True)
        return code
    else:
        verify()
        with psycopg.connect(URI+'postgres', autocommit=True) as conn:
            assert conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid<>pg_backend_pid() "
                "AND backend_type='client backend'").fetchone()[0] == 0
            assert conn.execute('SELECT count(*) FROM pg_locks WHERE NOT granted').fetchone()[0] == 0
            names = [r[0] for r in conn.execute('SELECT datname FROM pg_database') if r[0].startswith(PREFIX)]
            for name in names:
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        code = run([PG/'pg_ctl.exe','-D',DATA,'-m','fast','-w','stop'], OUT/'stop.log')
        assert code == 0
        # Retain the isolated cluster files for inspectability; no recursive deletion.
        with socket.socket() as probe:
            closed = probe.connect_ex(('127.0.0.1', PORT)) != 0
        assert closed
        (OUT/'cleanup.json').write_text(json.dumps(dict(status='STOPPED', port_closed=closed,
            dropped_databases=names, data_directory_retained=str(DATA), clients=0, waiting_locks=0), indent=2)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
