param(
    [ValidateSet('checks','targeted','regression','diagnostic','profile')][string]$Suite = 'targeted',
    [string]$Receipt = 'targeted-v3',
    [string]$Scenario = 'base',
    [string]$Labels = '',
    [string]$Database = ''
)
$ErrorActionPreference = 'Stop'
$monoPython = 'C:/Users/LAP/AppData/Local/Temp/vet-b8b-locked/Scripts/python.exe'
$monoRoot = (Resolve-Path "$PSScriptRoot/../..").Path
$env:SECRET_KEY = 'w1-mono-local-disposable-key-at-least-32-chars'
$env:DEBUG = 'False'
$env:ENVIRONMENT = 'dev'
$env:DISABLE_SENTRY = 'True'
$env:SENTRY_DSN = ''
$env:REDIS_URL = ''
$env:DISCORD_WEBHOOK_URL = ''
$env:DATABASE_URL = 'postgresql://w1mono@127.0.0.1:35442/test_b8b_w1_mono_template'
Set-Location "$monoRoot/backend"
if ($Suite -in @('diagnostic','profile')) {
    $monoDb = "test_b8b_w1_mono_$Suite"
    $env:DATABASE_URL = "postgresql://w1mono@127.0.0.1:35442/$monoDb"
    if ($Suite -eq 'diagnostic') {
        & rtk proxy $monoPython -X utf8 -m apps.agent.tests.w1_mono_diagnostic --scenario $Scenario --output "../docs/evals/w1-mono/$Receipt.json"
    } else {
        & rtk proxy $monoPython -X utf8 -m apps.agent.tests.b9e_profile --scenario $Scenario --output "../docs/evals/w1-mono/$Receipt.json"
    }
} else {
    $monoDb = if ($Suite -eq 'checks') { 'test_b8b_w1_mono_template' } else { "test_b8b_w1_mono_$Suite" }
    $monoLabels = if ($Suite -eq 'regression') { 'regression-labels.json' } else { 'targeted-labels.json' }
    if ($Labels) { $monoLabels = $Labels }
    if ($Database) { $monoDb = $Database }
    $monoRunnerSuite = if ($Suite -eq 'checks') { 'checks' } else { 'targeted' }
    & rtk proxy $monoPython -X utf8 -m apps.agent.tests.run_b9a_acceptance --suite $monoRunnerSuite --database $monoDb --ids-file "../docs/evals/w1-mono/$monoLabels" --output "../docs/evals/w1-mono/$Receipt"
}
exit $LASTEXITCODE
