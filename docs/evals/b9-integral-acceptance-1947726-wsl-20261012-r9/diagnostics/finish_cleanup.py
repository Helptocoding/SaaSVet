"""Finish owned cleanup, excluding only this helper's verified parent wrapper."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from recover_cleanup import HERE, WORK, DATA, PG, PORT, RTK, run, save, closed


def main():
    assert json.loads((HERE / 'STOP.json').read_text())['phase'] == 'full'
    assert WORK.resolve() == Path('/home/lap/b9i-wsl-1947726-20261012-r9')
    for kind in ['candidate-sources', 'dependency-files', 'evaluation-seal']:
        assert not json.loads((HERE / ('recovery-integrity-' + kind + '.json')).read_text())['mismatches']
    parent = os.getppid()
    own, wrapper = [], []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            args = (p / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, PermissionError):
            continue
        if not args or not args[0].startswith(str(WORK).encode()):
            continue
        record = {'pid': int(p.name), 'argv': [a.decode(errors='replace') for a in args if a]}
        if int(p.name) == parent and args[0] == str(RTK).encode() and str(Path(__file__).resolve()).encode() in args:
            wrapper.append(record)
        else:
            own.append(record)
    save('cleanup-recovery-process-verification.json', {'port_closed': closed(),
         'other_owned_processes': own, 'verified_current_parent_wrapper': wrapper,
         'prior_recovery_assertion_reason': 'The prior inventory counted its own RTK parent wrapper; no PostgreSQL start or data deletion occurred',
         'prior_recovery_script_sha256': hashlib.sha256((HERE / 'diagnostics/recover_cleanup.py').read_bytes()).hexdigest()})
    assert closed() and not own
    assert not (HERE / 'cleanup.json').exists()
    shutil.copy2(WORK / 'postgresql.log', HERE / 'postgresql-before-recovery.log')
    run('cleanup-recovery-pg-start', [PG / 'pg_ctl', '-D', DATA, '-l', WORK / 'postgresql.log', '-w', 'start'])
    # The sealed helper performs SQL ownership capture and only removes the exact owned path.
    from cleanup_linux import main as cleanup
    cleanup()
    save('cleanup-recovery-completion.json', {'state': 'PASS', 'formal_reruns': 0,
         'application_tests_executed': False, 'private_postgresql_started_only_for_SQL_preservation_and_cleanup': True,
         'original_failed_cleanup_and_recovery_receipts_preserved': True,
         'normal_cleanup_after_formal_stop_was_interrupted_by_restart': True})


if __name__ == '__main__':
    main()
