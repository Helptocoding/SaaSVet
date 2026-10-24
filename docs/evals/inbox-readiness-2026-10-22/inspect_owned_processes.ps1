$taskProcesses = Get-CimInstance Win32_Process
$taskLaunchers = @($taskProcesses | Where-Object { $_.CommandLine -like '*prepare_b9_native.py*' -and $_.Name -eq 'python.exe' })
$taskNames = @('python.exe', 'pg_ctl.exe', 'rtk.exe', 'postgres.exe')
$taskProcesses | Where-Object { $_.Name -in $taskNames } | Select-Object Name, ProcessId, ParentProcessId | ConvertTo-Json -Compress
$taskLaunchers | Select-Object Name, ProcessId, ParentProcessId | ConvertTo-Json -Compress
