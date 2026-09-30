# Finish the offline tail of the interrupted first cleanup, without restarting PostgreSQL.
$ErrorActionPreference='Stop'
$e4expected='C:\Users\LAP\AppData\Local\Temp\vet-e4-pg16-data'
$e4data=(Resolve-Path -LiteralPath $e4expected).Path
if ($e4data -ine $e4expected) { throw 'Unsafe E4 data directory' }
$e4out=Join-Path $PSScriptRoot 'e4-cleanup.json'
if (Test-Path -LiteralPath $e4out) { throw 'Refusing to overwrite cleanup evidence' }
$e4pg='C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin'
rtk proxy "$e4pg/pg_isready.exe" -h 127.0.0.1 -p 35441
$e4readyExit=$LASTEXITCODE
if ($e4readyExit -ne 2 -or (Test-Path -LiteralPath (Join-Path $e4data 'postmaster.pid'))) { throw 'Own instance is not stopped' }
$e4postgres=@(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'")
if (@($e4postgres | Where-Object { $_.ProcessId -eq 22496 -or $_.CommandLine -match 'vet-e4-pg16-data' }).Count -ne 0) { throw 'Own PostgreSQL process remains' }
$e4python=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
 $_.CommandLine -match 'apps\.agent\.tests\.(e4_profile|b9e_profile|e4_selection_process)' -or
 $_.CommandLine -match 'e4-(targeted|regression|postfix|diagnostic).*(selected|json|role)' })
if ($e4python.Count -ne 0) { throw 'E4 test process remains' }
$e4log='C:/Users/LAP/AppData/Local/Temp/vet-e4-pg16.log'
$e4sha=[System.Security.Cryptography.SHA256]::Create()
try { $e4logHash=([BitConverter]::ToString($e4sha.ComputeHash([IO.File]::ReadAllBytes($e4log)))).Replace('-','').ToLower() }
finally { $e4sha.Dispose() }
$e4lifecycle=Get-Content -LiteralPath $e4log -Encoding UTF8 | Where-Object { $_ -match ' LOG: (starting PostgreSQL|listening on|database system is ready|database system is shut down|database system was interrupted|database system was not properly shut down|redo starts|redo done|received fast shutdown|shutting down)' }
$e4lifecycle | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'e4-postgresql-lifecycle.json') -Encoding UTF8
if ((Resolve-Path -LiteralPath $e4data).Path -ine $e4expected) { throw 'Unsafe delete target' }
Remove-Item -LiteralPath $e4data -Recurse -Force
Remove-Item -LiteralPath $e4log -Force
[ordered]@{schema='e4-cleanup-v2';first_cleanup_exit=1;
 first_cleanup_error='Get-FileHash unavailable after verified database removal and PostgreSQL stop';
 initial_preflight_receipt_available=$false;
 initial_script_verified=@('own data directory/port','zero prepared transactions','zero test clients',
   'only whitelisted databases','zero remaining test databases','stopped own PostgreSQL process tree');
 remaining_test_databases=0;pg_isready_exit=$e4readyExit;server_stopped=$true;
 own_postmaster_pid=22496;remaining_e4_python_processes=$e4python.Count;
 postgres_process_ids_after=@($e4postgres | ForEach-Object { [int]$_.ProcessId });
 data_directory_removed=!(Test-Path -LiteralPath $e4data);raw_log_removed=!(Test-Path -LiteralPath $e4log);
 raw_log_sha256=$e4logHash;production_accessed=$false;
 evidence_note='Initial script reached the hash step after all its assertions; offline resume verifies stop and finishes artifact closure. Initial database names/PIDs were not persisted and are not reconstructed.'
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $e4out -Encoding UTF8
rtk read $e4out
