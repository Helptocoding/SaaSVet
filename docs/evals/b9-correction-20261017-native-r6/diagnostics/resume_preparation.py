"""Resume only the interrupted, unsealed native preparation tail; never run tests."""
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

EVIDENCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVIDENCE))
from native_support import (DATA, GIB, PG, PORT, PYTHON, RTK, SHA, TREE, WORK,
                            command, environment, integrity, resources, run, save, sha256)

ARCHIVE = EVIDENCE / 'diagnostics/preparation-interruption'
EXPECTED_WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
KNOWN_BOOT = '2026-10-18T11:52:49.5000000Z'
INVOCATION = 'invocation-stage-recovery.json'


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def read(name):
    return json.loads((EVIDENCE / name).read_text(encoding='utf-8'))


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def archive(path, name):
    target = ARCHIVE / name
    assert path.is_file() and not target.exists(), str(target)
    raw = path.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(raw)
    assert target.read_bytes() == raw
    return {'original': str(path), 'archive': target.relative_to(EVIDENCE).as_posix(),
            'sha256': sha256(raw), 'bytes': len(raw)}


def host_processes(old_pid):
    # The current recovery ancestry and the separately owned observers are allowed.
    script = r"""
$ErrorActionPreference='Stop'
$all=@(Get-CimInstance Win32_Process)
$ancestors=@()
foreach($seed in @([int]$PID,RECOVERY_PID)) {
  $cursor=$seed
  while($cursor -and ($ancestors -notcontains $cursor)) {
    $ancestors+=@($cursor)
    $row=$all | Where-Object ProcessId -eq $cursor | Select-Object -First 1
    if($null -eq $row){break}; $cursor=[int]$row.ParentProcessId
  }
}
$work='WORK_LITERAL'; $evidence='EVIDENCE_LITERAL'
$owned=@($all | Where-Object {
  $cmd=[string]$_.CommandLine; $exe=[string]$_.ExecutablePath
  (($cmd.IndexOf($work,[StringComparison]::OrdinalIgnoreCase) -ge 0) -or
   ($exe.IndexOf($work,[StringComparison]::OrdinalIgnoreCase) -ge 0) -or
   (($cmd.IndexOf($evidence,[StringComparison]::OrdinalIgnoreCase) -ge 0) -and
    ($cmd -match 'prepare_native\.py|interpreter_preflight\.py|resume_preparation\.py'))) -and
  ($ancestors -notcontains [int]$_.ProcessId)
})
function Describe($rows) {
  @($rows | ForEach-Object { [pscustomobject]@{
    pid=[int]$_.ProcessId; parent_pid=[int]$_.ParentProcessId
    executable=$_.ExecutablePath; command_line=$_.CommandLine
    created_utc=$_.CreationDate.ToUniversalTime().ToString('o')
  } })
}
$boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
[pscustomobject]@{boot_utc=$boot; recovery_ancestry=$ancestors;
  owned_remaining=@(Describe $owned);
  old_postmaster=@(Describe @($all | Where-Object ProcessId -eq OLD_PID))
} | ConvertTo-Json -Depth 6 -Compress
"""
    script = (script.replace('RECOVERY_PID', str(os.getpid()))
              .replace('OLD_PID', str(old_pid))
              .replace('WORK_LITERAL', str(WORK).replace("'", "''"))
              .replace('EVIDENCE_LITERAL', str(EVIDENCE).replace("'", "''")))
    result = json.loads(run('powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                            '-Command', script).decode('utf-8-sig'))
    assert abs(timestamp(result['boot_utc']) - timestamp(KNOWN_BOOT)) < 1
    assert not result['owned_remaining'], 'A previous owned preparation process remains'
    return result


def assert_port_free():
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', PORT)) != 0, 'Private port already accepts connections'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', PORT))


def verify_preconditions():
    assert os.name == 'nt' and PORT == 35490
    assert WORK.resolve() == EXPECTED_WORK and WORK.is_dir()
    for path in (WORK, DATA, TREE):
        assert path.is_dir() and not path.is_symlink() and not path.is_junction()
    assert DATA.resolve() == WORK.resolve() / 'pgdata'
    assert TREE.resolve() == WORK.resolve() / 'src'
    assert not PG.resolve().is_relative_to(WORK.resolve())
    absent = ['evaluation-seal.json', 'invocation-formal.json', 'STOP.json',
              'technical-completion.json', INVOCATION, 'preparation-interruption.json',
              'audit-toolchain.json', 'interpreters.command.json', 'interpreters.log',
              'interpreter-base-location.json', 'interpreter-probe-primary.json',
              'interpreter-probe-legacy_base.json', 'interpreter-preflight.json',
              'python-environment.json', 'base-python-environment.json',
              'dependency-files.json', 'integrity-ready.json', 'native-preflight.json',
              'environment-ready.json', 'audit-toolchain-recovery.command.json',
              'audit-toolchain-recovery.log']
    assert not [name for name in absent if (EVIDENCE / name).exists()], 'Tail already has evidence'
    assert not list((EVIDENCE / 'blocks').glob('*.command.json')), 'Formal blocks exist'
    assembly = read('assembly.json')
    assert assembly['candidate_sha'] == SHA and assembly['port'] == PORT
    assert Path(assembly['workspace']).resolve() == WORK.resolve()
    assert read('invocation-stage.json')['state'] == 'RUNNING'
    for label in ('initdb', 'discovery', 'frontend-install', 'audit-venv', 'audit-tool-install'):
        receipt = read(label + '.command.json')
        assert receipt['state'] == 'COMPLETED' and receipt['exit_code'] == 0, label
        assert receipt['preparation_only'] is True
    assert read('frontend-layout.json')['state'] == 'PASS'
    discovery = read('discovery.json')
    assert discovery['candidate_sha'] == SHA and discovery['tests_executed'] is False
    assert discovery['counts'] == dict(directed=87, full=3331, b0=17, b3=42, b4=68, b5=37)
    assert not any(discovery['loader_errors'].values())
    assert not any(discovery['duplicates'].values())
    assert not discovery['missing_directed'] and not discovery['unexpected_directed']
    assert read('full-partition.json')['candidate_tree'] == SHA
    for name in ('postgresql.conf', 'pg_hba.conf'):
        assert (DATA / name).read_bytes() == (EVIDENCE / 'private-postgresql' / name).read_bytes()
    assert (DATA / 'PG_VERSION').read_text().strip() == '16'
    assert read('postgresql-start.json')['port'] == PORT
    assert Path(read('postgresql-start.json')['data_directory']).resolve() == DATA.resolve()
    old = read('postgresql-preflight.json')
    assert old['state'] == 'PASS' and old['private_cluster'] is True and old['port'] == PORT
    assert Path(old['values'][1]).resolve() == DATA.resolve() and old['values'][2:] == ['on'] * 3
    assert (WORK / 'audit-venv/Scripts/python.exe').is_file()
    current = resources()
    assert current['physical_available'] >= 2 * GIB and current['disk_available'] >= GIB
    return old, current


def start_same_cluster(old, saved_pidfile, initial_snapshot):
    import psycopg
    argv = [str(RTK), 'proxy', str(PG / 'postgres.exe'), '-D', str(DATA)]
    for attempt in (1, 2):
        assert_port_free()
        log_path = WORK / 'postgresql.log'
        if attempt == 2:
            archive(log_path, 'postgresql-recovery-attempt-1.log')
        with log_path.open('wb') as log:
            server = subprocess.Popen(argv, cwd=WORK, env=environment(),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
        ownership = {'mode': 'Owned foreground server under RTK; same cluster after preparation reboot',
            'argv': argv, 'wrapper_pid': server.pid, 'port': PORT, 'data_directory': str(DATA),
            'utc_started': utc(), 'attempt': attempt, 'log': str(log_path),
            'log_generation': 'NEW_AFTER_ARCHIVING_PRE_REBOOT_LOG',
            'interruption_evidence': 'preparation-interruption.json'}
        save('postgresql-stage-recovery-start-' + str(attempt) + '.json', ownership)
        save('postgresql-start.json', ownership)  # Cleanup's canonical ownership reference.
        started = time.monotonic()
        while server.poll() is None:
            try:
                conn = psycopg.connect(host='127.0.0.1', port=PORT, user='b9e',
                    dbname='postgres', autocommit=True, connect_timeout=2)
                return server, conn
            except psycopg.OperationalError:
                if time.monotonic() - started > 60:
                    raise RuntimeError('Same private cluster did not become ready within 60 seconds')
                time.sleep(.5)
        save('postgresql-stage-recovery-exit-' + str(attempt) + '.json',
             {'exit_code': server.returncode, 'utc': utc(), 'wrapper_pid': server.pid})
        log_bytes = log_path.read_bytes()
        assert attempt == 1 and saved_pidfile is not None
        assert b'postmaster.pid' in log_bytes and b'lock file' in log_bytes.lower(), 'PG exit unrelated to stale lock'
        pidfile = DATA / 'postmaster.pid'
        assert pidfile.is_file() and sha256(pidfile.read_bytes()) == saved_pidfile['sha256']
        lines = pidfile.read_text(encoding='utf-8').splitlines()
        assert int(lines[0]) == old['postmaster_pid'] and Path(lines[1]).resolve() == DATA.resolve()
        assert int(lines[3]) == PORT and float(lines[2]) < timestamp(initial_snapshot['boot_utc'])
        snapshot = host_processes(old['postmaster_pid'])
        for row in snapshot['old_postmaster']:
            assert timestamp(row['created_utc']) >= timestamp(snapshot['boot_utc'])
            assert Path(row['executable'] or '').resolve() != (PG / 'postgres.exe').resolve()
            assert str(DATA).lower() not in (row['command_line'] or '').lower()
        assert_port_free()
        save('postgresql-stale-lock-decision.json', {'state': 'VERIFIED_STALE_PRE_REBOOT',
            'pid_file': str(pidfile), 'preserved_file': saved_pidfile, 'host': snapshot,
            'pid_reused_or_absent_after_boot': True, 'data_directory': str(DATA), 'port': PORT,
            'only_this_lock_removed': True, 'cluster_reinitialized': False})
        assert pidfile.resolve() == WORK.resolve() / 'pgdata/postmaster.pid'
        pidfile.unlink()
    raise AssertionError('Unreachable')


def resume():
    old, before = verify_preconditions()
    snapshot = host_processes(old['postmaster_pid'])
    assert_port_free()
    files = {}
    for name in ('invocation-stage.json', 'postgresql-start.json', 'postgresql-preflight.json'):
        files[name] = archive(EVIDENCE / name, name)
    files['postgresql.log'] = archive(WORK / 'postgresql.log', 'postgresql-before-reboot.log')
    saved_pidfile = None
    if (DATA / 'postmaster.pid').exists():
        saved_pidfile = archive(DATA / 'postmaster.pid', 'postmaster-before-recovery.pid')
        files['postmaster.pid'] = saved_pidfile
    interruption = {'state': 'PREPARATION_INTERRUPTED_BY_CONFIRMED_WINDOWS_REBOOT',
        'observed_utc': utc(), 'known_boot_utc': KNOWN_BOOT, 'host': snapshot,
        'last_auxiliary_heartbeat_utc': '2026-10-18T11:52:29Z',
        'original_stage_exit': 'UNKNOWN', 'original_stage_completion_time': None,
        'audit_tool_install': 'COMPLETED_EXIT_0_BEFORE_REBOOT', 'preserved_files': files,
        'candidate_sha': SHA, 'application_tests_executed': False, 'formal_invocation_exists': False,
        'prior_recovery_guard_attempt': {'exit_code': 1, 'postgresql_started': False,
            'receipts_written': False, 'cause': 'CIM collector and its RTK wrapper matched their own command lines',
            'correction': 'Exclude ancestry union of the PowerShell collector and recovery Python',
            'source_sha256_before': '0cf18f6e2ddba3e0a2ee485c495113f3e3d02b35e016565d7d4000b40ee9401d',
            'source_sha256_current': sha256(Path(__file__).read_bytes()),
            'retained_output': 'diagnostics/preparation-interruption/recovery-first-guard.log'},
        'reinitialization_or_dependency_installation_permitted': False, 'resources': before}
    save('preparation-interruption.json', interruption)
    previous = read('invocation-stage.json')
    previous.update(state='INTERRUPTED_UNKNOWN_EXIT', interruption_observed_utc=utc(),
                    known_boot_utc=KNOWN_BOOT, original_receipt=files['invocation-stage.json'],
                    interruption_evidence='preparation-interruption.json')
    save('invocation-stage.json', previous)
    info = {'state': 'RUNNING', 'step': 'stage-tail-recovery', 'utc_started': utc(),
        'pid': os.getpid(), 'argv': sys.argv, 'preparation_only': True,
        'application_tests_executed': False, 'wsl_invoked': False,
        'interruption_evidence': 'preparation-interruption.json'}
    save(INVOCATION, info)
    try:
        server, conn = start_same_cluster(old, saved_pidfile, snapshot)
        with conn:
            values = conn.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
            assert values[0].startswith('PostgreSQL 16.15,')
            assert Path(values[1]).resolve() == DATA.resolve() and values[2:] == ('on', 'on', 'on')
            port = conn.execute("SELECT current_setting('port')").fetchone()[0]
            assert port == str(PORT)
            names = [row[0] for row in conn.execute('SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname')]
            assert names == ['postgres', 'test_b9i_control'], names
            assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
            assert not conn.execute("SELECT pid FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
        postmaster_pid = int((DATA / 'postmaster.pid').read_text().splitlines()[0])
        preflight = {'state': 'PASS', 'values': values, 'port': PORT,
            'postmaster_pid': postmaster_pid, 'private_cluster': True,
            'same_cluster_restarted_without_initdb': True, 'databases': names,
            'wrapper_pid': server.pid, 'interruption_evidence': 'preparation-interruption.json'}
        save('postgresql-stage-recovery-preflight.json', preflight)
        save('postgresql-preflight.json', preflight)
        tool_env = environment()
        tool_env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
        raw = run(WORK / 'audit-venv/Scripts/python.exe', '-m', 'pip', 'list', '--format=json', env=tool_env)
        log = EVIDENCE / 'audit-toolchain-recovery.log'
        with log.open('xb') as stream:
            stream.write(raw)
        packages = json.loads(raw.decode('utf-8-sig'))
        assert any(row['name'].lower() == 'pip-audit' for row in packages)
        save('audit-toolchain-recovery.command.json', {'state': 'COMPLETED', 'exit_code': 0,
            'argv': [str(RTK), 'proxy', str(WORK / 'audit-venv/Scripts/python.exe'),
                     '-m', 'pip', 'list', '--format=json'], 'preparation_only': True,
            'installation_performed': False, 'pip_version_check_disabled': True,
            'output_sha256': sha256(raw), 'utc_completed': utc()})
        save('audit-toolchain.json', packages)
        command('interpreters', [PYTHON, '-B', EVIDENCE / 'interpreter_preflight.py'], cwd=TREE / 'backend')
        integrity('ready')
        save('native-preflight.json', {'state': 'PASS', 'python_and_base_private': True,
            'frontend_install': 'PASS', 'postgresql_private_durable': True,
            'full_partition_total': 3331, 'wsl_invoked': False, 'application_tests_executed': False,
            'resources': resources(), 'interruption_evidence': 'preparation-interruption.json',
            'recovery_invocation': INVOCATION})
        save('environment-ready.json', {'state': 'READY_FOR_SEAL', 'candidate_sha': SHA,
            'platform': 'Windows native', 'wsl_invoked': False, 'application_tests_executed': False,
            'interruption_evidence': 'preparation-interruption.json', 'recovery_invocation': INVOCATION})
        info.update(state='COMPLETED', exit_code=0, utc_completed=utc(), resources_after=resources())
        save(INVOCATION, info)
        print('NATIVE_PREPARATION_TAIL_RECOVERY_PASS', flush=True)
    except Exception as exc:
        info.update(state='FAILED', utc_failed=utc(), error_type=type(exc).__name__,
                    error=str(exc), resources_after=resources())
        save(INVOCATION, info)
        raise


if __name__ == '__main__':
    resume()
