"""Validate native parent edges captured during this exact worker lifetime."""


def validate(launch,identity,samples,last_journal_monotonic):
    errors=[];paths=[];witnesses=[]
    launcher=launch['launcher_pid'];child=identity['os_pid']
    if (not launch.get('launcher_creation_filetime') or not identity.get('process_creation_filetime')
            or identity['process_creation_filetime']<launch['launcher_creation_filetime']):
        errors.append('NATIVE_CREATION_ORDER_MISSING_OR_REVERSED')
    for sample in samples:
        if not identity['monotonic_ns']<=sample['monotonic_ns']<=last_journal_monotonic:continue
        rows={p['pid']:p for p in sample['processes']}
        if child not in rows:continue
        path=[];pid=child;seen=set()
        while pid!=launcher:
            if pid in seen or len(path)>=8 or pid not in rows:
                errors.append('NATIVE_PARENT_CHAIN_MISSING_OR_CYCLIC');break
            seen.add(pid);row=rows[pid]
            if row['name'].lower() not in ('python.exe','pythonw.exe'):
                errors.append('UNEXPECTED_INTERMEDIATE_EXECUTABLE');break
            if pid==child and row['parent']!=identity['parent_pid']:
                errors.append('JOURNAL_AND_NATIVE_PARENT_DISAGREE');break
            path.append(dict(pid=pid,parent=row['parent'],name=row['name']))
            pid=row['parent']
        if pid==launcher:
            paths.append(path);witnesses.append(sample['monotonic_ns'])
    if len(set(witnesses))<2:errors.append('TWO_CONTEMPORANEOUS_NATIVE_SNAPSHOTS_REQUIRED')
    if paths and any(p!=paths[0] for p in paths):errors.append('NATIVE_PARENT_CHAIN_CHANGED_DURING_CAPTURE')
    return dict(passed=not errors,errors=sorted(set(errors)),native_chain=paths[0] if paths else [],
        samples=len(witnesses),monotonic_witness_bounds=[min(witnesses),max(witnesses)] if witnesses else None,
        source='WINDOWS_TOOLHELP_SNAPSHOTS_CAPTURED_DURING_PHYSICAL_ATTEMPT',physical_accreditation=False)
