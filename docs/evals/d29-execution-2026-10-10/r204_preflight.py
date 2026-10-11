"""Read-only viability review. It never changes a host service."""
import json
import subprocess
from datetime import datetime,timezone
from lab_control import HERE,lab

if __name__=='__main__':
    service=subprocess.run(['rtk','proxy','powershell','-NoProfile','-Command',
        'Get-Service -Name W32Time | Format-List Name,Status,StartType'],capture_output=True,text=True,check=True)
    copied=json.loads((HERE/'r204-adaptation-seal.json').read_text())
    assert all(lab.sha(HERE/name)==v['sha256'] for name,v in copied.items())
    clocks={name:json.loads((HERE/name/'capture-clock/clock-receipt.json').read_text())['gate_passed']
        for name in ['r106-prospective-01','r209-uncertain-01','r209-slow-01','r104-passive-01']}
    assert all(clocks.values())
    value=dict(at_utc=datetime.now(timezone.utc).isoformat(),service_read_only=service.stdout,
        prior_strict_clock_results=clocks,preserved_special_sources=copied,
        clock_guard_sha256=lab.sha(HERE/'clock_guard.py'),host_service_mutation=False,
        viability='PROCEED_ONCE_WITH_INTACT_SERVICE_AND_ORIGINAL_STRICT_GUARD',
        longer_attempt_clock_validity='NOT_ASSUMED; DISCONTINUITY_INVALIDATES_AND_STOPS',physical_accreditation=False)
    lab.write(HERE/'r204-intact-preflight.json',value)
    print(json.dumps(value),flush=True)
