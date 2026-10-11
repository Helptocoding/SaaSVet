"""Read-only inventory of the two explicitly owned labs and their helpers."""
import ctypes as c
from ctypes import wintypes as w
import json
import socket
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
k = c.WinDLL('kernel32', use_last_error=True)
n = c.WinDLL('ntdll')

class Entry(c.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
        ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD), ('cntThreads', w.DWORD),
        ('th32ParentProcessID', w.DWORD), ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]

class Unicode(c.Structure):
    _fields_ = [('Length', w.USHORT), ('MaximumLength', w.USHORT), ('Buffer', c.c_void_p)]

k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
k.CreateToolhelp32Snapshot.restype = w.HANDLE
k.Process32FirstW.argtypes = [w.HANDLE, c.POINTER(Entry)]
k.Process32FirstW.restype = w.BOOL
k.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Entry)]
k.Process32NextW.restype = w.BOOL
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
k.CloseHandle.restype = w.BOOL
k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
k.TerminateProcess.restype = w.BOOL
k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
k.WaitForSingleObject.restype = w.DWORD
n.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)]
n.NtQueryInformationProcess.restype = w.LONG

def inventory():
    handle = k.CreateToolhelp32Snapshot(2, 0)
    if handle == c.c_void_p(-1).value:
        raise OSError(c.get_last_error())
    rows = []
    e = Entry()
    e.dwSize = c.sizeof(e)
    try:
        ok = k.Process32FirstW(handle, c.byref(e))
        while ok:
            rows.append(dict(pid=e.th32ProcessID, parent=e.th32ParentProcessID, name=e.szExeFile))
            ok = k.Process32NextW(handle, c.byref(e))
    finally:
        k.CloseHandle(handle)
    return rows

def command(pid):
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = w.ULONG()
        n.NtQueryInformationProcess(handle, 60, None, 0, c.byref(size))
        if not size.value or size.value > 131072:
            return None
        buf = c.create_string_buffer(size.value)
        status = n.NtQueryInformationProcess(handle, 60, buf, size.value, c.byref(size))
        if status < 0:
            return None
        u = Unicode.from_buffer(buf)
        return c.string_at(u.Buffer, u.Length).decode('utf-16-le')
    finally:
        k.CloseHandle(handle)

def closed(port):
    with socket.socket() as sock:
        sock.settimeout(2)
        return sock.connect_ex(('127.0.0.1', port)) != 0

def inspect():
    rows = []
    markers = ('vet-d29-authorized-20261007-', 'stop-regression-owned.ps1', 'cleanup_owned_oom.py', 'run_regression_v2.py')
    for row in inventory():
        if row['name'].lower() not in ('python.exe', 'pythonw.exe', 'powershell.exe', 'pwsh.exe', 'postgres.exe', 'pg_ctl.exe'):
            continue
        cmd = command(row['pid'])
        matched = [m for m in markers if cmd and m in cmd]
        if matched:
            rows.append(dict(row, matching_markers=matched))
    labs = []
    for name, port in (('vet-d29-authorized-20261007-03e5n2jy', 55969), ('vet-d29-authorized-20261007-l8icq_3c', 60036)):
        path = Path(tempfile.gettempdir()) / name
        archive = OUT / 'recovered-labs' / name
        labs.append(dict(name=name, exists=path.exists(), session_exists=(path/'session.json').exists(),
            children=sorted(p.name for p in path.iterdir()) if path.exists() else [],
            port=port, port_closed=closed(port), recovered_files=sorted(p.name for p in archive.iterdir()) if archive.exists() else []))
    return dict(laboratories=labs, matching_processes=rows)

if __name__ == '__main__':
    value = inspect()
    with (OUT / 'cleanup-inspection-v3.json').open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
    print(json.dumps(value), flush=True)
