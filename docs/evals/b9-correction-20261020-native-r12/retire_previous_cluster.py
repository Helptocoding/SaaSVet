"""Stop only the verified r11 disposable PostgreSQL; preserve files and databases."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import socket
import time
from native_support import EVIDENCE, WORK, DATA, TREE, PG, PORT, RTK, save, sha256, command

EXPECTED_WORK=Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
PREVIOUS=EVIDENCE.with_name('b9-correction-20261020-native-r11')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify_scope():
    root=WORK.resolve()
    assert root==EXPECTED_WORK.resolve() and WORK.is_dir()
    assert not WORK.is_symlink() and not WORK.is_junction()
    assert DATA.resolve()==root/'pgdata' and TREE.resolve()==root/'src'
    assert all(not p.is_symlink() and not p.is_junction() for p in (DATA,TREE))
    assert PORT==35490 and PG.resolve()!=root and not PG.resolve().is_relative_to(root)
    for name in ('postgresql.conf','pg_hba.conf'):
        assert (DATA/name).read_bytes()==(EVIDENCE/'private-postgresql'/name).read_bytes()
    return root


def kernel_api():
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    k.OpenProcess.restype=wintypes.HANDLE
    k.CloseHandle.argtypes=[wintypes.HANDLE];k.CloseHandle.restype=wintypes.BOOL
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.restype=wintypes.BOOL
    k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    k.GetProcessTimes.restype=wintypes.BOOL
    k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    k.WaitForSingleObject.restype=wintypes.DWORD
    return k


def identity(k,pid,expected_image):
    assert isinstance(pid,int) and pid>0
    handle=k.OpenProcess(0x00101000,False,pid) # query limited information + synchronize, never terminate
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        text=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(text))
        if not k.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert Path(text.value).resolve()==expected_image.resolve(), (pid,text.value)
        times=[wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle,*[ctypes.byref(x) for x in times]):
            raise ctypes.WinError(ctypes.get_last_error())
        creation=((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)/10000000-11644473600
        assert k.WaitForSingleObject(handle,0)==258, 'Expected process already exited'
        return handle,dict(pid=pid,image=text.value,created_epoch_seconds=creation)
    except BaseException:
        k.CloseHandle(handle)
        raise


def parent_pid(pid):
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
            ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
            ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
            ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
            ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    k=kernel_api()
    k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    k.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    k.Process32FirstW.restype=wintypes.BOOL
    k.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    k.Process32NextW.restype=wintypes.BOOL
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        row=Entry();row.dwSize=ctypes.sizeof(row)
        ok=k.Process32FirstW(snapshot,ctypes.byref(row))
        while ok:
            if row.th32ProcessID==pid:return row.th32ParentProcessID
            ok=k.Process32NextW(snapshot,ctypes.byref(row))
        raise RuntimeError('Owned postmaster not present in process snapshot')
    finally:k.CloseHandle(snapshot)


def confirm_port_free():
    with socket.socket() as probe:
        probe.settimeout(2)
        assert probe.connect_ex(('127.0.0.1',PORT))!=0, 'Owned port still listening'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',PORT))


def process_snapshot():
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
            ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
            ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
            ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
            ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    k=kernel_api()
    k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    k.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    k.Process32FirstW.restype=wintypes.BOOL
    k.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
    k.Process32NextW.restype=wintypes.BOOL
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        rows=[];row=Entry();row.dwSize=ctypes.sizeof(row)
        ok=k.Process32FirstW(snapshot,ctypes.byref(row))
        while ok:
            rows.append(dict(pid=int(row.th32ProcessID),parent_pid=int(row.th32ParentProcessID),
                image_name=row.szExeFile))
            ok=k.Process32NextW(snapshot,ctypes.byref(row))
        error=ctypes.get_last_error()
        assert rows and error==18, ('Incomplete process snapshot',error)
        return rows
    finally:k.CloseHandle(snapshot)


def confirm_previous_absence(wrapper,postmaster):
    assert all(isinstance(pid,int) and pid>0 for pid in (wrapper,postmaster))
    status_path=EVIDENCE/'previous-cluster-owned-status.json'
    status=read(status_path)
    assert status['state']=='CONFIRMED_NOT_RUNNING' and status['exit_code']==3
    assert status['argv']==[str(RTK),'proxy',str(PG/'pg_ctl.exe'),'-D',str(DATA),'status']
    assert status['tests_executed'] is False
    rows=process_snapshot()
    assert not [row for row in rows if row['pid'] in (wrapper,postmaster)], 'Previous PID exists or was reused'
    k=kernel_api();postgres_images=[];unknown_images=[]
    for row in rows:
        if row['image_name'].lower()!='postgres.exe':continue
        handle=k.OpenProcess(0x1000,False,row['pid']) # query only, never terminate
        if not handle:
            error=ctypes.get_last_error()
            if error==87:continue # Process exited after the snapshot; rechecked below.
            if error==5:
                unknown_images.append(dict(pid=row['pid'],image_name=row['image_name'],
                    query_error=error,image_path=None,ownership='UNKNOWN_OTHER_PID'))
                continue
            raise ctypes.WinError(error)
        try:
            text=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(text))
            if not k.QueryFullProcessImageNameW(handle,0,text,ctypes.byref(length)):
                error=ctypes.get_last_error()
                if error==5:
                    unknown_images.append(dict(pid=row['pid'],image_name=row['image_name'],
                        query_error=error,image_path=None,ownership='UNKNOWN_OTHER_PID'))
                    continue
                raise ctypes.WinError(error)
            postgres_images.append(dict(pid=row['pid'],image=text.value))
            assert Path(text.value).resolve()!=(PG/'postgres.exe').resolve(), 'A PostgreSQL process using this binary remains'
        finally:k.CloseHandle(handle)
    again=process_snapshot()
    assert not [row for row in again if row['pid'] in (wrapper,postmaster)], 'Previous PID appeared during verification'
    assert {row['pid'] for row in again if row['image_name'].lower()=='postgres.exe'} <= {
        row['pid'] for row in postgres_images+unknown_images}, 'PostgreSQL process changed during verification'
    return dict(observed_epoch_seconds=time.time(),previous_wrapper_pid=wrapper,
        previous_postmaster_pid=postmaster,previous_pids_absent=True,
        matching_postgresql_image_present=None if unknown_images else False,
        global_postgresql_image_absence_claimed=False,
        unknown_other_postgresql_images=unknown_images,other_postgresql_images=postgres_images,
        owned_status_receipt=status_path.relative_to(EVIDENCE).as_posix(),
        owned_status_receipt_sha256=sha256(status_path.read_bytes()),owned_pg_ctl_status_exit_code=3)


def stable_previous_log():
    path=PREVIOUS/'postgresql-start-1.log'
    assert path.is_file()
    first=path.read_bytes();time.sleep(.25);second=path.read_bytes()
    assert first==second, 'Previous server log is still changing'
    return dict(path=str(path),bytes=len(second),sha256=sha256(second),
        stable_across_read_interval=True,read_interval_seconds=.25)


def record_already_stopped(start,preflight):
    wrapper=start['wrapper_pid'];postmaster=preflight['postmaster_pid']
    assert wrapper!=postmaster and start['postmaster_pid']==postmaster
    assert start['state']=='PASS_READY' and preflight['private_cluster'] is True
    before=confirm_previous_absence(wrapper,postmaster)
    confirm_port_free();verify_scope()
    oldlog=stable_previous_log()
    pidfile=DATA/'postmaster.pid';raw=pidfile.read_bytes() if pidfile.exists() else None
    preserved=None
    if raw is not None:
        lines=raw.decode('utf-8').splitlines()
        assert int(lines[0])==postmaster and Path(lines[1]).resolve()==DATA.resolve()
        assert int(lines[3])==PORT
        assert abs(start['postmaster']['created_epoch_seconds']-int(lines[2]))<=5
        target=EVIDENCE/'previous-cluster-stale-postmaster.pid'
        with target.open('xb') as stream:stream.write(raw)
        assert target.read_bytes()==raw
        preserved=dict(path=target.relative_to(EVIDENCE).as_posix(),bytes=len(raw),sha256=sha256(raw))
    save('previous-cluster-retirement-intent.json',dict(state='ALREADY_STOPPED_PROCESS_ABSENCE_VERIFIED',
        previous_campaign=PREVIOUS.name,workspace=str(WORK),data_directory=str(DATA),port=PORT,
        previous_wrapper_pid=wrapper,previous_postmaster_pid=postmaster,process_absence=before,
        preserved_stale_pidfile=preserved,stop_command_executed=False,
        owned_process_exit_observed=False,clean_shutdown_observed=False,
        foreign_processes_targeted=False,databases_to_drop=[],workspace_removal=False))
    verify_scope();confirm_port_free()
    after=confirm_previous_absence(wrapper,postmaster)
    assert stable_previous_log()==oldlog, 'Previous log changed during absence verification'
    if raw is not None:
        assert pidfile.resolve()==EXPECTED_WORK.resolve()/'pgdata/postmaster.pid'
        assert pidfile.read_bytes()==raw
        save('previous-cluster-stale-lock-decision.json',dict(state='VERIFIED_ORPHANED_PIDFILE',
            previous_campaign=PREVIOUS.name,data_directory=str(DATA),port=PORT,
            preserved_file=preserved,process_absence=after,port_verified_free=True,
            only_this_lock_removed=True,no_clean_shutdown_claim=True))
        pidfile.unlink()
    assert not pidfile.exists()
    confirm_port_free();verify_scope()
    final=confirm_previous_absence(wrapper,postmaster)
    assert stable_previous_log()==oldlog
    save('previous-cluster-retirement.json',dict(state='PASS',mode='ALREADY_STOPPED_VERIFIED_ABSENT',
        previous_campaign=PREVIOUS.name,workspace=str(WORK),data_directory=str(DATA),port=PORT,
        port_closed=True,postmaster_pid_file_absent=True,previous_wrapper_pid=wrapper,
        previous_postmaster_pid=postmaster,owned_processes_currently_absent=True,
        verified_owned_processes_exited=False,owned_process_exit_observed=False,
        clean_shutdown_observed=False,previous_exit_code=None,stop_command_executed=False,
        process_absence_before=before,process_absence_after=final,previous_log=oldlog,
        preserved_stale_pidfile=preserved,only_verified_stale_pidfile_removed=raw is not None,
        previous_start_receipt_sha256=sha256((PREVIOUS/'postgresql-start.json').read_bytes()),
        previous_preflight_sha256=sha256((PREVIOUS/'postgresql-preflight.json').read_bytes()),
        application_tests_executed=False,runtime_reinstalled=False,databases_dropped=[],
        workspace_removed=False,foreign_processes_terminated=False,
        old_final_logs_stable_before_prior_evidence_snapshot=True))
    print('PREVIOUS_CLUSTER_ALREADY_STOPPED_ABSENCE_VERIFIED_PRESERVED',flush=True)


def main():
    verify_scope()
    assert not (EVIDENCE/'previous-cluster-retirement.json').exists()
    assert not (EVIDENCE/'previous-cluster-retirement-intent.json').exists(), 'No automatic retirement retry'
    start=read(PREVIOUS/'postgresql-start.json');preflight=read(PREVIOUS/'postgresql-preflight.json')
    assert preflight['state']=='PASS'
    assert start['port']==preflight['port']==PORT
    assert Path(start['data_directory']).resolve()==DATA.resolve()
    expected_argv=[str(RTK),'proxy',str(PG/'postgres.exe'),'-D',str(DATA)]
    assert start['argv']==expected_argv
    previous_pids=(start['wrapper_pid'],preflight['postmaster_pid'])
    snapshot=process_snapshot()
    if not [row for row in snapshot if row['pid'] in previous_pids]:
        record_already_stopped(start,preflight)
        return
    pidfile=DATA/'postmaster.pid';raw=pidfile.read_bytes();lines=raw.decode().splitlines()
    postmaster=int(lines[0]);started=int(lines[2]);wrapper=start['wrapper_pid']
    assert postmaster==preflight['postmaster_pid'] and postmaster!=wrapper
    assert Path(lines[1]).resolve()==DATA.resolve() and int(lines[3])==PORT
    k=kernel_api();handles=[]
    try:
        wrapper_handle,wrapper_identity=identity(k,wrapper,RTK);handles.append(wrapper_handle)
        server_handle,server_identity=identity(k,postmaster,PG/'postgres.exe');handles.append(server_handle)
        assert parent_pid(postmaster)==wrapper
        assert wrapper_identity['created_epoch_seconds']<=server_identity['created_epoch_seconds']
        assert abs(server_identity['created_epoch_seconds']-started)<=5
        import psycopg
        with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',
                autocommit=True,connect_timeout=3) as conn:
            values=conn.execute("SELECT version(),current_setting('data_directory'),current_setting('port'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes'),extract(epoch FROM pg_postmaster_start_time())").fetchone()
            active=conn.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
            prepared=conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
            databases=[r[0] for r in conn.execute('SELECT datname FROM pg_database ORDER BY datname')]
            save('previous-cluster-sql-before.json',dict(values=values,other_clients=active,
                prepared_transactions=prepared,databases=databases,postmaster_pid=postmaster))
            assert values[0].startswith('PostgreSQL 16.15,')
            assert Path(values[1]).resolve()==DATA.resolve() and values[2]==str(PORT)
            # pidfile records integer process start; SQL records postmaster startup
            # after initialization. Match the existing five-second OS identity bound.
            assert values[3:6]==('on','on','on') and abs(float(values[6])-started)<=5
            assert not active and not prepared
        assert pidfile.read_bytes()==raw
        save('previous-cluster-retirement-intent.json',dict(state='OWNED_CLUSTER_VERIFIED_BEFORE_FAST_STOP',
            previous_campaign=PREVIOUS.name,workspace=str(WORK),data_directory=str(DATA),port=PORT,
            wrapper=wrapper_identity,postmaster=server_identity,postmaster_pidfile_sha256=sha256(raw),
            foreign_processes_targeted=False,databases_to_drop=[],workspace_removal=False))
        command('previous-cluster-fast-stop',[PG/'pg_ctl.exe','-D',DATA,'-m','fast','-w','-t','60','stop'])
        for handle in (server_handle,wrapper_handle):
            wait=k.WaitForSingleObject(handle,15000)
            if wait==0xFFFFFFFF:raise ctypes.WinError(ctypes.get_last_error())
            assert wait==0, 'Verified owned PostgreSQL process failed to exit'
        confirm_port_free()
        assert not pidfile.exists()
        verify_scope()
        oldlog=stable_previous_log()
        save('previous-cluster-retirement.json',dict(state='PASS',previous_campaign=PREVIOUS.name,
            workspace=str(WORK),data_directory=str(DATA),port=PORT,port_closed=True,
            postmaster_pid_file_absent=True,wrapper=wrapper_identity,postmaster=server_identity,
            verified_owned_processes_exited=True,previous_log=oldlog,
            previous_start_receipt_sha256=sha256((PREVIOUS/'postgresql-start.json').read_bytes()),
            previous_preflight_sha256=sha256((PREVIOUS/'postgresql-preflight.json').read_bytes()),
            application_tests_executed=False,runtime_reinstalled=False,databases_dropped=[],
            workspace_removed=False,foreign_processes_terminated=False,
            old_final_logs_closed_before_prior_evidence_snapshot=True))
        print('PREVIOUS_OWNED_CLUSTER_STOPPED_PRESERVED',flush=True)
    finally:
        for handle in reversed(handles):k.CloseHandle(handle)


if __name__=='__main__':main()

