"""Final evidence inventory and resource summary, without executing scenarios."""
import json
import subprocess
from datetime import datetime,timezone
from lab_control import HERE,lab

scenarios={
    'R1-06':('r106-prospective-01','scenario-result.json'),
    'R2-09 uncertain_meta':('r209-uncertain-01','scenario-result.json'),
    'R2-09 slow_meta':('r209-slow-01','scenario-result.json'),
    'R1-04':('r104-passive-01','scenario-result.json'),
    'R2-04':('r204-intact-01','scenario-result.json')}
results={name:dict(status=json.loads((HERE/folder/file).read_text())['status'],
    authoritative_result=folder+'/'+file) for name,(folder,file) in scenarios.items()}
resources=[]
for path in sorted(HERE.glob('*/resources.jsonl')):
    samples=0;physical=[];commit=[];stages=set()
    with path.open(encoding='utf-8') as f:
        for line in f:
            r=json.loads(line);samples+=1;stages.add(r['stage'])
            physical.append(r['memory']['available_physical']);commit.append(r['memory']['available_pagefile'])
    folder=path.parent
    execution=json.loads((folder/'execution-receipt.json').read_text())
    assert execution['database_removed'] and execution['clients_after_child']==[]
    pglog=(folder/'postgres-attempt.log').read_text(encoding='utf-8',errors='replace')
    if 'out of memory' in pglog.lower():raise ValueError('OOM_PRESENT:'+folder.name)
    resources.append(dict(attempt=folder.name,kind=execution['kind'],samples=samples,stages=sorted(stages),
        min_available_physical=min(physical),min_available_commit=min(commit),
        owned_database_removed=True,clients_after_child=[],postgres_oom_observed=False))
archives=json.loads((HERE/'verification-archives.json').read_text())
for item in archives:
    assert lab.sha(HERE/item['receipt'])==item['receipt_sha256']
    assert all(lab.sha(HERE/item['source_directory']/name)==sha for name,sha in item['sources'].items())
service=subprocess.run(['rtk','proxy','powershell','-NoProfile','-Command',
    'Get-Service -Name W32Time | Format-List Name,Status,StartType'],capture_output=True,text=True,check=True)
lab.write(HERE/'post-host-check.json',dict(at_utc=datetime.now(timezone.utc).isoformat(),
    service_read_only=service.stdout,host_service_mutation=False))
lab.write(HERE/'resources-summary.json',dict(attempts=resources,monitoring='BEFORE_DURING_AFTER_EACH_OWNED_EXECUTION',
    historical_oom_cause='UNRESOLVED; NEW_SUCCESS_IS_NOT_A_CAUSAL_EXPLANATION'))
latest=sorted(HERE.glob('offline-validation-*.json'))[-1]
controls=json.loads(latest.read_text());assert controls['successful']
regressions=json.loads((HERE/'sequential-regressions.json').read_text())
assert regressions['status']=='ACCREDITED'
summary=dict(scenarios=results,offline_controls=dict(tests=controls['tests'],receipt=latest.name),
    native_postgresql_adapter_tests=4,regression_tests=sum(s['tests'] for s in regressions['suites']),
    regression_skipped=sum(s['skipped'] for s in regressions['suites']),
    all_attempt_databases_removed=True,host_service_mutation=False,commits=False,full_matrix=False,
    new_characterization=False,capacity_estimates=False,plan_closed=False,
    unresolved_decision='R1-04_PHYSICAL_FORECAST_SEQUENCE_NOT_OBSERVED; ACCEPT_LIMITATION_OR_DECIDE_COMPATIBLE_FIXTURE')
lab.write(HERE/'execution-summary.json',summary)
print(json.dumps(summary),flush=True)
