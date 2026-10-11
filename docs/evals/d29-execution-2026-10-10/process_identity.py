"""Read-only Windows process creation witness; no host configuration calls."""
import ctypes
import os
from ctypes import wintypes


def creation(pid):
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        raise OSError(ctypes.get_last_error(),'PROCESS_CREATION_WITNESS_UNAVAILABLE')
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
            raise OSError(ctypes.get_last_error(),'PROCESS_TIMES_UNAVAILABLE')
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)
