"""Remove the positively identified private clusters after OOM; no DB reconnect."""
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
temp=Path(tempfile.gettempdir()).resolve()
paths=[temp/'vet-d29-authorized-20261007-03e5n2jy',temp/'vet-d29-authorized-20261007-l8icq_3c']
current=Path(read(OUT/'environment.json')['task']).resolve()
if current!=paths[0].resolve():raise RuntimeError('Unexpected current lab')
if read(OUT/'regression-native-stop-receipt.json')['remaining']:raise RuntimeError('Regression processes remain')
results=[]
for path in paths:
    owned=path.resolve()
    if owned.parent!=temp or owned.name not in {p.name for p in paths} or owned.is_symlink():raise RuntimeError('Unsafe owned target')
    state=read(owned/'session.json');cfg=state['config'];data=Path(state['data']).resolve()
    scripts=Path(state['orchestration']).resolve()
    if data!=owned/'pgdata' or scripts.parent!=owned:raise RuntimeError('Unexpected lab layout')
    if cfg['HOST']!='127.0.0.1' or not cfg['NAME'].startswith('test_'):raise RuntimeError('Unexpected private DB')
    archive=OUT/'recovered-labs'/owned.name;archive.mkdir(parents=True,exist_ok=False)
    saved={}
    for source in list(scripts.glob('*.py'))+list(scripts.glob('*.ps1')):
        target=archive/source.name;shutil.copy2(source,target);saved[source.name]=sha(target)
    ctl=temp/'vet-b8b-pg16-bin/pgsql/bin/pg_ctl.exe'
    with (archive/'pg-status-before-stop.log').open('x',encoding='utf-8') as f:
        status=subprocess.run(['rtk','proxy',str(ctl),'-D',str(data),'status'],stdout=f,stderr=subprocess.STDOUT,timeout=30)
    if status.returncode not in (0,3):raise RuntimeError('Unknown PostgreSQL status')
    if status.returncode==0:
        with (archive/'pg-stop.log').open('x',encoding='utf-8') as f:
            stopped=subprocess.run(['rtk','proxy',str(ctl),'-D',str(data),'stop','-m','fast','-w','-t','20'],stdout=f,stderr=subprocess.STDOUT,timeout=30)
        if stopped.returncode:raise RuntimeError('Owned PostgreSQL stop failed')
    with socket.socket() as sock:
        sock.settimeout(2);closed=sock.connect_ex(('127.0.0.1',int(cfg['PORT'])))!=0
    if not closed:raise RuntimeError('Owned port still open')
    # Capture logs after stop. Never preserve session.json or credentials.
    for name in ('pg.stdout','pg.stderr'):
        source=owned/name
        if source.is_file():shutil.copy2(source,archive/name);saved[name]=sha(archive/name)
    ps=archive/'remove-owned-temp.ps1';escaped=str(owned).replace("'","''")
    ps.write_text("$ErrorActionPreference = 'Stop'\n$target = (Resolve-Path -LiteralPath '"+escaped+"').Path\nif ($target -ne '"+escaped+"') { throw 'Resolved path changed' }\nRemove-Item -LiteralPath $target -Recurse -Force\n",encoding='utf-8')
    subprocess.run(['rtk','proxy','powershell','-NoProfile','-File',str(ps)],check=True,timeout=60)
    results.append(dict(path=str(owned),removed=not owned.exists(),port=int(cfg['PORT']),port_closed=closed,
        credentials_removed=not (owned/'session.json').exists(),private_databases_removed='Entire owned cluster directory removed after server stop',
        database_inventory_at_close='Unavailable after OutOfMemory/connection timeout; no claim of successful SQL DROP for interrupted regression DBs.',
        recovered_source_hashes=saved))
duplicates=[];archive=OUT/'accidental-root-copies';archive.mkdir(exist_ok=False)
for name in ('clock_guard.py','evaluation_provider.py','host-event-cut.ps1','load_case.py','prepared_probe.py','verify_case.py','worker_entry.py'):
    source=ROOT/name
    if not source.exists():continue
    if source.resolve().parent!=ROOT.resolve() or source.is_symlink():raise RuntimeError('Unexpected helper path')
    h=sha(source);target=archive/name;shutil.copy2(source,target)
    if sha(target)!=h:raise RuntimeError('Helper archive mismatch')
    candidates=list((OUT/'recovered-labs').glob('*/'+name))+[OUT/'orchestration'/name,OUT/'revision2'/name]
    matches=[str(p.relative_to(OUT)) for p in candidates if p.is_file() and sha(p)==h]
    if matches:source.unlink()
    duplicates.append(dict(name=name,sha256=h,matches=matches,archived=True,removed=bool(matches)))
value=dict(laboratories=results,accidental_root_helpers=duplicates,
    all_owned_labs_removed=all(r['removed'] and r['port_closed'] and r['credentials_removed'] for r in results),
    reason='Cleanup after PostgreSQL OutOfMemory; no runtime, power, clock, or database tuning.')
with (OUT/'lab-cleanup-v2.json').open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
print('Owned private clusters stopped and removed; evidence retained; credentials removed',flush=True)
