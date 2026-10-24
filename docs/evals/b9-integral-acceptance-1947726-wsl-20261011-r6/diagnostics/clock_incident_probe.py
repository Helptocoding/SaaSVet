"""Read Windows power/time events after STOP; no configuration changes."""
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parents[1]
SCRIPT=r'''
$clockStart=[DateTime]::Parse('2026-10-12T03:58:30Z').ToLocalTime()
$clockEnd=[DateTime]::Parse('2026-10-12T04:02:30Z').ToLocalTime()
$clockEvents=Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$clockStart;EndTime=$clockEnd;Id=1,42,107,506,507} -ErrorAction SilentlyContinue
$clockRows=@($clockEvents | Where-Object {$_.ProviderName -in @('Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter','Microsoft-Windows-Kernel-General')} | ForEach-Object {
    $clockXml=[xml]$_.ToXml()
    $clockData=@{}
    foreach($clockItem in $clockXml.Event.EventData.Data){$clockData[$clockItem.Name]=$clockItem.InnerText}
    [pscustomobject]@{id=$_.Id;provider=$_.ProviderName;utc=$_.TimeCreated.ToUniversalTime().ToString('o');data=$clockData}
})
ConvertTo-Json -InputObject $clockRows -Depth 6 -Compress
'''

if __name__=='__main__':
    assert (HERE/'STOP.json').exists()
    target=HERE/'windows-clock-power-events.json'
    assert not target.exists()
    result=subprocess.run(['rtk','proxy','powershell.exe','-NoProfile','-Command',SCRIPT],
        stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',errors='replace')
    try:events=json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:events=None
    data={'state':'RECORDED' if result.returncode==0 and events is not None else 'DIAGNOSTIC_UNAVAILABLE',
        'created_after_stop':True,'read_only':True,'query_utc_start':'2026-10-12T03:58:30Z',
        'query_utc_end':'2026-10-12T04:02:30Z','exit_code':result.returncode,
        'stderr':result.stderr,'events':events,'application_tests_executed':False,'configuration_changed':False}
    target.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False))
