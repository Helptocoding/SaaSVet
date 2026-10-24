"""Capture SQL ownership, then retire only this diagnostic's resources."""
import json
from pathlib import Path
import shutil
import socket
from prepare_wsl import EVIDENCE, WORK, DATA, PG, PORT, save, command, integrity


def main():
    receipt = json.loads((EVIDENCE/'diagnostic.command.json').read_text())
    assert receipt['state'] == 'COMPLETED'
    integrity('final-before-cleanup')
    resolved = WORK.resolve()
    assert resolved == Path('/home/lap/b9i-correction-20261013')
    assert json.loads((EVIDENCE/'assembly.json').read_text())['workspace'] == str(resolved)
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        directory = conn.execute("SELECT current_setting('data_directory')").fetchone()[0]
        assert Path(directory).resolve() == DATA.resolve()
        names = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' ORDER BY datname")]
        active = conn.execute("SELECT datname,pid,state FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
        prepared = conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
        save('cleanup-sql-before.json', {'data_directory': directory, 'databases': names,
             'active_connections': active, 'prepared_transactions': prepared})
        assert not active and not prepared
        assert all(n in ['test_b9i_diagnostic_control', 'test_b9i_diagnostic_11'] for n in names)
        for n in names:
            with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname=n) as db:
                save('cleanup-tables-'+n+'.json', {'tables': db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()})
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(n)))
        save('cleanup-sql-after.json', {'databases': [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]})
    command('pg-stop', [PG/'pg_ctl', '-D', DATA, '-m', 'fast', '-w', 'stop'])
    shutil.copy2(WORK/'postgresql.log', EVIDENCE/'postgresql-final.log')
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', PORT)) != 0
    assert not (DATA/'postmaster.pid').exists()
    assert resolved == Path('/home/lap/b9i-correction-20261013')
    shutil.rmtree(resolved)
    assert not resolved.exists()
    save('cleanup.json', {'state': 'PASS', 'databases_dropped': names, 'port_closed': True,
         'private_postgresql_stopped': True, 'owned_workspace_removed': str(resolved),
         'foreign_processes_terminated': False, 'tests_run_during_cleanup': False})
    print('DIAGNOSTIC_CLEANUP_PASS', flush=True)


if __name__ == '__main__':
    main()
