"""Start one fresh r12 PostgreSQL owner after a verified, preserved r11 retirement."""
import json
from pathlib import Path
import subprocess
import time
from native_support import EVIDENCE, WORK, DATA, PG, PORT, SHA, RTK, save, sha256, environment, resources, integrity
from retire_previous_cluster import verify_scope, confirm_port_free, stable_previous_log, kernel_api, identity, parent_pid, confirm_previous_absence

FRESH_DB='test_b9i_full_general_remainder_r12'
EXPECTED_SHA='f5f18d71847a46d66644775cd90d30268f072e3b'


def main():
    verify_scope()
    assert SHA==EXPECTED_SHA
    assert EVIDENCE.name=='b9-correction-20261020-native-r12'
    assert Path(json.loads((EVIDENCE/'assembly.json').read_text(encoding='utf-8'))['workspace']).resolve()==WORK.resolve()
    assert not (EVIDENCE/'postgresql-start.json').exists(), 'Refusing duplicate owned server invocation'
    assert not (EVIDENCE/'postgresql-start-attempt-1.json').exists(), 'No automatic start retry'
    retirement_path=EVIDENCE/'previous-cluster-retirement.json'
    retirement=json.loads(retirement_path.read_text(encoding='utf-8'))
    assert retirement['state']=='PASS'
    if retirement.get('mode')=='ALREADY_STOPPED_VERIFIED_ABSENT':
        assert retirement['owned_processes_currently_absent'] is True
        assert retirement['verified_owned_processes_exited'] is False
        assert retirement['owned_process_exit_observed'] is False
        assert retirement['clean_shutdown_observed'] is False
        assert retirement['stop_command_executed'] is False
        confirm_previous_absence(retirement['previous_wrapper_pid'],retirement['previous_postmaster_pid'])
    else:
        assert retirement['verified_owned_processes_exited'] is True
    assert retirement['port_closed'] and retirement['postmaster_pid_file_absent']
    assert retirement['port']==PORT and Path(retirement['data_directory']).resolve()==DATA.resolve()
    assert retirement['databases_dropped']==[] and retirement['workspace_removed'] is False
    assert stable_previous_log()==retirement['previous_log'], 'Previous closed log changed after retirement'
    confirm_port_free()
    pidfile=DATA/'postmaster.pid'
    assert not pidfile.exists(), 'No stale-lock removal permitted in this clean handoff'
    manifest=json.loads((EVIDENCE/'candidate-sources.json').read_text(encoding='utf-8'))
    assert manifest['candidate_sha']==SHA
    integrity('handoff')
    argv=[str(RTK),'proxy',str(PG/'postgres.exe'),'-D',str(DATA)]
    logpath=EVIDENCE/'postgresql-start-1.log'
    with logpath.open('xb') as log:
        server=subprocess.Popen(argv,cwd=WORK,env=environment(),stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
    info=dict(mode='Owned same-cluster handoff after verified r11 retirement under RTK',
        argv=argv,wrapper_pid=server.pid,port=PORT,data_directory=str(DATA),
        previous_invocation_resumed=False,same_disposable_cluster=True,
        previous_cluster_retirement='previous-cluster-retirement.json',
        previous_cluster_retirement_sha256=sha256(retirement_path.read_bytes()),
        state='STARTED_PENDING_READINESS',attempt=1,maximum_start_attempts=1)
    save('postgresql-start-attempt-1.json',info)
    save('postgresql-start.json',info)
    import psycopg
    connection=None;started=time.monotonic()
    while time.monotonic()-started<120:
        if server.poll() is not None:
            raise RuntimeError('Owned r12 PostgreSQL start failed; retained exact log; no retry')
        try:
            connection=psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',
                autocommit=True,connect_timeout=2)
            break
        except psycopg.OperationalError:
            time.sleep(.5)
    assert connection is not None, 'Owned r12 PostgreSQL readiness timeout; no retry'
    assert server.poll() is None
    lines=pidfile.read_text(encoding='utf-8').splitlines()
    postmaster=int(lines[0]);start_epoch=int(lines[2])
    assert Path(lines[1]).resolve()==DATA.resolve() and int(lines[3])==PORT
    k=kernel_api();handles=[]
    try:
        handle,wrapper_identity=identity(k,server.pid,RTK);handles.append(handle)
        handle,server_identity=identity(k,postmaster,PG/'postgres.exe');handles.append(handle)
        assert parent_pid(postmaster)==server.pid
        assert wrapper_identity['created_epoch_seconds']<=server_identity['created_epoch_seconds']
        assert abs(server_identity['created_epoch_seconds']-start_epoch)<=5
        with connection:
            values=connection.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
            actual_port,sql_epoch=connection.execute("SELECT current_setting('port'),extract(epoch FROM pg_postmaster_start_time())").fetchone()
            names=[row[0] for row in connection.execute('SELECT datname FROM pg_database ORDER BY datname')]
            prepared=connection.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
            active=connection.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type='client backend' ORDER BY pid").fetchall()
            save('postgresql-sql-before-formal.json',dict(values=values,actual_port=actual_port,
                sql_postmaster_epoch=sql_epoch,existing_databases=names,prepared_transactions=prepared,
                other_clients=active,postmaster=server_identity,wrapper=wrapper_identity))
            assert values[0].startswith('PostgreSQL 16.15,') and Path(values[1]).resolve()==DATA.resolve()
            assert values[2:]==('on','on','on')
            assert actual_port==str(PORT) and abs(float(sql_epoch)-start_epoch)<=5
            assert 'test_b9i_control' in names and FRESH_DB not in names
            assert not prepared and not active
    finally:
        if connection is not None:connection.close()
        for handle in reversed(handles):k.CloseHandle(handle)
    assert stable_previous_log()==retirement['previous_log'], 'New startup changed closed r11 server log'
    info.update(state='PASS_READY',postmaster_pid=postmaster,postmaster=server_identity,wrapper=wrapper_identity)
    save('postgresql-start.json',info)
    save('postgresql-preflight.json',dict(state='PASS',values=values,port=PORT,postmaster_pid=postmaster,
        private_cluster=True,existing_databases=names,fresh_remainder_database_absent=True,
        fresh_remainder_database=FRESH_DB,previous_cluster_retired=True))
    save('native-preflight.json',dict(state='PASS',python_and_base_private=True,
        frontend_install='REFERENCED_FROZEN_INTACT',postgresql_private_durable=True,
        full_partition_total=3331,wsl_invoked=False,application_tests_executed=False,
        resources=resources(),runtime_reference='prepared-runtime-references.json',
        current_live_input_equivalence_required_before_seal=True,previous_cluster_retired=True,
        candidate_sources_verified_before_owned_server_start=True))
    save('environment-ready.json',dict(state='READY_FOR_SEAL',candidate_sha=SHA,platform='Windows native',
        wsl_invoked=False,application_tests_executed=False,runtime_reinstalled=False,
        runtime_reference='prepared-runtime-references.json',previous_invocation_resumed=False))
    print('SAME_CLUSTER_R12_HANDOFF_PASS_NO_TESTS',flush=True)


if __name__=='__main__':main()

