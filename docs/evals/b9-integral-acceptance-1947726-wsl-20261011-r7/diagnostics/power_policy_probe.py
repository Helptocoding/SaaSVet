"""Read host power policy after STOP without changing system configuration."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parents[1]

class PowerStatus(ctypes.Structure):
    _fields_ = [('ACLineStatus', wintypes.BYTE), ('BatteryFlag', wintypes.BYTE),
        ('BatteryLifePercent', wintypes.BYTE), ('SystemStatusFlag', wintypes.BYTE),
        ('BatteryLifeTime', wintypes.DWORD), ('BatteryFullLifeTime', wintypes.DWORD)]

def main():
    assert (HERE / 'STOP.json').exists()
    target = HERE / 'power-policy-after-stop.json'
    assert not target.exists()
    status = PowerStatus()
    get_status = ctypes.WinDLL('kernel32', use_last_error=True).GetSystemPowerStatus
    get_status.argtypes = [ctypes.POINTER(PowerStatus)]
    get_status.restype = wintypes.BOOL
    success = get_status(ctypes.byref(status))
    results = {}
    for name, args in [('active_scheme', ['/getactivescheme']),
            ('sleep_policy', ['/query', 'SCHEME_CURRENT', 'SUB_SLEEP']),
            ('available_sleep_states', ['/a']), ('current_requests', ['/requests'])]:
        result = subprocess.run(['rtk', 'proxy', 'powercfg.exe', *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        results[name] = {'args': args, 'exit_code': result.returncode,
            'stdout': result.stdout.decode('utf-8', errors='replace'),
            'stderr': result.stderr.decode('utf-8', errors='replace')}
    data = {'state': 'RECORDED', 'created_after_stop': True, 'read_only': True,
        'configuration_changed': False, 'application_tests_executed': False,
        'system_power_status_api_success': bool(success),
        'system_power_status': {name: getattr(status, name) for name, _ in status._fields_} if success else None,
        'commands': results,
        'causality_limit': 'Current policy/status is a post-stop observation, not proof of which caller or action caused the sleep event'}
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False))

if __name__ == '__main__':
    main()
