"""Retire only resources belonging to this campaign after durable SQL evidence."""
import json
from pathlib import Path
import shutil
import socket
from prepare_wsl import EVIDENCE, WORK, DATA, PG, PORT, save, integrity, command

def main():
    assert (EVIDENCE / 'STOP.json').exists() or (EVIDENCE / 'technical-completion.json').exists()
    integrity('final-before-cleanup')
    resolved = WORK.resolve()
    assert resolved == Path('/home/lap/b9i-wsl-1947726-20261011-r3')
    assert json.loads((EVIDENCE / 'assembly.json').read_text())['workspace'] == str(resolved)
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        directory = conn.execute("SELECT current_setting('data_directory')").fetchone()[0]
        assert Path(directory).resolve() == DATA.resolve()
        names = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' ORDER BY datname")]
        active = conn.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
        prepared = conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
        locks = conn.execute("SELECT database,locktype,mode,granted,pid FROM pg_locks WHERE pid<>pg_backend_pid() ORDER BY pid,locktype,mode").fetchall()
        save('cleanup-sql-before.json', {'data_directory': directory, 'databases': names,
            'active_connections': active, 'prepared_transactions': prepared, 'locks_other_than_observer': locks})
        assert not active and not prepared
        assert all(n.startswith('test_b9i_') or n == 'test_b8b_b9i_directed' for n in names)
        for name in names:
            with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname=name) as database:
                tables = database.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
                save('cleanup-tables-' + name + '.json', {'tables': tables})
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        save('cleanup-sql-after-drop.json', {'databases': [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]})
    command('pg-stop', [PG / 'pg_ctl', '-D', DATA, '-m', 'fast', '-w', 'stop'])
    shutil.copy2(WORK / 'postgresql.log', EVIDENCE / 'postgresql-final.log')
    with socket.socket() as sock:
        closed = sock.connect_ex(('127.0.0.1', PORT)) != 0
    assert closed and not (DATA / 'postmaster.pid').exists()
    shutil.rmtree(resolved)
    assert not resolved.exists()
    save('cleanup.json', {'state': 'PASS', 'databases_dropped': names, 'private_postgresql_stopped': True,
        'port': PORT, 'port_closed': closed, 'owned_workspace_removed': str(resolved),
        'foreign_processes_terminated': False, 'raw_sql_saved_before_cleanup': True,
        'previous_campaigns_and_windows_environments_preserved': True})
    print('CLEANUP_PASS', flush=True)

if __name__ == '__main__':
    main()
