"""Complete the existing preparation tail without restarting or installing anything."""
import datetime as dt
import json
from pathlib import Path
import sys

EVIDENCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVIDENCE))
from native_support import DATA, GIB, PORT, PYTHON, SHA, TREE, command, integrity, resources, save, sha256


def main():
    name = 'invocation-stage-tail-completion.json'
    absent = [name, 'evaluation-seal.json', 'invocation-formal.json', 'STOP.json',
              'audit-toolchain.json', 'interpreters.command.json', 'interpreters.log',
              'interpreter-base-location.json', 'interpreter-probe-primary.json',
              'interpreter-probe-legacy_base.json', 'interpreter-preflight.json',
              'python-environment.json', 'base-python-environment.json',
              'dependency-files.json', 'integrity-ready.json', 'native-preflight.json',
              'environment-ready.json', 'audit-toolchain-retained-output.json']
    assert not [item for item in absent if (EVIDENCE / item).exists()]
    previous = json.loads((EVIDENCE / 'invocation-stage-recovery.json').read_text())
    assert previous['state'] == 'FAILED' and previous['error_type'] == 'AssertionError'
    assert previous['application_tests_executed'] is False and PORT == 35490
    raw = (EVIDENCE / 'audit-toolchain-recovery.log').read_bytes()
    packages = json.loads(raw.decode('utf-8-sig'))
    assert any(row['name'].lower().replace('_', '-') == 'pip-audit' for row in packages)
    current = resources()
    assert current['physical_available'] >= 2 * GIB and current['disk_available'] >= GIB
    info = {'state': 'RUNNING', 'step': 'stage-tail-completion', 'utc_started': current['utc'],
            'preparation_only': True, 'application_tests_executed': False, 'wsl_invoked': False,
            'prior_failed_invocation': 'invocation-stage-recovery.json'}
    save(name, info)
    try:
        import psycopg
        prior = json.loads((EVIDENCE / 'postgresql-preflight.json').read_text())
        assert prior['state'] == 'PASS' and prior['same_cluster_restarted_without_initdb'] is True
        assert int((DATA / 'postmaster.pid').read_text().splitlines()[0]) == prior['postmaster_pid']
        with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
            values = conn.execute("SELECT current_setting('data_directory'),current_setting('port'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
            assert Path(values[0]).resolve() == DATA.resolve() and values[1:] == (str(PORT), 'on', 'on', 'on')
            assert [row[0] for row in conn.execute('SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname')] == ['postgres', 'test_b9i_control']
        save('audit-toolchain.json', packages)
        save('audit-toolchain-retained-output.json', {'state': 'PASS', 'source': 'audit-toolchain-recovery.log',
            'sha256': sha256(raw), 'package_count': len(packages), 'name_normalization': 'underscore to hyphen',
            'previous_assertion_failure_preserved': True, 'new_pip_command_or_installation': False})
        command('interpreters', [PYTHON, '-B', EVIDENCE / 'interpreter_preflight.py'], cwd=TREE / 'backend')
        integrity('ready')
        save('native-preflight.json', {'state': 'PASS', 'python_and_base_private': True,
            'frontend_install': 'PASS', 'postgresql_private_durable': True, 'full_partition_total': 3331,
            'wsl_invoked': False, 'application_tests_executed': False, 'resources': resources(),
            'interruption_evidence': 'preparation-interruption.json', 'recovery_invocation': name})
        save('environment-ready.json', {'state': 'READY_FOR_SEAL', 'candidate_sha': SHA,
            'platform': 'Windows native', 'wsl_invoked': False, 'application_tests_executed': False,
            'interruption_evidence': 'preparation-interruption.json', 'recovery_invocation': name})
        info.update(state='COMPLETED', exit_code=0)
        print('NATIVE_PREPARATION_TAIL_COMPLETION_PASS', flush=True)
    except Exception as exc:
        info.update(state='FAILED', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        info.update(utc_finished=dt.datetime.now(dt.timezone.utc).isoformat(), resources_after=resources())
        save(name, info)


if __name__ == '__main__':
    main()
