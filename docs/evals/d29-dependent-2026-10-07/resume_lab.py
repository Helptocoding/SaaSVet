"""Recover the owned stopped lab and retain the interrupted attempt as such."""
import hashlib
import json
import runpy
import socket
import subprocess
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
lab=runpy.run_path(str(HERE/'orchestration/lab.py'))
task,state=lab['session']()
cfg=state['config']
integrity=lab['integrity']()
with socket.socket() as sock:
    if sock.connect_ex(('127.0.0.1',int(cfg['PORT'])))==0:
        raise RuntimeError('Lab already listening; do not start a second server')
for name in ('pg.stdout','pg.stderr'):
    source=task/name
    if source.exists():
        (HERE/('interruption-original-'+name+'.log')).write_bytes(source.read_bytes())
start=task/'resume.ps1'
start.write_text("$proc = Start-Process -FilePath '"+str(lab['BIN']/'postgres.exe')+
    "' -ArgumentList @('-D','"+state['data']+"','-h','127.0.0.1','-p','"+cfg['PORT']+
    "') -WindowStyle Hidden -RedirectStandardOutput '"+str(task/'pg-resume.stdout')+
    "' -RedirectStandardError '"+str(task/'pg-resume.stderr')+
    "' -PassThru\n$proc.Id | Set-Content -LiteralPath '"+str(task/'pg-resume.pid')+"'\n",encoding='utf-8')
subprocess.Popen(['rtk','proxy','powershell','-NoProfile','-File',str(start)],
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
end=time.monotonic()+60
while True:
    try:
        with lab['connect'](cfg) as connection:
            databases=[r[0] for r in connection.execute('SELECT datname FROM pg_database').fetchall()]
        break
    except __import__('psycopg').OperationalError:
        if time.monotonic()>end:
            raise
        time.sleep(.2)
with lab['connect'](cfg,cfg['NAME']) as connection:
    empty=connection.execute('SELECT (SELECT count(*) FROM organizations_organization),'
                             '(SELECT count(*) FROM channels_message),'
                             '(SELECT count(*) FROM agent_turnwork)').fetchone()==(0,0,0)
    durable=connection.execute("SELECT current_setting('fsync'),current_setting('synchronous_commit')").fetchone()==('on','on')
if not empty or not durable:
    raise RuntimeError('Recovered template is not empty/durable')
run_id='individual-R106-backlog'
name='test_d29_dep_'+hashlib.sha256(run_id.encode()).hexdigest()[:20]
plan=lab['read'](HERE/'individual'/(run_id+'-plan.json'))
value=lab['read'](HERE/'individual'/run_id/'independent-verification.json')
if plan['run_id']!=run_id or value['run_id']!=run_id or value['status']!='NOT_ACCREDITED':
    raise RuntimeError('Unexpected interrupted attempt')
from psycopg import sql
with lab['connect'](cfg) as connection:
    if name in databases:
        connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    removed=not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
lab['write'](HERE/'individual'/(run_id+'-database-cleanup.json'),dict(database=name,removed=removed,
    created_by_this_run=True,cleanup_recovered_after_interruption=True,was_present_on_recovery=name in databases))
result=dict(value,case_id='R1-06',variant='backlog',run_id=run_id,exit_code=None,
    receipt='individual/'+run_id,mode='load',orchestration_interrupted=True,
    recovery='COMPLETED_VERIFIER_PRESERVED_ORIGINAL_PROCESS_EXIT_UNKNOWN')
lab['write'](HERE/'individual'/(run_id+'-result.json'),result)
values=[lab['read'](HERE/'individual'/(n+'-result.json')) for n in (
    'individual-R103-unequal','individual-R104-forecasts','individual-R105-simultaneous',
    'individual-R105-concentrated',run_id)]
lab['write'](HERE/'interruption-recovery.json',dict(
    cause='ORCHESTRATION_AND_PRIVATE_POSTGRES_PROCESSES_ABSENT_ON_RESUME_CAUSE_UNKNOWN',
    original_sessions_available=False,private_port_was_closed=True,
    private_server_restarted=True,original_template_reused=True,
    template_empty=empty,durability_unchanged=durable,
    base_recalibrated=False,old_receipts_rewritten=False,
    protected_sources_intact=integrity['intact'],interrupted_run=run_id,
    original_process_exit_unknown=True,completed_verification=lab['sha'](HERE/'individual'/run_id/'independent-verification.json'),
    matrix_had_not_started=True))
lab['write'](HERE/'individual-result.json',dict(results=values,state='FULL_LIVE_MATRIX_NOT_READY'))
print('Owned laboratory recovered; interrupted rejection retained; matrix not yet started',flush=True)
