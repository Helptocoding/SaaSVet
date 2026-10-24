"""Complete Linux preflight only; candidate and original runners stay untouched."""
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
from prepare_wsl import EVIDENCE,REPO,OLD,WORK,TREE,PYTHON,PG,NODE,PNPM,DATA,PORT,SHA,RTK,save,run,environment,fetch,download,extract,command,integrity

def host_resources():
    win_python='C:\\Users\\LAP\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'
    script='C:\\Users\\LAP\\Desktop\\VeterinariaSaaS\\docs\\evals\\'+EVIDENCE.name+'\\host_resources.py'
    return json.loads(subprocess.check_output(['/mnt/c/Users/LAP/.local/bin/rtk.exe','proxy',
        win_python,'-B','-X','utf8',script],cwd=REPO,stdin=subprocess.DEVNULL))

def main():
    for name in ('postgres','initdb','psql','pg_ctl'):
        if 'not found' in (EVIDENCE/('ldd-'+name+'.txt')).read_text():
            raise RuntimeError('Resolve missing PostgreSQL shared libraries before starting: '+name)
    version=run(PG/'postgres','--version').decode().strip()
    if ' 16.15 ' not in version+' ':
        raise RuntimeError('Wrong PostgreSQL version: '+version)
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',PORT))==0:
            raise RuntimeError('Private port already occupied')
    command('initdb',[PG/'initdb','-D',DATA,'--username=b9e','--auth-local=trust','--auth-host=trust',
        '--encoding=UTF8','--locale=C.UTF-8','-L',WORK/'pgroot/usr/share/postgresql/16'])
    (WORK/'pgsocket').mkdir()
    with (DATA/'postgresql.conf').open('a') as config:
        config.write("\n# Private B9E Linux campaign, no productive data\n"
            "listen_addresses='127.0.0.1'\nport="+str(PORT)+"\n"
            "unix_socket_directories='"+str(WORK/'pgsocket')+"'\n"
            "fsync=on\nsynchronous_commit=on\nfull_page_writes=on\nmax_connections=40\n"
            "dynamic_library_path='"+str(WORK/'pgroot/usr/lib/postgresql/16/lib')+"'\n")
    command('pg-start',[PG/'pg_ctl','-D',DATA,'-l',WORK/'postgresql.log','-w','start'])
    import psycopg
    with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',autocommit=True) as conn:
        durable=conn.execute("SELECT version(),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes'),pg_backend_pid()").fetchone()
        if durable[1:4]!=('on','on','on'):
            raise RuntimeError('PostgreSQL is not durable')
        conn.execute('CREATE DATABASE test_b9i_control')
    save('postgresql-preflight.json',{'version':version,'durability':durable,'port':PORT,
        'database':'test_b9i_control','ownership':'new campaign only','no_application_tables':True})
    (EVIDENCE/'private-postgresql').mkdir()
    for filename in ('postgresql.conf','pg_hba.conf'):
        shutil.copy2(DATA/filename,EVIDENCE/'private-postgresql'/filename)
    command('discovery',[PYTHON,'-B',EVIDENCE/'discover_candidate.py'],cwd=TREE/'backend')
    files=['backend/apps/agent/tests/b9e_profile.py','backend/apps/agent/tests/b9a_harness.py',
        'backend/apps/agent/tests/test_b9a_e2e.py']
    delta=run('git','diff','--exit-code','08310461337a284386299ec47c54125f2139bf7f',SHA,'--',*files)
    if delta:
        raise RuntimeError('PROFILE sources changed from historical accepted scenario')
    historical=json.loads((TREE/'docs/evals/profile-beta-1-e4-sql-2026-10-02/saturation.json').read_text())
    save('profile-compatibility.json',{'candidate_sha':SHA,'identical_git_sources':files,
        'historical_candidate':'08310461337a284386299ec47c54125f2139bf7f',
        'historical_gates':list(historical['gates']),'warmup_seconds':30,'measurement_seconds':300,
        'drain_seconds':20,'smoke':False,'actual_read_llm_calls':2,'no_workload_or_gate_changes':True})
    gitleaks='gitleaks_8.18.4_linux_x64.tar.gz'
    base='https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/'
    checks=fetch(base+'gitleaks_8.18.4_checksums.txt').decode()
    digest=next(line.split()[0] for line in checks.splitlines() if line.split()[-1]==gitleaks)
    extract(download(base+gitleaks,gitleaks,digest),WORK/'gitleaks')
    command('gitleaks-version',[WORK/'gitleaks/gitleaks','version'])
    command('history-clone',['git','clone','--no-hardlinks','--no-checkout',REPO,WORK/'history'])
    command('history-checkout',['git','checkout','--detach',SHA],cwd=WORK/'history')
    if run('git','rev-parse','--is-shallow-repository',cwd=WORK/'history').strip()!=b'false':
        raise RuntimeError('Security history is shallow')
    save('security-history.json',{'head':run('git','rev-parse','HEAD',cwd=WORK/'history').decode().strip(),
        'refs':run('git','show-ref',cwd=WORK/'history').decode(),'full_history':True,
        'source':'local independent clone, no uncommitted evidence injected into scanner'})
    command('audit-venv',[PYTHON,'-m','venv',WORK/'audit-venv'])
    command('audit-tool-install',[WORK/'audit-venv/bin/python','-m','pip','install','--no-cache-dir','pip-audit'])
    save('audit-toolchain.json',json.loads(run(WORK/'audit-venv/bin/python','-m','pip','list','--format=json')))
    integrity('ready')
    save('host-resource-preflight-observation.json',host_resources())
    save('environment-ready.json',{'candidate_sha':SHA,'state':'READY_FOR_SEAL',
        'python':str(PYTHON),'postgresql':version,'node':run(NODE,'--version').decode().strip(),
        'pnpm':run(NODE,PNPM,'--version').decode().strip(),'all_product_sources_unchanged':True})
    print('ENVIRONMENT_READY_FOR_SEAL',flush=True)

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        save('stage-incident.json',{'type':type(exc).__name__,'message':str(exc),'tests_executed':False})
        raise
