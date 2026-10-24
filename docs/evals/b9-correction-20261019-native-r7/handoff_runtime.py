"""Restart only the intact owned disposable cluster after the recorded Windows reboot."""
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from native_support import EVIDENCE, WORK, DATA, PG, PORT, SHA, RTK, save, sha256, environment, resources, integrity


def alive(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if handle:
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return True
    assert ctypes.get_last_error() in (87, 1168), ctypes.get_last_error()
    return False


def main():
    assert WORK.resolve() == Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6').resolve()
    assert not WORK.is_symlink() and not WORK.is_junction()
    assert not (EVIDENCE / 'postgresql-start.json').exists()
    for name in ('postgresql.conf', 'pg_hba.conf'):
        assert (DATA / name).read_bytes() == (EVIDENCE / 'private-postgresql' / name).read_bytes()
    with socket.socket() as check:
        check.bind(('127.0.0.1', PORT))
    pidfile = DATA / 'postmaster.pid'
    stale = pidfile.read_bytes() if pidfile.exists() else None
    if stale:
        lines = stale.decode().splitlines()
        pid, epoch = int(lines[0]), int(lines[2])
        assert Path(lines[1]).resolve() == DATA.resolve() and int(lines[3]) == PORT
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        boot_lower_bound = time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000
        assert epoch < boot_lower_bound - 60 and not alive(pid)
        (EVIDENCE / 'stale-postmaster.pid').write_bytes(stale)
        save('stale-lock-validation.json', {'state': 'CONFIRMED_PREBOOT_OWNED_LOCK',
            'pid': pid, 'pid_absent': True, 'sha256': sha256(stale),
            'start_epoch': epoch, 'estimated_boot_epoch': boot_lower_bound,
            'data_directory': str(DATA), 'port': PORT, 'foreign_processes_targeted': False})
    oldlog = WORK / 'postgresql.log'
    if oldlog.exists():
        (EVIDENCE / 'postgresql-before-handoff.log').write_bytes(oldlog.read_bytes())
    argv = [str(RTK), 'proxy', str(PG / 'postgres.exe'), '-D', str(DATA)]
    server = None
    for attempt in (1, 2):
        logfile = EVIDENCE / ('postgresql-start-' + str(attempt) + '.log')
        with logfile.open('xb') as log:
            server = subprocess.Popen(argv, cwd=WORK, env=environment(), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
        save('postgresql-start-attempt-' + str(attempt) + '.json', {'argv': argv,
            'wrapper_pid': server.pid, 'port': PORT, 'data_directory': str(DATA)})
        import psycopg
        started = time.monotonic()
        while time.monotonic() - started < 60:
            if server.poll() is not None:
                break
            try:
                conn = psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres',
                    autocommit=True, connect_timeout=2)
                break
            except psycopg.OperationalError:
                time.sleep(.5)
        else:
            raise RuntimeError('Owned PostgreSQL readiness timeout; no foreign process targeted')
        if server.poll() is None:
            break
        failure = logfile.read_text(encoding='utf-8', errors='replace')
        if attempt != 1 or not stale or 'postmaster.pid' not in failure or 'lock file' not in failure.lower():
            raise RuntimeError('Owned PostgreSQL start failed; retained log')
        assert pidfile.read_bytes() == stale and not alive(int(stale.decode().splitlines()[0]))
        assert pidfile.resolve().is_relative_to(WORK.resolve())
        pidfile.unlink()
        save('stale-lock-removal.json', {'state': 'REMOVED_ONLY_PROVEN_OWNED_PREBOOT_LOCK',
            'path': str(pidfile), 'sha256': sha256(stale), 'after_specific_postgres_lock_rejection': True})
    assert server is not None and server.poll() is None
    with conn:
        values = conn.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
        assert values[0].startswith('PostgreSQL 16.15,') and Path(values[1]).resolve() == DATA.resolve()
        assert values[2:] == ('on', 'on', 'on')
        names = [row[0] for row in conn.execute('SELECT datname FROM pg_database')]
        assert 'test_b9i_control' in names and 'test_b9i_full_general_remainder' not in names
        assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
        assert not conn.execute('SELECT pid FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type=\'client backend\'').fetchall()
    save('postgresql-start.json', {'mode': 'Owned same-cluster handoff under RTK', 'argv': argv,
        'wrapper_pid': server.pid, 'port': PORT, 'data_directory': str(DATA),
        'previous_invocation_resumed': False, 'same_disposable_cluster': True})
    save('postgresql-preflight.json', {'state': 'PASS', 'values': values, 'port': PORT,
        'postmaster_pid': int(pidfile.read_text().splitlines()[0]), 'private_cluster': True,
        'existing_databases': names, 'fresh_remainder_database_absent': True})
    integrity('handoff')
    save('native-preflight.json', {'state': 'PASS', 'python_and_base_private': True,
        'frontend_install': 'REFERENCED_FROZEN_INTACT', 'postgresql_private_durable': True,
        'full_partition_total': 3331, 'wsl_invoked': False, 'application_tests_executed': False,
        'resources': resources(), 'runtime_reference': 'prepared-runtime-references.json',
        'current_live_input_equivalence_required_before_seal': True})
    save('environment-ready.json', {'state': 'READY_FOR_SEAL', 'candidate_sha': SHA,
        'platform': 'Windows native', 'wsl_invoked': False, 'application_tests_executed': False,
        'runtime_reinstalled': False, 'runtime_reference': 'prepared-runtime-references.json'})
    print('SAME_CLUSTER_HANDOFF_PASS_NO_TESTS', flush=True)


if __name__ == '__main__':
    main()
