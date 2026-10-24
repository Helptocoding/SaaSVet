"""Post-STOP recovery of owned resources after host restart; never runs tests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from prepare_wsl import WORK, TREE, DATA, PG, PORT, RTK, environment


def save(name, data):
    p = HERE / name
    assert not p.exists(), name
    p.write_text(json.dumps(data, indent=2, default=str) + '\n', encoding='utf-8')


def run(label, args):
    argv = [str(RTK), 'proxy', *map(str, args)]
    p = subprocess.run(argv, cwd=WORK, env=environment(), stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=90)
    save(label + '.json', {'argv': argv, 'exit_code': p.returncode,
                         'stdout': p.stdout.decode(errors='replace'),
                         'stderr': p.stderr.decode(errors='replace')})
    assert p.returncode == 0, label
    return p.stdout.decode()


def closed():
    with socket.socket() as s:
        return s.connect_ex(('127.0.0.1', PORT)) != 0


def main():
    assert json.loads((HERE / 'STOP.json').read_text())['phase'] == 'full'
    assert WORK.resolve() == Path('/home/lap/b9i-wsl-1947726-20261012-r9')
    assert json.loads((HERE / 'assembly.json').read_text())['workspace'] == str(WORK)
    assert not (HERE / 'cleanup.json').exists()
    # Recheck hashes after reboot, in new receipts; never replace damaged originals.
    for name in ['candidate-sources', 'dependency-files', 'evaluation-seal']:
        data = json.loads((HERE / (name + '.json')).read_text())['files']
        mapping = {str(TREE / row['path']): row['sha256'] for row in data} if isinstance(data, list) else data
        bad = [p for p, h in mapping.items() if not Path(p).is_file()
               or hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
        save('recovery-integrity-' + name + '.json', {'checked': len(mapping), 'mismatches': bad,
             'observed_after_host_restart': True, 'replaces_original_receipt': False})
        assert not bad, (name, bad)
    own = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            args = (p / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, PermissionError):
            continue
        if args and args[0].startswith(str(WORK).encode()):
            own.append({'pid': int(p.name), 'argv': [a.decode(errors='replace') for a in args if a]})
    old_pid = (DATA / 'postmaster.pid').read_text() if (DATA / 'postmaster.pid').exists() else None
    save('cleanup-recovery-before.json', {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
         'port_closed': closed(), 'owned_processes': own, 'old_postmaster_pid_file': old_pid,
         'purpose': 'Restart only private PostgreSQL to preserve SQL ownership/tables and drop owned databases; no application tests'})
    assert closed() and not own
    shutil.copy2(WORK / 'postgresql.log', HERE / 'postgresql-before-recovery.log')
    # pg_ctl handles a stale postmaster.pid itself; no manual PID-file deletion.
    run('cleanup-recovery-pg-start', [PG / 'pg_ctl', '-D', DATA, '-l', WORK / 'postgresql.log', '-w', 'start'])
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        directory = conn.execute("SELECT current_setting('data_directory')").fetchone()[0]
        assert Path(directory).resolve() == DATA.resolve()
        names = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' ORDER BY datname")]
        active = conn.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
        prepared = conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
        locks = conn.execute('SELECT database,locktype,mode,granted,pid FROM pg_locks WHERE pid<>pg_backend_pid() ORDER BY pid,locktype,mode').fetchall()
        save('cleanup-sql-before.json', {'data_directory': directory, 'databases': names,
             'active_connections': active, 'prepared_transactions': prepared, 'locks_other_than_observer': locks,
             'observed_after_postgresql_crash_recovery': True})
        assert not active and not prepared
        assert all(n.startswith('test_b9i_') or n == 'test_b8b_b9i_directed' for n in names)
        for name in names:
            with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname=name) as db:
                tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
                save('cleanup-tables-' + name + '.json', {'tables': tables})
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        save('cleanup-sql-after-drop.json', {'databases': [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]})
    run('cleanup-recovery-pg-stop', [PG / 'pg_ctl', '-D', DATA, '-m', 'fast', '-w', 'stop'])
    shutil.copy2(WORK / 'postgresql.log', HERE / 'postgresql-final.log')
    assert closed() and not (DATA / 'postmaster.pid').exists()
    resolved = WORK.resolve()
    assert resolved == Path('/home/lap/b9i-wsl-1947726-20261012-r9')
    shutil.rmtree(resolved)
    assert not resolved.exists()
    save('cleanup.json', {'state': 'PASS', 'method': 'post-stop recovery after host restart',
         'original_cleanup_exit_code': 1, 'original_cleanup_error': 'private PostgreSQL connection refused',
         'original_receipt_preserved': True, 'databases_dropped': names, 'private_postgresql_stopped': True,
         'port': PORT, 'port_closed': True, 'owned_workspace_removed': str(resolved),
         'foreign_processes_terminated': False, 'raw_sql_saved_before_cleanup': True,
         'application_tests_executed_during_recovery': False, 'formal_reruns': 0})
    print('RECOVERY_CLEANUP_PASS', flush=True)


if __name__ == '__main__':
    main()
