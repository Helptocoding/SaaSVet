"""Keep the prepared runtime while releasing owned services during the external power wait."""
import ctypes
import json
import socket
import subprocess
import time
from pathlib import Path
from native_support import EVIDENCE, WORK, DATA, PG, PORT, SHA, RTK, save, sha256, environment, resources


class Power(ctypes.Structure):
    _fields_ = [('ac', ctypes.c_byte), ('flag', ctypes.c_byte), ('percent', ctypes.c_byte),
        ('reserved', ctypes.c_byte), ('remaining_seconds', ctypes.c_uint), ('full', ctypes.c_uint)]


power = Power()
assert ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power))
if power.ac == 1:
    print('AC_CONNECTED_NO_PAUSE', flush=True)
    raise SystemExit(0)
assert not (EVIDENCE / 'invocation-formal.json').exists()
assert not (EVIDENCE / 'evaluation-seal.json').exists()
assert not (EVIDENCE / 'STOP.json').exists()
for name, state in [('reuse-manifest.json', 'VALIDATED_REFERENCED_PASS'),
        ('case-resumption-validation.json', 'PASS'), ('clock-preflight.json', 'PASS'),
        ('native-preflight.json', 'PASS'), ('launcher-validation.json', 'PASS'),
        ('diagnostics/preserved-contract-checks.json', 'PASS'),
        ('diagnostics/composite-validator-checks.json', 'PASS_VALIDATOR_CHECKS')]:
    assert json.loads((EVIDENCE / name).read_text(encoding='utf-8'))['state'] == state, name
save('preparation-pause.json', {'state': 'PREPARED_WAITING_FOR_AC', 'candidate_tree': SHA,
    'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'cause': 'Windows reports battery without AC; remaining power is shorter than the pending complete stages',
    'power': {n: getattr(power, n) for n, _ in power._fields_}, 'resources': resources(),
    'retained_PASS': 2483, 'retained_expected_skips': 2, 'remaining_cases': 728,
    'reused_complete_PASS_blocks': 13, 'formal_application_tests_executed_here': False,
    'formal_invocation_started': False, 'candidate_or_dependencies_removed': False,
    'accepted_historical_evidence_limitation': True,
    'authorization': 'case-resumption-authorization.json',
    'next': 'Confirm AC, start fresh bounded auxiliaries, restart same cluster, refresh live launcher/clock checks, seal, run only 728 cases and remaining stages',
    'new_authorization_required': False, 'no_test_reruns_required': True})
assert DATA.resolve() == WORK.resolve() / 'pgdata'
preflight = json.loads((EVIDENCE / 'postgresql-preflight.json').read_text(encoding='utf-8'))
assert int((DATA / 'postmaster.pid').read_text().splitlines()[0]) == preflight['postmaster_pid']
import psycopg
with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True, connect_timeout=5) as conn:
    assert Path(conn.execute("SELECT current_setting('data_directory')").fetchone()[0]).resolve() == DATA.resolve()
    assert not conn.execute("SELECT pid FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND backend_type='client backend'").fetchall()
    assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
argv = [str(RTK), 'proxy', str(PG / 'pg_ctl.exe'), '-D', str(DATA), 'stop', '-m', 'fast', '-w', '-t', '30']
with (EVIDENCE / 'preparation-postgresql-stop.log').open('xb') as stream:
    result = subprocess.run(argv, env=environment(), cwd=WORK, stdin=subprocess.DEVNULL,
        stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
assert result.returncode == 0 and not (DATA / 'postmaster.pid').exists()
with socket.socket() as check:
    check.bind(('127.0.0.1', PORT))
save('preparation-postgresql-closure.json', {'state': 'PASS', 'argv': argv,
    'exit_code': result.returncode, 'postmaster_pid': preflight['postmaster_pid'],
    'port': PORT, 'port_free': True, 'same_cluster_preserved': True,
    'candidate_and_dependencies_preserved': True, 'foreign_processes_targeted': False})
for folder in ('awake-request', 'resource-observer'):
    path = EVIDENCE / folder / 'stop.request'
    with path.open('x', encoding='utf-8') as stream:
        stream.write('Preparation complete; waiting for external AC, no formal tests started.\n')
print('PREPARATION_CHECKPOINT_SAVED_OWNED_AUXILIARIES_RELEASING_NO_TESTS', flush=True)
