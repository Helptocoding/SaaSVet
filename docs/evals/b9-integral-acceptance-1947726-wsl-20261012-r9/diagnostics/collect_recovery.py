"""Capture post-restart evidence without rewriting damaged formal receipts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parents[1]


def save(name, data):
    p = HERE / name
    assert not p.exists(), name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def command(args):
    p = subprocess.run(['rtk', 'proxy', *args], capture_output=True, timeout=60)
    return {'argv': args, 'exit_code': p.returncode,
            'stdout': p.stdout.decode('utf-8-sig', errors='replace'),
            'stderr': p.stderr.decode('utf-8-sig', errors='replace')}


def main():
    invalid, nulls = [], []
    for p in HERE.rglob('*'):
        if not p.is_file() or p.suffix not in ('.json', '.jsonl', '.log'):
            continue
        data = p.read_bytes()
        row = {'path': p.relative_to(HERE).as_posix(), 'bytes': len(data),
               'sha256': hashlib.sha256(data).hexdigest()}
        if b'\0' in data:
            nulls.append(dict(row, null_bytes=data.count(b'\0')))
        if p.suffix == '.json':
            try:
                json.loads(data)
            except Exception as e:
                invalid.append(dict(row, error=str(e)))
    save('damaged-receipts.json', {'invalid_json': invalid, 'files_with_null_bytes': nulls,
         'original_bytes_preserved': True, 'cause_of_byte_damage_established': False,
         'replacement_formal_receipts_created': False})
    script = r"""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$events = @(Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,6005,6008; StartTime=[datetime]'2026-10-13T00:00:00'} -MaxEvents 6 -ErrorAction SilentlyContinue | ForEach-Object {
    @{utc=$_.TimeCreated.ToUniversalTime().ToString('o'); id=$_.Id; provider=$_.ProviderName; message=$_.Message; xml=$_.ToXml()}
})
$os = Get-CimInstance Win32_OperatingSystem
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in 22456,18840 } | Select-Object ProcessId,Name,CreationDate,CommandLine)
@{observed_utc=[datetime]::UtcNow.ToString('o'); last_boot_utc=$os.LastBootUpTime.ToUniversalTime().ToString('o'); free_physical_kib=$os.FreePhysicalMemory; prior_monitor_pids_now=$processes; events=$events} | ConvertTo-Json -Depth 8
"""
    result = command(['powershell', '-NoProfile', '-Command', script])
    save('host-restart-query.json', result)
    assert result['exit_code'] == 0, result
    host = json.loads(result['stdout'])
    save('host-restart-evidence.json', host)
    assert not host['prior_monitor_pids_now'], 'Do not kill reused PIDs'
    save('monitor-closure-after-restart.json', {
        'state': 'PASS_CURRENT_PROCESS_ABSENCE', 'prior_windows_pids': [22456, 18840],
        'normal_finally_receipts_available': False, 'explicit_stop_requests_saved_after_restart': True,
        'original_API_thread_restoration_proven': False,
        'request_cannot_survive_termination_of_owning_thread': True,
        'global_power_policy_changed': False, 'W32Time_changed': False,
        'limitation': 'Current absence verified; do not infer graceful shutdown or original API release call'})
    cfg = json.loads((HERE / 'clock-guardian-location.json').read_text())
    status = command(['wsl.exe', '-d', 'Ubuntu-24.04', '--exec', cfg['linux'] + '/rtk-linux', 'proxy',
                      'systemctl', 'show', 'systemd-timesyncd.service',
                      '--property=ActiveState,SubState,UnitFileState,MainPID'])
    save('clock-restoration-after-restart-query.json', status)
    assert status['exit_code'] == 0
    fields = dict(line.split('=', 1) for line in status['stdout'].splitlines() if '=' in line)
    assert fields['ActiveState'] == 'active' and fields['SubState'] == 'running' and fields['UnitFileState'] == 'enabled'
    save('clock-restoration.json', {'state': 'PASS', 'method': 'current state verified after host/WSL restart',
         'active_matches_original': True, 'enabled_matches_original': True, 'status': fields,
         'guardian_service_restored_receipt_available': False,
         'normal_guardian_restoration_proven': False, 'windows_W32Time_untouched': True})
    save('disk-after-stop.json', {'observed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
         'backing_disk_free_bytes': shutil.disk_usage('C:/').free,
         'measurement_after_host_restart': True, 'does_not_revalidate_interrupted_full_block': True})
    print('POST_RESTART_EVIDENCE_SAVED')


if __name__ == '__main__':
    main()
