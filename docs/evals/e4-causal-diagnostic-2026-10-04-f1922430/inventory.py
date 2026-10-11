"""Observe this run's process ancestry; do not serialize command lines."""
import json
import subprocess
import infra


def main():
    command = "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'postgres.exe'\" | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    output = subprocess.check_output(['rtk','proxy','powershell','-NoProfile','-Command',command]).decode()
    rows = json.loads(output)
    rows = [rows] if isinstance(rows,dict) else rows
    selected = {row['ProcessId'] for row in rows if infra.KEY[:8] in (row['CommandLine'] or '')}
    for _ in range(10):
        updated = selected | {row['ProcessId'] for row in rows if row['ParentProcessId'] in selected}
        if updated == selected:
            break
        selected = updated
    records = [{key:row[key] for key in ('ProcessId','ParentProcessId','Name')} for row in rows if row['ProcessId'] in selected]
    assert records
    infra.write('process-inventory-observed.json',records)
    print(json.dumps(dict(observed_processes=len(records),command_lines_serialized=False)))


if __name__=='__main__':
    main()
