"""Retire only the verified private Windows campaign after durable SQL evidence."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from native_support import EVIDENCE, REPO, WORK, TREE, DATA, PG, PORT, save, integrity, command, resources

EXPECTED_WORK=Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')


def read(name):
    return json.loads((EVIDENCE/name).read_text(encoding='utf-8'))


def verify_scope():
    resolved=WORK.resolve()
    assert resolved==EXPECTED_WORK and resolved!=REPO.resolve()
    assert WORK.is_dir() and not WORK.is_symlink() and not WORK.is_junction()
    assert Path(read('assembly.json')['workspace']).resolve()==resolved
    assert DATA.resolve()==resolved/'pgdata' and TREE.resolve()==resolved/'src'
    for path in (DATA,TREE):
        assert not path.is_symlink() and not path.is_junction()
    executable=Path(sys.executable).resolve()
    assert not executable.is_relative_to(resolved), 'Cleanup interpreter must be outside the owned workspace'
    assert not PG.resolve().is_relative_to(resolved), 'Shared PostgreSQL binaries must be preserved'
    assert PORT==35490
    return resolved,executable


def wrapper_handle():
    path=EVIDENCE/'postgresql-start.json'
    if not path.exists():
        return None,None,None
    start=read(path.name)
    pid=start['wrapper_pid']
    assert isinstance(pid,int) and pid>0 and pid!=os.getpid()
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel32.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel32.OpenProcess.restype=wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel32.WaitForSingleObject.restype=wintypes.DWORD
    kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel32.CloseHandle.restype=wintypes.BOOL
    handle=kernel32.OpenProcess(0x00100000,False,pid)  # SYNCHRONIZE only; never terminate a process.
    if not handle:
        error=ctypes.get_last_error()
        if error==87:  # ERROR_INVALID_PARAMETER: no process with this PID remains.
            return kernel32,None,pid
        raise ctypes.WinError(error)
    return kernel32,handle,pid


def wait_wrapper(kernel32,handle,pid):
    if pid is None:
        return {'state':'NOT_STARTED','wrapper_pid':None}
    if handle is None:
        return {'state':'EXITED_BEFORE_CLEANUP','wrapper_pid':pid}
    result=kernel32.WaitForSingleObject(handle,15000)
    if result==0xFFFFFFFF:
        raise ctypes.WinError(ctypes.get_last_error())
    if result!=0:
        raise RuntimeError('Owned PostgreSQL wrapper did not exit within 15 seconds')
    return {'state':'EXITED_CONFIRMED','wrapper_pid':pid,'wait_timeout_seconds':15}


def main():
    assert (EVIDENCE/'STOP.json').exists() or (EVIDENCE/'technical-completion.json').exists()
    assert not (EVIDENCE/'cleanup.json').exists(), 'Cleanup already decided'
    resolved,executable=verify_scope()
    integrity('final-before-cleanup')
    before=resources()
    cluster_created=DATA.exists()
    names=[]
    kernel32,handle,wrapper_pid=wrapper_handle()
    try:
        if cluster_created:
            assert (EVIDENCE/'postgresql-preflight.json').is_file()
            postmaster_pid=int((DATA/'postmaster.pid').read_text(encoding='utf-8').splitlines()[0])
            assert postmaster_pid==read('postgresql-preflight.json')['postmaster_pid']
            assert wrapper_pid is not None
            import psycopg
            from psycopg import sql
            with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',autocommit=True) as conn:
                directory,actual_port=conn.execute("SELECT current_setting('data_directory'),current_setting('port')").fetchone()
                assert Path(directory).resolve()==DATA.resolve() and actual_port==str(PORT)
                names=[row[0] for row in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' ORDER BY datname")]
                active=conn.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
                prepared=conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
                locks=conn.execute("SELECT database,locktype,mode,granted,pid FROM pg_locks WHERE pid<>pg_backend_pid() ORDER BY pid,locktype,mode").fetchall()
                save('cleanup-sql-before.json',{'data_directory':directory,'port':actual_port,
                    'postmaster_pid':postmaster_pid,'databases':names,'active_connections':active,
                    'prepared_transactions':prepared,'locks_other_than_observer':locks})
                assert not active and not prepared
                owned_full=set()
                if (EVIDENCE/'full-partition.json').exists():
                    from full_partition import validate_partition
                    owned_full={row['database'] for row in validate_partition()['groups']}
                assert all(name.startswith('test_b9i_') or name=='test_b8b_b9i_directed' or name in owned_full for name in names)
                save('cleanup-database-scope.json',{'owned_full_databases':sorted(owned_full),
                    'partition_validated':(EVIDENCE/'full-partition.json').exists(),'databases_to_drop':names})
                for name in names:
                    assert '/' not in name and '\\' not in name
                    with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname=name) as database:
                        tables=database.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
                        save('cleanup-tables-'+name+'.json',{'tables':tables})
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                save('cleanup-sql-after-drop.json',{'databases':[row[0] for row in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]})
            command('pg-stop',[PG/'pg_ctl.exe','-D',DATA,'-m','fast','-w','stop'])
        else:
            assert (EVIDENCE/'STOP.json').is_file(), 'Preparation-only cleanup requires a durable stop'
            save('cleanup-preparation-only.json',{'state':'OWNED_CLUSTER_NOT_CREATED',
                'sources_verified':True,'sql_executed':False,'resources':before})
        wrapper=wait_wrapper(kernel32,handle,wrapper_pid)
        save('postgresql-wrapper-closure.json',wrapper)
    finally:
        if handle is not None:
            kernel32.CloseHandle(handle)
    log=WORK/'postgresql.log'
    if cluster_created:
        assert log.is_file()
    if log.exists():
        shutil.copy2(log,EVIDENCE/'postgresql-final.log')
    with socket.socket() as sock:
        closed=sock.connect_ex(('127.0.0.1',PORT))!=0
    assert closed and not (DATA/'postmaster.pid').exists()
    # Recheck the exact absolute target immediately before extended-length removal.
    assert verify_scope()[0]==resolved
    save('cleanup-removal-scope.json',{'state':'VERIFIED','resolved_workspace':str(resolved),
        'extended_length_path_used':True,'cleanup_interpreter':str(executable),
        'interpreter_outside_workspace':True,'workspace_root_symlink_or_junction':False,
        'port_closed':closed,'postmaster_pid_file_absent':True,'wrapper':wrapper,
        'shared_postgresql_bin_preserved':str(PG.resolve()),'sql_saved_before_removal':cluster_created})
    extended='\\\\?\\'+str(resolved)
    shutil.rmtree(extended)
    assert not resolved.exists()
    save('cleanup.json',{'state':'PASS','databases_dropped':names,
        'postgresql_cluster_created':cluster_created,
        'postgresql_state':'STOPPED' if cluster_created else 'NOT_CREATED',
        'private_postgresql_stopped':cluster_created,'wrapper':wrapper,
        'port':PORT,'port_closed':closed,'postmaster_pid_file_absent':True,
        'owned_workspace_removed':str(resolved),'resolved_recursive_removal_target_verified':str(EXPECTED_WORK),
        'foreign_processes_terminated':False,'raw_sql_saved_before_cleanup':cluster_created,
        'sql_evidence':'SAVED_BEFORE_REMOVAL' if cluster_created else 'NOT_APPLICABLE_CLUSTER_NOT_CREATED',
        'cleanup_interpreter':str(executable),'interpreter_outside_workspace':True,
        'shared_postgresql_bin_preserved':str(PG.resolve()),'shared_python_environment_removed':False,
        'previous_campaigns_and_windows_environments_preserved':True,
        'resources_before':before,'resources_after':resources()})
    print('CLEANUP_PASS',flush=True)


if __name__=='__main__':
    main()
