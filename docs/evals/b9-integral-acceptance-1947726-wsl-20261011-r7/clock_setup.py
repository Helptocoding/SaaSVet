"""Own the temporary WSL synchronization pause and prove restoration."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
PREVIOUS=Path('C:/Users/LAP/AppData/Local/Temp/b9-clock-isolation-gp1mngqo')
BASELINE=Path('C:/Users/LAP/AppData/Local/Temp/b9-clock-diagnostic-ry8snt_d')
WORK='/home/lap/b9i-wsl-1947726-20261011-r7'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(name,data):
    (HERE/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def configuration():
    return json.loads((HERE/'clock-guardian-location.json').read_text(encoding='utf-8'))

def create():
    assert not (HERE/'clock-guardian-location.json').exists()
    assert json.loads((HERE/'interpreter-preflight.json').read_text(encoding='utf-8'))['state']=='PASS'
    p=Path(tempfile.mkdtemp(prefix='b9-clock-isolation-r7-'))
    linux='/mnt/c'+p.as_posix()[2:]
    for name in ('probe.py','observe.py'):
        shutil.copy2(PREVIOUS/name,p/name)
    guard=(PREVIOUS/'guard.py').read_text(encoding='utf-8').replace('<10800','<21600')
    guard=guard.replace('subprocess.run(list(args),',"subprocess.run([str(p/'rtk-linux'),'proxy',*args],")
    (p/'guard.py').write_text(guard,encoding='utf-8',newline='\n')
    code="import shutil,os; shutil.copy2("+repr(WORK+'/tools/rtk')+','+repr(linux+'/rtk-linux')+"); os.chmod("+repr(linux+'/rtk-linux')+",0o755)"
    subprocess.run(['rtk','proxy','wsl.exe','-d','Ubuntu-24.04','--exec',WORK+'/tools/rtk','proxy',
        WORK+'/venv/bin/python','-B','-c',code],check=True)
    save('clock-guardian-location.json',{'windows':p.as_posix(),'linux':linux,
        'lease_seconds':21600,'guard_source_sha256':digest(p/'guard.py'),'guard_rtk_sha256':digest(p/'rtk-linux')})
    print(json.dumps(configuration()))

def record():
    config=configuration();p=Path(config['windows'])
    assert not (HERE/'clock-control.json').exists()
    result=json.loads((p/'summary.json').read_text(encoding='utf-8'))
    assert result['exit_codes']=={'windows':0,'wsl':0}
    assert all(v['elapsed_seconds']>=120 and v['max_absolute_wall_minus_monotonic_seconds']<=1 for v in result['surfaces'].values())
    assert json.loads((p/'service-paused.json').read_text(encoding='utf-8'))['state']=='PASS'
    assert not (p/'service-restored.json').exists()
    for label,folder in [('baseline',BASELINE),('paused',p)]:
        target=HERE/'clock-diagnostics'/label;target.mkdir(parents=True)
        for name in ('probe.py','observe.py','windows.jsonl','wsl.jsonl','summary.json'):
            shutil.copy2(folder/name,target/name)
        if label=='paused':
            for name in ('guard.py','service-before.json','service-stop-command.json','service-paused.json'):
                shutil.copy2(folder/name,target/name)
    before=json.loads((p/'service-before.json').read_text(encoding='utf-8'))
    save('clock-control.json',{'guard_pid':before['pid'],'guard_source_linux':config['linux']+'/guard.py',
        'guard_rtk_linux':config['linux']+'/rtk-linux','guard_source_sha256':digest(p/'guard.py'),
        'guard_rtk_sha256':digest(p/'rtk-linux'),'initial_active':before['initial_active'],
        'initial_enabled':before['initial_enabled'],'lease_seconds':21600,
        'authorized_temporary_state':'systemd-timesyncd.service inactive; enabled state unchanged',
        'restoration_required':True,'windows_W32Time_untouched':True,
        'isolation_summary_sha256':digest(p/'summary.json'),
        'paused_max_skew_seconds':result['surfaces']['wsl']['max_absolute_wall_minus_monotonic_seconds'],
        'observation_limit':'120-second observation; original continuous clock monitor remains authoritative'})
    print('CLOCK_OBSERVATION_PASS')

def restore():
    config=configuration();p=Path(config['windows'])
    (p/'restore.request').write_text('Restore at campaign closure\n',encoding='utf-8')
    start=time.monotonic()
    while not (p/'service-restored.json').exists() and time.monotonic()-start<30:
        time.sleep(.5)
    result=json.loads((p/'service-restored.json').read_text(encoding='utf-8'))
    assert result['state']=='PASS',result
    target=HERE/'clock-diagnostics'/'restoration';target.mkdir(parents=True)
    for name in ('service-restore-command.json','service-restored.json','restore.request'):
        shutil.copy2(p/name,target/name)
    save('clock-restoration.json',result)
    print('CLOCK_RESTORATION_PASS')

if __name__=='__main__':
    {'create':create,'record':record,'restore':restore}[sys.argv[1]]()
