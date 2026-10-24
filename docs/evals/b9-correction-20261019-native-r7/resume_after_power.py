"""Reopen the prepared native campaign after AC is connected; no tests or installs."""
import ctypes
import json
from pathlib import Path
import socket
import subprocess
import time
from native_support import EVIDENCE, WORK, DATA, PG, PORT, SHA, RTK, save, sha256, environment, resources


class Power(ctypes.Structure):
    _fields_ = [('ac', ctypes.c_byte), ('flag', ctypes.c_byte), ('percent', ctypes.c_byte),
        ('reserved', ctypes.c_byte), ('remaining_seconds', ctypes.c_uint), ('full', ctypes.c_uint)]


def main():
    power = Power()
    assert ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)) and power.ac == 1
    assert not any((EVIDENCE / n).exists() for n in ('evaluation-seal.json', 'invocation-formal.json', 'STOP.json'))
    closure = json.loads((EVIDENCE / 'preparation-native-closure.json').read_text(encoding='utf-8'))
    assert closure['state'] == 'PASS_PREPARATION_AUXILIARIES_CLOSED'
    assert DATA.resolve() == WORK.resolve() / 'pgdata' and not (DATA / 'postmaster.pid').exists()
    with socket.socket() as check:
        check.bind(('127.0.0.1', PORT))
    history = EVIDENCE / 'preparation-history'
    assert not history.exists()
    history.mkdir()
    names = ['awake-request', 'resource-observer', 'resource-observer-control.json',
        'resource-observer-closure.json', 'postgresql-start.json', 'postgresql-preflight.json',
        'clock-preflight.json', 'clock-observation.json', 'invocation-clock.json', 'invocation-clock.log',
        'invocation-validate.json', 'invocation-validate.log', 'launcher-validation.json',
        'native-preflight.json', 'environment-ready.json']
    names += [p.name for p in EVIDENCE.glob('postgresql-start-*') if p.is_file()]
    names = list(dict.fromkeys(names))
    preserved = {}
    for name in names:
        source, target = EVIDENCE / name, history / name
        assert source.exists() and not source.is_symlink() and not source.is_junction(), name
        assert source.resolve().is_relative_to(EVIDENCE.resolve())
        assert target.resolve().is_relative_to(EVIDENCE.resolve()) and not target.exists()
        files = [source] if source.is_file() else [p for p in source.rglob('*') if p.is_file()]
        records = {p.relative_to(EVIDENCE).as_posix(): sha256(p.read_bytes()) for p in files}
        source.rename(target)
        assert all(sha256((history / relative).read_bytes()) == value for relative, value in records.items())
        preserved.update(records)
    save('preparation-history-manifest.json', {'state': 'PRESERVED_UNCHANGED',
        'files': preserved, 'archive_directory': 'preparation-history',
        'formal_tests_had_started': False, 'auxiliaries_had_been_released': True})
    argv = [str(RTK), 'proxy', str(PG / 'postgres.exe'), '-D', str(DATA)]
    with (WORK / 'postgresql.log').open('ab') as log:
        server = subprocess.Popen(argv, cwd=WORK, env=environment(), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
    save('postgresql-start.json', {'mode': 'Owned clean same-cluster restart for the first formal r7 invocation',
        'argv': argv, 'wrapper_pid': server.pid, 'port': PORT, 'data_directory': str(DATA),
        'previous_preparation': 'preparation-history/postgresql-start.json'})
    import psycopg
    started = time.monotonic()
    while True:
        assert server.poll() is None, 'Owned PostgreSQL exited before readiness'
        try:
            conn = psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres',
                autocommit=True, connect_timeout=2)
            break
        except psycopg.OperationalError:
            if time.monotonic() - started > 120:
                raise
            time.sleep(.5)
    with conn:
        values = conn.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
        assert values[0].startswith('PostgreSQL 16.15,') and Path(values[1]).resolve() == DATA.resolve()
        assert values[2:] == ('on', 'on', 'on')
        names = [row[0] for row in conn.execute('SELECT datname FROM pg_database')]
        assert 'test_b9i_control' in names and 'test_b9i_full_general_remainder' not in names
        assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
        assert not conn.execute("SELECT pid FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type='client backend'").fetchall()
    save('postgresql-preflight.json', {'state': 'PASS', 'values': values, 'port': PORT,
        'postmaster_pid': int((DATA / 'postmaster.pid').read_text().splitlines()[0]),
        'private_cluster': True, 'existing_databases': names, 'fresh_remainder_database_absent': True})
    save('native-preflight.json', {'state': 'PASS', 'python_and_base_private': True,
        'frontend_install': 'REFERENCED_FROZEN_INTACT', 'postgresql_private_durable': True,
        'full_partition_total': 3331, 'wsl_invoked': False, 'application_tests_executed': False,
        'resources': resources(), 'runtime_reference': 'prepared-runtime-references.json',
        'current_live_input_equivalence_required_before_seal': True})
    save('environment-ready.json', {'state': 'READY_FOR_SEAL', 'candidate_sha': SHA,
        'platform': 'Windows native', 'wsl_invoked': False, 'application_tests_executed': False,
        'runtime_reinstalled': False, 'runtime_reference': 'prepared-runtime-references.json'})
    save('formal-preparation-resumption.json', {'state': 'SAME_RUNTIME_READY_FOR_FRESH_CONTROLS',
        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_reply': 'Ya conectado y mantendré la tapa abierta',
        'power': {n: getattr(power, n) for n, _ in power._fields_},
        'candidate_tree': SHA, 'formal_tests_started': False, 'installs_or_exports_repeated': False,
        'retained_PASS': 2483, 'retained_SKIP': 2, 'remaining_cases': 728,
        'prepared_auxiliaries_released_before_fresh_formal_auxiliaries': True,
        'adaptive_formal_renewal': False, 'maximum_formal_awake_seconds': 43200,
        'preparation_history_manifest': 'preparation-history-manifest.json'})
    print('POWER_CONFIRMED_SAME_RUNTIME_READY_NO_TESTS', flush=True)


if __name__ == '__main__':
    main()
