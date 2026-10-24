"""Preserve pre-seal observations invalidated by the confirmed Windows reboot."""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from native_support import RTK, REPO, save, environment, resources


def main():
    assert not any((HERE / n).exists() for n in ('evaluation-seal.json', 'invocation-formal.json', 'STOP.json'))
    boot = subprocess.check_output([str(RTK), 'proxy', 'powershell.exe', '-NoProfile', '-Command',
        "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')"],
        cwd=REPO, env=environment(), creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()
    assert boot.startswith('2026-10-18T11:52:49.'), boot
    archive = HERE / 'diagnostics/preparation-interruption/host-observations'
    assert not archive.exists()
    archive.mkdir(parents=True)
    records = {}
    names = ('awake-request', 'resource-observer', 'resource-observer-control.json',
             'resource-observer-closure.json', 'clock-preflight.json', 'clock-observation.json',
             'invocation-clock.json', 'invocation-clock.log')
    for name in names:
        source = HERE / name
        if not source.exists():
            continue
        assert source.resolve().parent == HERE.resolve()
        assert not source.is_symlink() and not source.is_junction()
        target = archive / name
        assert target.resolve().is_relative_to(HERE.resolve()) and not target.exists()
        files = list(source.rglob('*')) if source.is_dir() else [source]
        records[name] = {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in files if p.is_file()}
        source.rename(target)
        for old, digest in records[name].items():
            restored = archive / Path(old)
            assert hashlib.sha256(restored.read_bytes()).hexdigest() == digest
    receipt = {'state': 'PRESERVED_BEFORE_FRESH_PREFLIGHT',
        'utc': datetime.now(timezone.utc).isoformat(), 'windows_last_boot_utc': boot,
        'cause': 'Windows reboot before formal seal; prior session no longer exists',
        'old_auxiliary_processes_survived_reboot': False,
        'old_api_explicit_restoration_claimed': False,
        'old_thread_requests_end_with_previous_windows_session': True,
        'global_power_clock_display_policy_changed': False,
        'candidate_or_test_assertions_changed': False, 'formal_tests_executed': False,
        'archived_observations_sha256': records, 'resources': resources(),
        'fresh_awake_max_seconds': 43200, 'fresh_observer_max_seconds': 46800,
        'adaptive_renewal': False}
    save('diagnostics/host-preflight-recovery.json', receipt)
    amendment = json.loads((HERE / 'operational-lifetime-amendment.json').read_text(encoding='utf-8'))
    amendment['pre_seal_reboot_recovery'] = {
        'reference': 'diagnostics/host-preflight-recovery.json',
        'sha256': hashlib.sha256((HERE / 'diagnostics/host-preflight-recovery.json').read_bytes()).hexdigest(),
        'fresh_bounded_requests_before_formal_only': True, 'old_observations_retained': True}
    save('operational-lifetime-amendment.json', amendment)
    print('PRE_SEAL_REBOOT_OBSERVATIONS_PRESERVED', flush=True)


if __name__ == '__main__':
    main()
