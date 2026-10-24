import json,os,signal,subprocess,time
from pathlib import Path
p=Path(__file__).resolve().parent
service='systemd-timesyncd.service'
def run(*args,check=True):
    result=subprocess.run(list(args),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if check and result.returncode:
        raise RuntimeError(str(args)+': '+result.stdout)
    return {'argv':list(args),'exit_code':result.returncode,'output':result.stdout}
def save(name,data):
    (p/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
def status():
    return run('systemctl','show',service,'--property=ActiveState,SubState,UnitFileState,MainPID')
if (p/'service-before.json').exists():
    raise RuntimeError('Refusing duplicate service intervention')
before=status()
initial_active=run('systemctl','is-active',service,check=False)['output'].strip()=='active'
initial_enabled=run('systemctl','is-enabled',service,check=False)['output'].strip()
save('service-before.json',{'status':before,'initial_active':initial_active,'initial_enabled':initial_enabled,'pid':os.getpid(),'windows_W32Time_untouched':True})
requested=False
def halt(signum,frame):
    global requested
    requested=True
signal.signal(signal.SIGTERM,halt)
signal.signal(signal.SIGINT,halt)
started=time.monotonic()
try:
    if initial_active:
        save('service-stop-command.json',run('systemctl','stop',service))
    paused=status()
    assert 'ActiveState=inactive' in paused['output']
    save('service-paused.json',{'state':'PASS','status':paused,'pid':os.getpid(),'unit_enabled_state_unchanged':run('systemctl','is-enabled',service,check=False)['output'].strip()==initial_enabled,'restoration_required':initial_active})
    print('CLOCK_SERVICE_PAUSED '+str(os.getpid()),flush=True)
    while not requested and not (p/'restore.request').exists() and time.monotonic()-started<10800:
        time.sleep(1)
finally:
    if initial_active:
        restored=run('systemctl','start',service,check=False)
        save('service-restore-command.json',restored)
    after=status()
    active=run('systemctl','is-active',service,check=False)['output'].strip()=='active'
    enabled=run('systemctl','is-enabled',service,check=False)['output'].strip()
    save('service-restored.json',{'state':'PASS' if active==initial_active and enabled==initial_enabled else 'FAIL','status':after,'active_matches_original':active==initial_active,'enabled_matches_original':enabled==initial_enabled,'windows_W32Time_untouched':True})
    print('CLOCK_SERVICE_RESTORED',flush=True)
