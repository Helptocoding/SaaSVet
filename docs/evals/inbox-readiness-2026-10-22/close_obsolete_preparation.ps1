$ErrorActionPreference = 'Stop'
$taskProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = 33516'
if ($null -ne $taskProcess) {
    if ($taskProcess.Name -ne 'python.exe' -or $taskProcess.ParentProcessId -ne 22416 -or $taskProcess.CommandLine -notlike '*prepare_b9_native.py*') { throw 'Obsolete preparation identity differs' }
    Stop-Process -Id 33516 -Force
}
Write-Output 'OBSOLETE_PREPARATION_CLOSED; NO_PROCESS_TREE_KILL'
