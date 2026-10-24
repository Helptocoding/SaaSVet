"""Resume evidence staging after verifying and retiring an abandoned index lock."""
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from deliver_wsl import REPO,SHARED,run,staged_blobs,digest,save

def main():
    assert json.loads((HERE/'delivery-verification.json').read_text())['state']=='VERIFYING'
    assert not (HERE/'delivery-recovery.json').exists()
    manifest=json.loads((HERE/'preservation-manifest.json').read_text())
    assert not [n for n,r in manifest['files'].items() if digest((HERE/n).read_bytes())!=r['sha256']]
    powershell="Get-CimInstance Win32_Process -Filter \"Name = 'git.exe'\" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    observed=subprocess.check_output(['rtk','proxy','powershell.exe','-NoProfile','-Command',powershell],text=True)
    processes=json.loads(observed) if observed.strip() else []
    if isinstance(processes,dict):processes=[processes]
    evidence=[]
    for process in processes:
        cmd=process['CommandLine'] or ''
        assert ' diff' in cmd or ' status' in cmd, 'Unexpected Git operation; do not retire lock'
        evidence.append({'pid':process['ProcessId'],'parent_pid':process['ParentProcessId'],
            'operation':'diff' if ' diff' in cmd else 'status'})
    # WSL has restarted since cleanup; check its process list immediately as well.
    config=json.loads((HERE/'clock-guardian-location.json').read_text())
    linux=subprocess.check_output(['rtk','proxy','wsl.exe','-d','Ubuntu-24.04','--exec',
        config['linux']+'/rtk-linux','proxy','ps','-eo','comm'],text=True)
    assert not any(line.strip() in ('git','git.exe') for line in linux.splitlines())
    lock=(REPO/'.git/index.lock').resolve()
    backup=(HERE/'diagnostics/abandoned-index-lock.bin').resolve()
    assert lock==Path('C:/Users/LAP/Desktop/VeterinariaSaaS/.git/index.lock').resolve()
    assert backup.is_relative_to(HERE.resolve()) and not backup.exists()
    stat=lock.stat()
    assert stat.st_size==0 and stat.st_mtime==1791773877.0930636
    assert time.time()-stat.st_mtime>15*60
    baseline=json.loads((HERE/'index-before-delivery.json').read_text())
    current_names=set(filter(None,run('git','diff','--cached','--name-only','-z').decode().split('\0')))
    assert set(baseline).issubset(current_names)
    current=staged_blobs(current_names)
    assert not [n for n,h in baseline.items() if n not in SHARED and digest(current[n])!=h]
    lock.rename(backup)
    assert not lock.exists() and backup.stat().st_size==0
    save('delivery-recovery.json',{'state':'RESUMING_STAGING','initial_failure':'Git add refused existing .git/index.lock',
        'package_and_two_recovery_checks_already_passed':True,'package_manifest_unchanged':True,
        'retired_lock':{'original':str(lock),'backup':str(backup),'bytes':0,'mtime':stat.st_mtime,
            'age_seconds':time.time()-stat.st_mtime,'sha256':digest(backup.read_bytes())},
        'windows_git_processes_at_retirement':evidence,'wsl_git_processes_at_retirement':0,
        'no_git_process_terminated':True,'prior_staged_paths_checked':len(baseline),
        'script_added_after_package':True,'formal_campaign_retried':False})
    selection=json.loads((HERE/'git-selection.json').read_text())['paths']
    extras=[HERE/'diagnostics/finish_delivery.py',backup,HERE/'delivery-recovery.json']
    selection=sorted(set(selection)|{p.relative_to(REPO).as_posix() for p in extras})
    save('git-selection.json',{'paths':selection,'explicit':True,'raw_logs_excluded_from_git':True,
        'postpackage_delivery_recovery_artifacts':[p.relative_to(HERE).as_posix() for p in extras]})
    run('git','add','--pathspec-from-file=-','--pathspec-file-nul',stdin=('\0'.join(selection)+'\0').encode())
    run('git','diff','--cached','--check')
    staged=staged_blobs(set(selection)|current_names)
    prior_drift=[n for n,b in current.items() if n not in SHARED and n not in selection and staged[n]!=b]
    prior_drift += [n for n,h in baseline.items() if n not in SHARED and digest(staged[n])!=h]
    mismatches=[];normalized=[]
    for name in selection:
        local=(REPO/name).read_bytes()
        if local!=staged[name]:
            if name in ('.gitattributes','.gitignore') and local.replace(b'\r\n',b'\n')==staged[name].replace(b'\r\n',b'\n'):
                normalized.append(name)
            else:mismatches.append(name)
    drift=[n for n,r in manifest['files'].items() if digest((HERE/n).read_bytes())!=r['sha256']]
    assert not prior_drift and not mismatches and not drift,(prior_drift,mismatches,drift)
    recovery=json.loads((HERE/'delivery-recovery.json').read_text());recovery['state']='PASS'
    save('delivery-recovery.json',recovery)
    proof=json.loads((HERE/'preservation-verification.json').read_text())
    save('delivery-verification.json',{'state':'PASS','selected_paths':len(selection),
        'evidence_git_blobs_equal_local_bytes':True,'root_text_normalized_paths':normalized,
        'prior_staged_paths_checked':len(baseline),'prior_staged_drift_outside_three_delivery_files':prior_drift,
        'evidence_drift':drift,'cached_diff_check_exit_code':0,
        'recovered_members':proof['internal_restore']['recovered_members'],
        'package_sha256':manifest['archive_sha256'],
        'postpackage_delivery_recovery_artifacts':[p.relative_to(HERE).as_posix() for p in extras],
        'commits_created':0,'pushes_performed':0})
    final=[(HERE/n).relative_to(REPO).as_posix() for n in ('delivery-recovery.json','delivery-verification.json')]
    run('git','add','--',*final)
    for name in final:
        assert run('git','show',':'+name)==(REPO/name).read_bytes()
    run('git','diff','--cached','--check')
    print(json.dumps({'delivery':'PASS','selected_paths':len(selection),'recovered_members':proof['internal_restore']['recovered_members']}))

if __name__=='__main__':
    main()
