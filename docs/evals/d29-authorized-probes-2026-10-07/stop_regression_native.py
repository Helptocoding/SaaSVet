"""Owned process-tree cleanup without relying on a stalled WMI service."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
k=c.WinDLL('kernel32',use_last_error=True);n=c.WinDLL('ntdll')
class Entry(c.Structure):
    _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),
        ('th32DefaultHeapID',c.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),
        ('th32ParentProcessID',w.DWORD),('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]
class Unicode(c.Structure):
    _fields_=[('Length',w.USHORT),('MaximumLength',w.USHORT),('Buffer',c.c_void_p)]
k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,c.POINTER(Entry)];k.Process32FirstW.restype=w.BOOL
k.Process32NextW.argtypes=[w.HANDLE,c.POINTER(Entry)];k.Process32NextW.restype=w.BOOL
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.TerminateProcess.restype=w.BOOL
k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
n.NtQueryInformationProcess.argtypes=[w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)];n.NtQueryInformationProcess.restype=w.LONG
def inventory():
    handle=k.CreateToolhelp32Snapshot(2,0)
    if handle==c.c_void_p(-1).value:raise OSError(c.get_last_error())
    rows=[];e=Entry();e.dwSize=c.sizeof(e)
    try:
        ok=k.Process32FirstW(handle,c.byref(e))
        while ok:
            rows.append(dict(pid=e.th32ProcessID,parent=e.th32ParentProcessID,name=e.szExeFile))
            ok=k.Process32NextW(handle,c.byref(e))
    finally:k.CloseHandle(handle)
    return rows
def command(pid):
    handle=k.OpenProcess(0x1000,False,pid)
    if not handle:return None
    try:
        size=w.ULONG();n.NtQueryInformationProcess(handle,60,None,0,c.byref(size))
        if not size.value or size.value>131072:return None
        buf=c.create_string_buffer(size.value)
        status=n.NtQueryInformationProcess(handle,60,buf,size.value,c.byref(size))
        if status<0:return None
        u=Unicode.from_buffer(buf)
        return c.string_at(u.Buffer,u.Length).decode('utf-16-le')
    finally:k.CloseHandle(handle)
rows=inventory();parents=[]
for row in rows:
    if row['name'].lower().startswith('python'):
        cmd=command(row['pid'])
        if cmd and 'd29-authorized-probes-2026-10-07' in cmd and 'run_regression_v2.py' in cmd:
            row['command']=cmd;parents.append(row)
if len(parents)>1:raise RuntimeError('Ambiguous regression parent')
owned={r['pid'] for r in parents}
while True:
    expanded=owned|{r['pid'] for r in rows if r['parent'] in owned}
    if expanded==owned:break
    owned=expanded
selected=[r for r in rows if r['pid'] in owned]
if any(r['name'].lower().startswith('postgres') for r in selected):raise RuntimeError('Unexpected database server descendant')
results=[]
ordered=parents+[r for r in selected if r['pid'] not in {p['pid'] for p in parents}]
for row in ordered:
    handle=k.OpenProcess(0x00100001,False,row['pid'])
    if not handle:
        results.append(dict(row,already_absent=True));continue
    try:
        terminated=bool(k.TerminateProcess(handle,130));wait=k.WaitForSingleObject(handle,5000)
        results.append(dict(row,terminated=terminated,wait_result=wait))
    finally:k.CloseHandle(handle)
remaining=[r for r in inventory() if r['pid'] in owned]
result=dict(reason='POSTGRESQL_OUT_OF_MEMORY_DURING_REGRESSION',
    parent_matches=len(parents),owned_processes=results,remaining=remaining,
    postgres_reconfigured=False,other_processes_modified=False)
with (OUT/'regression-native-stop-receipt.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(dict(parents=len(parents),owned_processes=len(selected),remaining=remaining)),flush=True)
if remaining:raise RuntimeError('Owned regression processes remain')
