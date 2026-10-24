"""Finish only removal of the owned workspace after a Windows path error."""
import json
import os
from pathlib import Path
import shutil
import socket
from prepare_campaign import EVIDENCE, REPO, WORK, SHA, save, sha256, resources, run

assembly = json.loads((EVIDENCE / 'assembly.json').read_text())
absolute = WORK.resolve()
expected = (Path(os.environ['TEMP']) / 'b9i-1947726').resolve()
assert absolute == expected == Path(assembly['workspace']).resolve()
assert absolute.parent == Path(os.environ['TEMP']).resolve() and absolute != REPO.resolve()
assert json.loads((EVIDENCE / 'integrity-final-before-cleanup.json').read_text())['mismatches'] == []
assert 'server stopped' in (EVIDENCE / 'pg-stop.log').read_text()
assert not (WORK / 'pgdata/postmaster.pid').exists()
with socket.socket() as sock:
    port_closed = sock.connect_ex(('127.0.0.1', 35459)) != 0
assert port_closed
save('cleanup-incident.json', {'phase': 'CLEANUP_ONLY', 'application_tests_executed': 0,
    'cause': 'WinError 145 removing a deeply nested pnpm dependency directory',
    'correction': 'Use Windows extended-length path for the same verified absolute owned workspace',
    'sql_snapshot_limitation': 'SQL checks and DROP DATABASE completed before the exception; in-memory row snapshots were not persisted because the final write followed recursive deletion',
    'postgresql_restart_or_test_rerun': False})
extended = '\\\\?\\' + str(absolute)
if absolute.exists():
    shutil.rmtree(extended)
assert not absolute.exists()
save('cleanup.json', {'state': 'PASS', 'owned_workspace': str(absolute),
    'resolved_recursive_removal_target_verified': str(expected), 'workspace_removed': True,
    'port': 35459, 'port_closed_verified': port_closed, 'postmaster_pid_file_absent': True,
    'pg_stop_log': 'pg-stop.log', 'owned_databases_dropped': ['test_b9i_control'],
    'sql_checks': 'Completed by close_campaign.py before the recorded filesystem exception',
    'raw_sql_snapshot_limitation': 'See cleanup-incident.json; no unrecorded row values fabricated',
    'reused_python_and_postgresql_installations_removed': False,
    'foreign_processes_terminated': False, 'resources_after': resources()})
initial = json.loads((EVIDENCE / 'checkout-before.json').read_text())
final = {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
    'branch': run('git', 'branch', '--show-current').decode().strip(),
    'unrelated': {p: {'exists': (REPO / p).exists(), 'sha256': sha256((REPO / p).read_bytes()) if (REPO / p).exists() else None}
                  for p in initial['unrelated']}}
final['unrelated_unchanged'] = final['unrelated'] == initial['unrelated']
assert final['unrelated_unchanged'] and final['head'] == initial['head'] and final['branch'] == initial['branch']
save('checkout-final.json', final)
print('Owned workspace removed; PostgreSQL stopped; unrelated changes intact.')
