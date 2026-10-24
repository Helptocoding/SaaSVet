"""Complete readiness after PostgreSQL crash recovery outlasted the initial 60s probe."""
import json
import time
from pathlib import Path
import psycopg
from native_support import EVIDENCE, WORK, DATA, PORT, SHA, save, resources, integrity

assert not (EVIDENCE / 'postgresql-start.json').exists()
start = json.loads((EVIDENCE / 'postgresql-start-attempt-1.json').read_text(encoding='utf-8'))
assert start['port'] == PORT and Path(start['data_directory']).resolve() == DATA.resolve()
assert DATA.resolve().is_relative_to(WORK.resolve())
save('handoff-initial-probe-timeout.json', {'state': 'PREPARATION_READINESS_TIMEOUT',
    'application_tests_executed': False, 'server_restarted': False,
    'cause': 'Same-cluster crash recovery exceeded initial 60 second readiness wait',
    'retained_server_log': 'postgresql-start-1.log', 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True, connect_timeout=5) as conn:
    values = conn.execute("SELECT version(),current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
    assert values[0].startswith('PostgreSQL 16.15,') and Path(values[1]).resolve() == DATA.resolve()
    assert values[2:] == ('on', 'on', 'on')
    names = [row[0] for row in conn.execute('SELECT datname FROM pg_database')]
    assert 'test_b9i_control' in names and 'test_b9i_full_general_remainder' not in names
    assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
    assert not conn.execute("SELECT pid FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type='client backend'").fetchall()
save('postgresql-start.json', dict(start, mode='Same already-started owned cluster after crash recovery',
    previous_invocation_resumed=False, same_disposable_cluster=True, server_restarted_for_completion=False))
save('postgresql-preflight.json', {'state': 'PASS', 'values': values, 'port': PORT,
    'postmaster_pid': int((DATA / 'postmaster.pid').read_text().splitlines()[0]), 'private_cluster': True,
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
print('SAME_CLUSTER_HANDOFF_COMPLETED_NO_RESTART_NO_TESTS', flush=True)
