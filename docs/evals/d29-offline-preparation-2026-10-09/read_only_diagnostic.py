"""Windows read-only diagnostics. No service mutation, SQL, suite or probe."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
from pathlib import Path

from common import HERE, PRIOR, save, sha, utc


def command(args):
    start=utc()
    try:
        p=subprocess.run(['rtk','proxy',*args],capture_output=True,text=True,timeout=20,errors='replace')
        return {'at_utc':start,'argv':args,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    except subprocess.TimeoutExpired as exc:
        return {'at_utc':start,'argv':args,'error':'READ_ONLY_COMMAND_TIMEOUT',
                'stdout':str(exc.stdout or ''),'stderr':str(exc.stderr or '')}


def service_access():
    a=c.WinDLL('advapi32',use_last_error=True)
    a.OpenSCManagerW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.DWORD];a.OpenSCManagerW.restype=w.HANDLE
    a.OpenServiceW.argtypes=[w.HANDLE,w.LPCWSTR,w.DWORD];a.OpenServiceW.restype=w.HANDLE
    a.CloseServiceHandle.argtypes=[w.HANDLE]
    manager=a.OpenSCManagerW(None,None,1)
    if not manager:return {'query_error':c.get_last_error(),'can_restore':False}
    try:
        service=a.OpenServiceW(manager,'W32Time',0x4|0x10|0x20)
        if not service:return {'start_stop_query_handle_opened':False,'error':c.get_last_error(),'can_restore':False}
        a.CloseServiceHandle(service)
        return {'start_stop_query_handle_opened':True,'can_restore':None,
                'meaning':'Access handle only; no StartService/ControlService called. Independent helper still needs its own check.'}
    finally:a.CloseServiceHandle(manager)


class Memory(c.Structure):
    _fields_=[('length',w.DWORD),('load_percent',w.DWORD),('total_physical',c.c_ulonglong),
              ('available_physical',c.c_ulonglong),('total_pagefile',c.c_ulonglong),
              ('available_pagefile',c.c_ulonglong),('total_virtual',c.c_ulonglong),
              ('available_virtual',c.c_ulonglong),('available_extended_virtual',c.c_ulonglong)]


class ProcessMemory(c.Structure):
    _fields_=[('cb',w.DWORD),('page_fault_count',w.DWORD),('peak_working_set',c.c_size_t),
              ('working_set',c.c_size_t),('peak_paged_pool',c.c_size_t),('paged_pool',c.c_size_t),
              ('peak_nonpaged_pool',c.c_size_t),('nonpaged_pool',c.c_size_t),('pagefile_usage',c.c_size_t),
              ('peak_pagefile_usage',c.c_size_t),('private_usage',c.c_size_t)]


class BasicLimit(c.Structure):
    _fields_=[('per_process_user_time',c.c_longlong),('per_job_user_time',c.c_longlong),('flags',w.DWORD),
              ('min_working_set',c.c_size_t),('max_working_set',c.c_size_t),('active_process_limit',w.DWORD),
              ('affinity',c.c_size_t),('priority_class',w.DWORD),('scheduling_class',w.DWORD)]


class IoCounters(c.Structure):
    _fields_=[(n,c.c_ulonglong) for n in ('read_operations','write_operations','other_operations','read_bytes','write_bytes','other_bytes')]


class ExtendedLimit(c.Structure):
    _fields_=[('basic',BasicLimit),('io',IoCounters),('process_memory_limit',c.c_size_t),
              ('job_memory_limit',c.c_size_t),('peak_process_memory',c.c_size_t),('peak_job_memory',c.c_size_t)]


def memory_and_processes():
    k=c.WinDLL('kernel32',use_last_error=True);p=c.WinDLL('psapi',use_last_error=True)
    k.GlobalMemoryStatusEx.argtypes=[c.POINTER(Memory)]
    mem=Memory();mem.length=c.sizeof(mem)
    if not k.GlobalMemoryStatusEx(c.byref(mem)):raise OSError(c.get_last_error())
    memory={name:getattr(mem,name) for name,_ in Memory._fields_ if name!='length'}
    memory['commit_used_approx']=mem.total_pagefile-mem.available_pagefile
    spec=importlib.util.spec_from_file_location('readonly_previous_inventory',PRIOR/'inspect_cleanup_v3.py')
    inventory=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory)
    p.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.POINTER(ProcessMemory),w.DWORD]
    rows=[]
    for row in inventory.inventory():
        if row['name'].lower() not in ('python.exe','pythonw.exe','postgres.exe','pg_ctl.exe','powershell.exe','pwsh.exe'):
            continue
        # Command lines never leave this process: only known ownership markers.
        cmd=inventory.command(row['pid'])
        row['owned_markers']=[m for m in ('vet-d29-authorized-20261007-','run_regression_v2.py','d29-offline-preparation-2026-10-09') if cmd and m in cmd]
        handle=inventory.k.OpenProcess(0x400|0x10,False,row['pid'])
        if handle:
            try:
                pm=ProcessMemory();pm.cb=c.sizeof(pm)
                if p.GetProcessMemoryInfo(handle,c.byref(pm),c.sizeof(pm)):
                    row['memory']={key:getattr(pm,key) for key,_ in ProcessMemory._fields_ if key!='cb'}
                else:row['memory_error']=c.get_last_error()
            finally:inventory.k.CloseHandle(handle)
        else:row['memory_error']=c.get_last_error()
        rows.append(row)
    k.QueryInformationJobObject.argtypes=[w.HANDLE,w.INT,c.c_void_p,w.DWORD,c.c_void_p]
    job=ExtendedLimit()
    if k.QueryInformationJobObject(None,9,c.byref(job),c.sizeof(job),None):
        limits={'available':True,'scope':'current diagnostic process job; not historical PostgreSQL backend',
                'flags':job.basic.flags,'process_memory_limit':job.process_memory_limit,
                'job_memory_limit':job.job_memory_limit,'active_process_limit':job.basic.active_process_limit,
                'peak_process_memory':job.peak_process_memory,'peak_job_memory':job.peak_job_memory}
    else:limits={'available':False,'error':c.get_last_error(),'meaning':'Unknown; not evidence of unlimited memory'}
    return memory,rows,limits


class TcpRow(c.Structure):
    _fields_=[(name,w.DWORD) for name in ('state','local_address','local_port','remote_address','remote_port','pid')]


def tcp_snapshot(processes):
    api=c.WinDLL('iphlpapi',use_last_error=True)
    api.GetExtendedTcpTable.argtypes=[c.c_void_p,c.POINTER(w.DWORD),w.BOOL,w.ULONG,w.INT,w.ULONG]
    size=w.DWORD(0)
    api.GetExtendedTcpTable(None,c.byref(size),False,2,5,0)
    buf=c.create_string_buffer(size.value)
    rc=api.GetExtendedTcpTable(buf,c.byref(size),False,2,5,0)
    if rc:return {'error':rc,'connections':None}
    n=w.DWORD.from_buffer(buf).value
    postgres={p['pid'] for p in processes if p['name'].lower()=='postgres.exe'}
    rows=[]
    for i in range(n):
        row=TcpRow.from_buffer(buf,c.sizeof(w.DWORD)+i*c.sizeof(TcpRow))
        port=socket.ntohs(row.local_port&0xffff)
        if row.pid in postgres or port in (55969,60036):
            rows.append({'pid':row.pid,'state':row.state,'local_port':port,'remote_port':socket.ntohs(row.remote_port&0xffff)})
    return {'method':'GetExtendedTcpTable read-only IPv4 snapshot','connections':rows,
            'historical_private_ports':{str(port):not any(r['local_port']==port for r in rows) for port in (55969,60036)},
            'pg_stat_activity':'NOT_AVAILABLE: preserved private clusters removed; no production DB queried',
            'ipv6_and_historical_connections':'NOT_MEASURED'}


def historical_oom():
    directory=PRIOR/'recovered-labs/vet-d29-authorized-20261007-03e5n2jy'
    found=[]
    for path in (directory/'pg.stderr',PRIOR/'application-regression-v2/test_b4_sender.log'):
        text=path.read_text(encoding='utf-8',errors='replace').splitlines()
        hits=[]
        for i,line in enumerate(text):
            if 'out of memory' in line.lower() or 'request of size 48' in line:
                # These lines contain the error and context, not SQL/payloads.
                hits.append({'line':i+1,'error_text':line})
            elif i and 'STATEMENT:' in line and any('out of memory' in s.lower() or 'request of size 48' in s for s in text[max(0,i-3):i]):
                hits.append({'line':i+1,'statement_sha256':hashlib.sha256(line.encode()).hexdigest(),'statement_bytes':len(line.encode()),'sql_not_disclosed':True})
        found.append({'path':str(path.relative_to(PRIOR)),'sha256':sha(path),'line_count':len(text),'hits':hits})
    return {'status':'ROOT_CAUSE_UNDETERMINED','observed':'PostgreSQL backend PID 102336: 48-byte allocation failed in MessageContext',
            'logs':found,'historical_process_disposition':read_safe_stop(),
            'unavailable':['host commit/physical memory at OOM','backend memory contexts before failure','pg_stat_activity at failure','historical job limits'],
            'attributed_to_runtime':False,'resolution_claimed':False,'memory_or_pg_changes':False}


def read_safe_stop():
    path=PRIOR/'regression-native-stop-receipt.json'
    value=json.loads(path.read_text())
    return {'receipt':str(path.relative_to(PRIOR)),'sha256':sha(path),
            'reason':value['reason'],'owned_processes':[{'pid':p['pid'],'parent':p['parent'],'name':p['name'],'terminated':p['terminated']} for p in value['owned_processes']],
            'remaining':value['remaining']}


if __name__=='__main__':
    if os.name!='nt':raise SystemExit('Windows read-only diagnostic only')
    memory,processes,limits=memory_and_processes()
    clock={'service':command(['powershell','-NoProfile','-Command','Get-Service -Name W32Time | Select-Object Name,Status,StartType | ConvertTo-Json -Compress']),
           'status':command(['w32tm','/query','/status','/verbose']),
           'source':command(['w32tm','/query','/source']),
           'access_check_only':service_access(),'service_modified':False}
    value={'at_utc':utc(),'kind':'READ_ONLY_HOST_AND_PRESERVED_LOG_DIAGNOSTIC','clock':clock,
           'memory':memory,'processes':processes,'current_process_job_limits':limits,
           'connections':tcp_snapshot(processes),'oom':historical_oom(),
           'limits_changed':False,'service_control_called':False,'databases_created':False,'suites_executed':False}
    save('host-diagnostic.json',value)
    print(json.dumps({'at_utc':value['at_utc'],'memory':memory,'clock_access':clock['access_check_only'],
                      'clock_status':clock['status'],'connections':value['connections'],'oom_status':value['oom']['status']},ensure_ascii=False))
