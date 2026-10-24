$ErrorActionPreference = 'Stop'
$taskLauncher = Get-CimInstance Win32_Process -Filter 'ProcessId = 42208'
$taskParent = Get-CimInstance Win32_Process -Filter 'ProcessId = 33516'
if ($null -eq $taskLauncher -or $null -eq $taskParent) { throw 'Owned launcher identity unavailable' }
if ($taskLauncher.Name -ne 'rtk.exe' -or $taskLauncher.ParentProcessId -ne 33516) { throw 'Launcher identity differs' }
if ($taskParent.Name -ne 'python.exe' -or $taskParent.CommandLine -notlike '*prepare_b9_native.py*') { throw 'Parent is not this preparation' }
if ($taskLauncher.CommandLine -notlike '*pg_ctl.exe*' -or $taskLauncher.CommandLine.Replace('\','/') -notlike '*inbox-readiness-2026-10-22/runtime/b9/pgdata*') { throw 'Private pg_ctl scope differs' }
$taskReceipt = @{ state='OWNED_WRAPPER_RELEASED'; wrapper_pid=42208; parent_pid=33516; postmaster_pid=28828; server_terminated=$false; formal_profiles_executed=0; cause='RTK wrapper retains inherited server output pipe after pg_ctl exits' }
$taskReceipt | ConvertTo-Json | Set-Content -LiteralPath 'docs/evals/inbox-readiness-2026-10-22/b9-launcher-incident.json' -Encoding UTF8
Stop-Process -Id 42208 -Force
$taskBadObservers = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like '*-Command*Get-CimInstance Win32_Process*Where-Object*{ .Name*' })
foreach ($taskObserver in $taskBadObservers) { Stop-Process -Id $taskObserver.ProcessId -Force }
Write-Output 'OWNED_LAUNCHER_RELEASED; PRIVATE_SERVER_PRESERVED'
