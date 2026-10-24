"""Read-only readiness evidence for the user-authorized continuation after r8."""
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import winreg

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
GIB = 1024**3


def query(argv, timeout=30):
    started = time.monotonic()
    try:
        result = subprocess.run(['rtk', 'proxy', *argv], capture_output=True, timeout=timeout)
        return {'exit_code': result.returncode, 'seconds': time.monotonic() - started,
                'stdout': result.stdout.decode('utf-8', errors='replace'),
                'stderr': result.stderr.decode('utf-8', errors='replace')}
    except subprocess.TimeoutExpired as exc:
        return {'exit_code': None, 'timeout_seconds': timeout,
                'seconds': time.monotonic() - started,
                'stdout': (exc.stdout or b'').decode('utf-8', errors='replace'),
                'stderr': (exc.stderr or b'').decode('utf-8', errors='replace')}


def main():
    target = HERE / 'environment-readiness.json'
    assert not target.exists(), 'Preserve the original readiness receipt'
    disks = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            path = chr(65+i) + ':/'
            if ctypes.windll.kernel32.GetDriveTypeW(path) == 3:
                disks.append({'path': path, **shutil.disk_usage(path)._asdict()})
    wsl = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Lxss') as key:
        for i in range(winreg.QueryInfoKey(key)[0]):
            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as distro:
                def value(name):
                    try:
                        return winreg.QueryValueEx(distro, name)[0]
                    except OSError:
                        return None
                base = value('BasePath')
                files = []
                if base and Path(base).exists():
                    files = [{'name': f.name, 'logical_bytes': f.stat().st_size}
                             for f in Path(base).iterdir() if f.is_file() and f.suffix == '.vhdx']
                wsl.append({'name': value('DistributionName'), 'base_path': base,
                            'virtual_disk_files': files})
    result = {'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'user_instruction': 'prosige', 'candidate_sha': '194772677ca4e9fe1a1dec7f4dafa48396a6c583',
        'scope': 'Read-only readiness before another fixed-scope acceptance campaign',
        'disk_samples': disks, 'wsl_registration': wsl,
        'Windows_pagefile': query(['powershell.exe', '-NoProfile', '-Command',
            'Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage | ConvertTo-Json -Compress']),
        'wsl_probe': query(['wsl.exe', '-d', 'Ubuntu-24.04', '--exec', '/usr/bin/python3', '-B', '-c',
            "import json,shutil; from pathlib import Path; print(json.dumps({'backing':shutil.disk_usage('/mnt/c')._asdict(),'linux':shutil.disk_usage('/home/lap')._asdict(),'owned_workspaces':[q.name for q in Path('/home/lap').iterdir() if q.name.startswith('b9i-wsl-')]}))"]),
        'formal_application_tests_executed': False,
        'dependencies_reinstalled': False, 'files_deleted': False,
        'global_configuration_changed': False, 'prior_campaigns_modified': False}
    result['disk_at_end'] = shutil.disk_usage('C:/')._asdict()
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
