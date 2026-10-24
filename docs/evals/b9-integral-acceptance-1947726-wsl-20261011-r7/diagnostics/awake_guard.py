"""Bounded, reversible Windows idle-sleep request; never run application tests.

Prepared after r7 STOP for a future campaign. Uses SetThreadExecutionState on
its own thread, without changing a power plan, display policy, or W32Time.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def save(directory, name, value):
    target = directory / name
    assert not target.exists(), target
    target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, required=True)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 21600:
        parser.error('Duration must be between 1 and 21600 seconds')
    directory = args.output.resolve()
    if directory.exists():
        parser.error('Output must be a new directory; no overwrite')
    directory.mkdir(parents=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    request = kernel.SetThreadExecutionState
    request.argtypes = [wintypes.DWORD]
    request.restype = wintypes.DWORD
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    previous = request(flags)
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    started = time.monotonic()
    confirmed = 0
    error = None
    try:
        confirmed = request(flags)
        if not confirmed or (confirmed & flags) != flags:
            raise RuntimeError('Own thread did not retain the requested execution state')
        save(directory, 'control.json', {
            'state': 'ACTIVE_API_CONFIRMED', 'pid': os.getpid(),
            'thread_id': kernel.GetCurrentThreadId(), 'seconds_maximum': args.seconds,
            'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'flags_requested': hex(flags), 'previous_thread_state': hex(previous),
            'confirmation_previous_state': hex(confirmed),
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'global_power_policy_changed': False, 'display_policy_changed': False,
            'W32Time_changed': False, 'application_tests_executed': False,
            'limits': 'Idle sleep request only; user-requested sleep/lid/power button and policy overrides are not guaranteed to be prevented',
            'documentation': 'https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate'})
        print('OWN_AWAKE_REQUEST_ACTIVE', flush=True)
        while time.monotonic() - started < args.seconds:
            if args.stop_file and args.stop_file.exists():
                break
            time.sleep(min(0.5, max(0, args.seconds - (time.monotonic() - started))))
    except BaseException as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        restore_flags = previous | ES_CONTINUOUS
        before_release = request(restore_flags)
        restored_state = request(restore_flags)
        restored = bool(before_release and restored_state and restored_state == restore_flags)
        save(directory, 'closure.json', {
            'state': 'PASS_API_REQUEST_AND_RESTORATION' if restored and not error else 'NONPASS',
            'seconds': time.monotonic() - started, 'pid': os.getpid(),
            'thread_state_before_release': hex(before_release),
            'restored_thread_state': hex(restored_state),
            'matches_original_thread_state': restored,
            'error': error, 'application_tests_executed': False,
            'sleep_prevention_over_15_minutes_validated': False,
            'global_power_policy_changed': False})
        if not restored:
            raise RuntimeError('Own awake request restoration could not be confirmed')
        print('OWN_AWAKE_REQUEST_RESTORED', flush=True)

if __name__ == '__main__':
    main()
