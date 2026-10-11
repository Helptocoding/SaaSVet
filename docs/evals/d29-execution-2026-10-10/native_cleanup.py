"""Actual exit + after-process inventory + absent database clients, no inference."""


def participant_exit(exits,native_worker_pids,snapshot,live_backends):
    errors=[]
    if len(exits)!=3 or any(p['exit_code']!=0 for p in exits):errors.append('WORKER_EXIT_NOT_CLEAN')
    if len(set(native_worker_pids))!=3:errors.append('THREE_NATIVE_WORKER_IDENTITIES_REQUIRED')
    if any(p['pid'] in native_worker_pids for p in snapshot):errors.append('NATIVE_WORKER_STILL_PRESENT')
    if live_backends:errors.append('NATIVE_PARTICIPANT_BACKEND_STILL_PRESENT')
    return dict(all_reaped=not errors,failures=errors,native_worker_pids=native_worker_pids,
        source='NATIVE_PROCESS_AND_BACKEND_INVENTORY_AFTER_WORKER_WAIT')


def capture(directory,exits):
    import sys
    import time
    from pathlib import Path
    from apps.agent.claim_diagnostic_report import read_journal
    from apps.agent.tests.scheduling_characterization.runner import write_json
    from django.db import connection
    sys.path.append(str(Path(__file__).parent.parent/'d29-offline-preparation-2026-10-09'))
    from read_only_diagnostic import memory_and_processes
    identities=[]
    for role in ('planner_1','planner_2','sender'):
        matches=[r for r in read_journal(directory/(role+'.jsonl')) if r['event']=='participant_identity']
        if len(matches)!=1:raise ValueError('NATIVE_WORKER_IDENTITY_MISSING')
        identities.append(matches[0])
    before=time.perf_counter_ns()
    _,processes,_=memory_and_processes()
    with connection.cursor() as c:
        c.execute('SELECT pid FROM pg_stat_activity WHERE pid IN (%s,%s,%s)',[r['backend_pid'] for r in identities])
        backends=c.fetchall()
    after=time.perf_counter_ns()
    write_json(directory/'participant-process-after.json',dict(monotonic_bounds=[before,after],processes=processes,live_backends=backends))
    result=participant_exit(exits,[r['os_pid'] for r in identities],processes,backends)
    result['evidence']=['participant-exits.json','participant-process-after.json']
    write_json(directory/'participants-cleanup.json',result)


def validate(exits,native_worker_pids,after_samples,execution):
    errors=[]
    if len(exits)!=3 or any(p['exit_code']!=0 for p in exits):errors.append('WORKER_EXIT_NOT_CLEAN')
    if len(set(native_worker_pids))!=3:errors.append('THREE_NATIVE_WORKER_IDENTITIES_REQUIRED')
    if not after_samples or any(r['stage']!='after' for r in after_samples):errors.append('NATIVE_AFTER_SNAPSHOT_REQUIRED')
    if any(p['pid'] in native_worker_pids for r in after_samples for p in r['processes']):errors.append('NATIVE_WORKER_STILL_PRESENT')
    if execution.get('clients_after_child')!=[] or execution.get('database_removed') is not True:
        errors.append('OWNED_DATABASE_CLEANUP_NOT_PROVEN')
    return dict(all_reaped=not errors,failures=errors,native_worker_pids=native_worker_pids,
        exit_receipt='participant-exits.json',after_resource_samples=len(after_samples),
        source='CONTEMPORANEOUS_NATIVE_EXIT_AND_PROCESS_SNAPSHOTS')
