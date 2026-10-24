import json,subprocess,sys,time
from pathlib import Path
p=Path(__file__).resolve().parent
assert p.drive.lower()=='c:'
linux='/mnt/c'+str(p).replace('\\','/')[2:]+'/probe.py'
rtk='C:/Users/LAP/.local/bin/rtk.exe'
commands={'windows':[rtk,'proxy',sys.executable,'-B',str(p/'probe.py')],'wsl':[rtk,'proxy','wsl.exe','-d','Ubuntu-24.04','--exec','/usr/bin/python3','-B',linux]}
handles={name:(p/(name+'.jsonl')).open('wb') for name in commands}
processes={name:subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=handles[name],stderr=subprocess.STDOUT) for name,args in commands.items()}
print('CLOCK_DIAGNOSTIC_STARTED '+str(p),flush=True)
exits={name:proc.wait(timeout=180) for name,proc in processes.items()}
for handle in handles.values():handle.close()
summary={'type':'read-only clock observation, not an acceptance campaign','duration_target_seconds':120,'project_tests_executed':False,'system_configuration_changed':False,'exit_codes':exits,'surfaces':{}}
for name in commands:
    lines=[json.loads(line) for line in (p/(name+'.jsonl')).read_text(encoding='utf-8').splitlines()]
    rows=[r for r in lines if r.get('kind')=='sample']
    summary['surfaces'][name]={'metadata':lines[0],'samples':len(rows),'elapsed_seconds':rows[-1]['elapsed_seconds'],'max_absolute_wall_minus_monotonic_seconds':max(abs(r['wall_minus_monotonic_seconds']) for r in rows),'first':rows[0],'last':rows[-1]}
(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary),flush=True)
