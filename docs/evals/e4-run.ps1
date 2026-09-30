param([ValidateSet('targeted','regression','corpus','checks','profile')][string]$Mode,
  [ValidateRange(1,3)][int]$Shard=1,
  [ValidateSet('base','blocked_llm','meta_slow','duplicate','saturation')][string]$Scenario='base',
  [int]$Port=35441)
$ErrorActionPreference='Stop'
$e4root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$e4python='C:/Users/LAP/AppData/Local/Temp/vet-b8b-locked/Scripts/python.exe'
$e4pg='C:/Users/LAP/AppData/Local/Temp/vet-b8b-pg16-bin/pgsql/bin'
$env:SECRET_KEY='e4-local-test-disposable-key'
$env:DEBUG='False'; $env:ENVIRONMENT='dev'; $env:DISABLE_SENTRY='True'
$env:SENTRY_DSN=''; $env:REDIS_URL=''; $env:DISCORD_WEBHOOK_URL=''
$env:E4_SELECTOR=''
$env:DATABASE_URL="postgresql://e4@127.0.0.1:$Port/test_e4_template"
Set-Location -LiteralPath (Join-Path $e4root 'backend')
if ($Mode -eq 'profile') {
  $e4db="test_e4_postfix_$Scenario"
  $e4out=Join-Path $PSScriptRoot "e4-postfix-$Scenario.json"
  if (Test-Path -LiteralPath $e4out) { throw 'Refusing to overwrite receipt' }
  rtk proxy "$e4pg/createdb.exe" -h 127.0.0.1 -p $Port -U e4 -T test_e4_template $e4db
  if ($LASTEXITCODE -ne 0) { throw 'Profile clone failed' }
  $env:DATABASE_URL="postgresql://e4@127.0.0.1:$Port/$e4db"
  $ErrorActionPreference='Continue'
  rtk proxy $e4python -m apps.agent.tests.b9e_profile --scenario $Scenario --output $e4out *> (Join-Path $PSScriptRoot "e4-postfix-$Scenario-driver.log")
  $ErrorActionPreference='Stop'
  if ($LASTEXITCODE -ne 0) { throw 'Profile execution failed' }
  $e4receipt=Get-Content -LiteralPath $e4out -Raw | ConvertFrom-Json
  Write-Output ($e4receipt | Select-Object scenario,healthy_claim,safety_dispatch,outbox_dispatch,gates,technical_pass | ConvertTo-Json -Depth 6)
  rtk proxy $e4python -m apps.agent.tests.e4_collect --current-selector --receipt $e4out --output (Join-Path $PSScriptRoot "e4-postfix-$Scenario.analysis.json")
  if ($LASTEXITCODE -ne 0) { throw 'Collection failed' }
  if (!$e4receipt.technical_pass) { throw 'STOP: justified candidate failed frozen profile; no further tuning' }
} else {
  $e4db="test_b8b_e4_$Mode"
  $e4prefix=Join-Path $PSScriptRoot "e4-$Mode"
  if ($Mode -eq 'regression') {
    $e4db="test_b8b_e4_regression_$Shard"
    $e4prefix=Join-Path $PSScriptRoot "e4-regression-$Shard"
  }
  if (Test-Path -LiteralPath "$e4prefix.exit.json") { throw 'Refusing to overwrite validation' }
  if ($Mode -eq 'checks') {
    rtk proxy "$e4pg/createdb.exe" -h 127.0.0.1 -p $Port -U e4 -T test_e4_template $e4db
    if ($LASTEXITCODE -ne 0) { throw 'Checks clone failed' }
    rtk proxy $e4python -m apps.agent.tests.run_b9a_acceptance --suite checks --database $e4db --output $e4prefix
  } else {
    rtk proxy "$e4pg/createdb.exe" -h 127.0.0.1 -p $Port -U e4 -T test_e4_template $e4db
    if ($LASTEXITCODE -ne 0) { throw 'Validation clone failed' }
    $e4selection = if ($Mode -eq 'corpus') { 'e4-b9e-corpus-selected.json' } elseif ($Mode -eq 'regression') { "e4-regression-$Shard-selected.json" } else { "e4-$Mode-selected.json" }
    rtk proxy $e4python -m apps.agent.tests.run_b9a_acceptance --suite targeted --database $e4db --ids-file (Join-Path $PSScriptRoot $e4selection) --output $e4prefix
  }
  if ($LASTEXITCODE -ne 0) { throw "Validation failed: $Mode" }
  rtk read "$e4prefix.exit.json"
}
