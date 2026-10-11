"""Own isolated PostgreSQL lifecycle; no PROFILE entry point is invoked."""
import argparse
import hashlib
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
import psycopg
from psycopg import sql

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
KEY = 'dded711c1ce04cfd8f01af5dc7d62da2'
HEAD = '825db75df68bf076929fa787e77beefe96803350'
DATA = Path(tempfile.gettempdir()) / ('vet-e4-causal-'+KEY)
PG = Path(tempfile.gettempdir())/'vet-b8b-pg16-bin/pgsql/bin'
PORT, USER = 35449, 'e4causal'
PREFIX = 'test_b8b_e4_causal_'+KEY[:8]+'_'
TEMPLATE, LOAD, EQUIV = (PREFIX+name for name in ('template','load','equiv'))
URI = f'postgresql://{USER}@127.0.0.1:{PORT}/'

def write(name, value):
    with (OUT/name).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,default=str); stream.write('\n')

def env(database=TEMPLATE):
    result = dict(os.environ, DATABASE_URL=URI+database, SECRET_KEY=secrets.token_urlsafe(48),
        DEBUG='False', ENVIRONMENT='dev', DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='',
        DISCORD_WEBHOOK_URL='', HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
        PYTHONIOENCODING='utf-8', DJANGO_SETTINGS_MODULE='config.settings',
        PYTHONPATH=str(ROOT/'backend'), E4_DIAGNOSTIC_RUN=KEY)
    for name in ('E4_BATCH','E4_POLL_SECONDS','E4_LLM_SECONDS','E4_CLAIM_CANDIDATE',
                 'E4_NO_NOISY','E4_MEASURE_SECONDS','E4_TRACE_EVIDENCE_DIR'):
        result.pop(name,None)
    return result

def run(command, name, database=TEMPLATE):
    with (OUT/name).open('x',encoding='utf-8') as stream:
        return subprocess.call([str(x) for x in command],cwd=ROOT/'backend',env=env(database),
            stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)

def verify():
    with psycopg.connect(URI+'postgres',autocommit=True,connect_timeout=5) as conn:
        row = conn.execute("SELECT current_setting('data_directory'),version(),"
            "current_setting('fsync'),current_setting('synchronous_commit')").fetchone()
    assert Path(row[0]).resolve()==DATA.resolve() and row[2:]==('on','on')
    return dict(run_id=KEY,head=HEAD,data_directory=str(DATA),port=PORT,postgresql=row[1],
                fsync=row[2],synchronous_commit=row[3],classification='DIAGNOSTIC_ONLY')

def snapshot():
    assert subprocess.check_output(['rtk','proxy','git','rev-parse','HEAD'],cwd=ROOT).decode().strip()==HEAD
    paths=subprocess.check_output(['rtk','proxy','git','ls-tree','-r','--name-only',HEAD],cwd=ROOT).decode().splitlines()
    paths=[p for p in paths if p.startswith(('backend/','docs/evals/profile-beta-1-',
        'docs/decisions/','docs/evals/e4-instrumentation-2026-10-03/'))]
    requested=''.join(HEAD+':'+p+'\n' for p in paths).encode()
    blobs=subprocess.run(['rtk','proxy','git','cat-file','--batch'],cwd=ROOT,input=requested,
        stdout=subprocess.PIPE,check=True).stdout
    stream=io.BytesIO(blobs); hashes={}; drift=[]
    for p in paths:
        header=stream.readline().split(); original=stream.read(int(header[2])); assert stream.read(1)==b'\n'
        current=(ROOT/p).read_bytes()
        normalized=lambda x:hashlib.sha256(x.replace(b'\r\n',b'\n')).hexdigest()
        if normalized(original)!=normalized(current): drift.append(p)
        hashes[p]=dict(raw_sha256=hashlib.sha256(current).hexdigest(),normalized_lf_sha256=normalized(current))
    assert not drift,drift
    return dict(head=HEAD,classification='DIAGNOSTIC_ONLY',protected_files=len(paths),drift=drift,hashes=hashes)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('prepare','functional','load','cleanup'))
    args=parser.parse_args()
    if args.action=='prepare':
        write('protected-sources-before.json',snapshot())
        assert not DATA.exists()
        with socket.socket() as probe: assert probe.connect_ex(('127.0.0.1',PORT))!=0
        assert run([PG/'initdb.exe','-D',DATA,'-U',USER,'-A','trust','--encoding=UTF8','--locale=C'],'init.log')==0
        assert run([PG/'pg_ctl.exe','-D',DATA,'-l',DATA/'server.log','-o',
            f'-p {PORT} -h 127.0.0.1 -c fsync=on -c synchronous_commit=on','-t','180','-w','start'],'start.log')==0
        write('environment.json',verify())
        with psycopg.connect(URI+'postgres',autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(TEMPLATE)))
        assert run([sys.executable,'manage.py','migrate','--noinput'],'migrate.log')==0
        with psycopg.connect(URI+'postgres',autocommit=True) as conn:
            for name in (LOAD,EQUIV):
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(name),sql.Identifier(TEMPLATE)))
        write('prepared.json',dict(run_id=KEY,classification='DIAGNOSTIC_ONLY',databases=[TEMPLATE,LOAD,EQUIV]))
    elif args.action in ('functional','load'):
        verify(); snapshot()
        if args.action=='load':
            assert json.loads((OUT/'functional.exit.json').read_text())['exit_code']==0
        code=run([sys.executable,OUT/'run.py',args.action],args.action+'.log',EQUIV if args.action=='functional' else LOAD)
        write(args.action+'.exit.json',dict(classification='DIAGNOSTIC_ONLY',exit_code=code,run_id=KEY))
        return code
    else:
        verify()
        with psycopg.connect(URI+'postgres',autocommit=True) as conn:
            clients=conn.execute("SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchone()[0]
            waits=conn.execute('SELECT count(*) FROM pg_locks WHERE NOT granted').fetchone()[0]
            prepared=conn.execute('SELECT count(*) FROM pg_prepared_xacts').fetchone()[0]
            assert clients==waits==prepared==0
            for name in (LOAD,EQUIV,TEMPLATE):
                conn.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
        assert run([PG/'pg_ctl.exe','-D',DATA,'-m','fast','-t','180','-w','stop'],'stop.log')==0
        with socket.socket() as probe: closed=probe.connect_ex(('127.0.0.1',PORT))!=0
        assert closed
        # One shell/runtime end-to-end; verify the exact resolved own target.
        expected=Path(tempfile.gettempdir()).resolve()/('vet-e4-causal-'+KEY)
        assert DATA.resolve()==expected and DATA.resolve().parent==Path(tempfile.gettempdir()).resolve()
        shutil.rmtree(DATA)
        assert not DATA.exists()
        write('cleanup.json',dict(status='CLEANED',classification='DIAGNOSTIC_ONLY',port_closed=True,
            clients=clients,waiting_locks=waits,prepared_transactions=prepared,data_directory_absent=True,
            dropped_databases=[LOAD,EQUIV,TEMPLATE]))
        write('protected-sources-after.json',snapshot())
    return 0

if __name__=='__main__': raise SystemExit(main())
