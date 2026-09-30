param([int]$Port=35441)
$ErrorActionPreference='Stop'
$e4pg='C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin'
$e4expected='C:\Users\LAP\AppData\Local\Temp\vet-e4-pg16-data'
$e4data=(Resolve-Path -LiteralPath $e4expected).Path
if ($e4data -ine $e4expected) { throw 'Unsafe E4 data directory' }
$e4out=Join-Path $PSScriptRoot 'e4-cleanup.json'
if (Test-Path -LiteralPath $e4out) { throw 'Refusing to overwrite cleanup evidence' }
$e4postmaster=[int](Get-Content -LiteralPath (Join-Path $e4data 'postmaster.pid') -TotalCount 1)
$e4processes=@(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'")
$e4ownedPids=@($e4postmaster)
do {
 $e4children=@($e4processes | Where-Object { $_.ParentProcessId -in $e4ownedPids -and $_.ProcessId -notin $e4ownedPids } | ForEach-Object { [int]$_.ProcessId })
 $e4ownedPids += $e4children
} while ($e4children.Count -gt 0)
$e4otherPids=@($e4processes | Where-Object { $_.ProcessId -notin $e4ownedPids } | ForEach-Object { [int]$_.ProcessId })
$e4meta=rtk proxy "$e4pg/psql.exe" -h 127.0.0.1 -p $Port -U e4 -d postgres -t -A -c "SELECT json_build_object('data_directory', current_setting('data_directory'), 'port', current_setting('port'), 'prepared', (SELECT count(*) FROM pg_prepared_xacts), 'databases', (SELECT json_agg(datname ORDER BY datname) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')), 'activity', (SELECT json_agg(json_build_object('database',datname,'pid',pid,'state',state,'wait_type',wait_event_type)) FROM pg_stat_activity WHERE datname LIKE 'test_e4_%' OR datname LIKE 'test_b8b_e4_%'))"
if ($LASTEXITCODE -ne 0) { throw 'Cleanup preflight failed' }
$e4before=$e4meta | ConvertFrom-Json
if ([IO.Path]::GetFullPath($e4before.data_directory) -ine $e4data -or [int]$e4before.port -ne $Port) { throw 'Wrong PostgreSQL instance' }
if ($e4before.prepared -ne 0) { throw 'Prepared transactions need investigation' }
if (@($e4before.activity | Where-Object { $null -ne $_ }).Count -ne 0) { throw 'Own test clients remain; preserve databases' }
$e4before | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'e4-cleanup-preflight.json') -Encoding UTF8
$e4owned=@('test_e4_template','test_e4_reproduction','test_e4_baseline','test_e4_baseline_120',
 'test_e4_no_noisy','test_e4_fast_provider','test_e4_batch_3','test_e4_poll_01','test_e4_efficient','test_e4_fair',
 'test_e4_postfix_base','test_e4_postfix_blocked_llm','test_e4_postfix_meta_slow','test_e4_postfix_duplicate','test_e4_postfix_saturation',
 'test_b8b_e4_targeted','test_b8b_e4_checks','test_b8b_e4_regression_1','test_b8b_e4_regression_2','test_b8b_e4_regression_3')
foreach ($e4db in $e4before.databases) {
 if ($e4db -notin $e4owned) { throw "Unrecognized database; preserve instance: $e4db" }
 rtk proxy "$e4pg/dropdb.exe" -h 127.0.0.1 -p $Port -U e4 $e4db
 if ($LASTEXITCODE -ne 0) { throw "Unable to drop own test database $e4db" }
}
$e4remaining=rtk proxy "$e4pg/psql.exe" -h 127.0.0.1 -p $Port -U e4 -d postgres -t -A -c "SELECT count(*) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')"
if ($LASTEXITCODE -ne 0 -or [int]$e4remaining -ne 0) { throw 'Databases remain' }
rtk proxy "$e4pg/pg_ctl.exe" -D $e4data -m fast -w stop
if ($LASTEXITCODE -ne 0) { throw 'Unable to stop E4 PostgreSQL' }
rtk proxy "$e4pg/pg_isready.exe" -h 127.0.0.1 -p $Port
$e4readyExit=$LASTEXITCODE
if ($e4readyExit -ne 2 -or (Test-Path -LiteralPath (Join-Path $e4data 'postmaster.pid'))) { throw 'PostgreSQL did not stop' }
$e4processesAfter=@(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" | ForEach-Object { [int]$_.ProcessId })
$e4remainingPids=@($e4ownedPids | Where-Object { $_ -in $e4processesAfter })
if ($e4remainingPids.Count -ne 0) { throw 'Own PostgreSQL processes remain; preserve data directory' }
$e4log='C:/Users/LAP/AppData/Local/Temp/vet-e4-pg16.log'
$e4sha=[System.Security.Cryptography.SHA256]::Create()
try { $e4logHash=([BitConverter]::ToString($e4sha.ComputeHash([IO.File]::ReadAllBytes($e4log)))).Replace('-','').ToLower() }
finally { $e4sha.Dispose() }
# Preserve technical lifecycle only; SQL/error detail can contain fixture content.
$e4lifecycle=Get-Content -LiteralPath $e4log -Encoding UTF8 | Where-Object { $_ -match ' LOG: (starting PostgreSQL|listening on|database system is ready|database system is shut down|database system was interrupted|database system was not properly shut down|redo starts|redo done|received fast shutdown|shutting down)' }
$e4lifecycle | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'e4-postgresql-lifecycle.json') -Encoding UTF8
# Check the resolved absolute target again immediately before recursive deletion.
if ((Resolve-Path -LiteralPath $e4data).Path -ine $e4expected) { throw 'Unsafe delete target' }
Remove-Item -LiteralPath $e4data -Recurse -Force
Remove-Item -LiteralPath $e4log -Force
[ordered]@{schema='e4-cleanup-v1';before=$e4before;dropped_databases=$e4before.databases;
 remaining_test_databases=0;pg_isready_exit=$e4readyExit;server_stopped=$true;
 stopped_postmaster_pid=$e4postmaster;own_process_ids=$e4ownedPids;remaining_own_process_ids=$e4remainingPids;
 unrelated_process_ids_before=$e4otherPids;unrelated_process_ids_preserved=@($e4otherPids | Where-Object { $_ -in $e4processesAfter });
 data_directory_removed=!(Test-Path -LiteralPath $e4data);raw_log_removed=!(Test-Path -LiteralPath $e4log);
 raw_log_sha256=$e4logHash;production_accessed=$false} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $e4out -Encoding UTF8
rtk read $e4out
