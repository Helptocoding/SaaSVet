"""Close only the two positively identified private labs after probes finish."""
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT))
import authorized_lab as lab

def main():
    current=Path(lab.read(OUT/'environment.json')['task']).resolve()
    temp=Path(tempfile.gettempdir()).resolve()
    prior=temp/'vet-d29-authorized-20261007-l8icq_3c'
    paths=[current,prior.resolve()]
    allowed={'vet-d29-authorized-20261007-03e5n2jy','vet-d29-authorized-20261007-l8icq_3c'}
    if any(p.parent!=temp or p.name not in allowed or p.is_symlink() for p in paths):
        raise RuntimeError('Owned path validation failed')
    if not (OUT/'r2-04/authorized-r204-postcommit-base-20261007-0004-database-cleanup.json').exists():
        raise RuntimeError('Physical probe still open')
    results=[]
    for owned in paths:
        state=lab.read(owned/'session.json');cfg=state['config'];data=Path(state['data']).resolve()
        if data.parent!=owned or data.name!='pgdata':raise RuntimeError('Unexpected pgdata')
        archive=OUT/'recovered-labs'/owned.name
        archive.mkdir(parents=True,exist_ok=False)
        # Source recovery is dated at closure, never asserted as a prior seal.
        scripts=Path(state['orchestration']).resolve()
        if scripts.parent!=owned:raise RuntimeError('Unexpected script directory')
        saved={}
        for source in list(scripts.glob('*.py'))+list(scripts.glob('*.ps1'))+[owned/'pg.stdout',owned/'pg.stderr']:
            if source.is_file():
                target=archive/source.name;shutil.copy2(source,target);saved[source.name]=lab.sha(target)
        with lab.connect(cfg) as con:
            active=con.execute("SELECT datname,pid,state FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
            if active:raise RuntimeError('Owned lab has client sessions; refusing cleanup: '+str([(x[0],x[2]) for x in active]))
            dbs=[r[0] for r in con.execute("SELECT datname FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')")]
            if any(n!=cfg['NAME'] for n in dbs):raise RuntimeError('Unexpected database remains: '+str(dbs))
            for name in dbs:con.execute(lab.sql.SQL('DROP DATABASE {}').format(lab.sql.Identifier(name)))
        with (archive/'pg-stop.log').open('x',encoding='utf-8') as f:
            stopped=subprocess.run(['rtk','proxy',str(lab.BIN/'pg_ctl.exe'),'-D',str(data),'stop','-m','fast','-w'],stdout=f,stderr=subprocess.STDOUT)
        if stopped.returncode:raise RuntimeError('PostgreSQL stop failed')
        with socket.socket() as s:closed=s.connect_ex(('127.0.0.1',int(cfg['PORT'])))!=0
        if not closed:raise RuntimeError('Owned port is still open')
        # Verified absolute path, one PowerShell invocation for deletion, no
        # cmd/batch composition and no enumerated children crossing shells.
        ps=archive/'remove-owned-temp.ps1'
        escaped=str(owned).replace("'","''")
        ps.write_text("$ErrorActionPreference = 'Stop'\n$target = (Resolve-Path -LiteralPath '"+escaped+"').Path\nif ($target -ne '"+escaped+"') { throw 'Resolved path changed' }\nRemove-Item -LiteralPath $target -Recurse -Force\n",encoding='utf-8')
        subprocess.run(['rtk','proxy','powershell','-NoProfile','-File',str(ps)],check=True)
        results.append(dict(path=str(owned),removed=not owned.exists(),port=int(cfg['PORT']),port_closed=closed,
            private_databases_removed=dbs,credentials_removed=not (owned/'session.json').exists(),recovered_source_hashes=saved))
    duplicates=[]
    names=('clock_guard.py','evaluation_provider.py','host-event-cut.ps1','load_case.py','prepared_probe.py','verify_case.py','worker_entry.py')
    archive=OUT/'accidental-root-copies';archive.mkdir(exist_ok=False)
    for name in names:
        source=ROOT/name
        if not source.exists():continue
        resolved=source.resolve()
        if resolved.parent!=ROOT.resolve() or source.is_symlink():raise RuntimeError('Unexpected root helper path')
        h=lab.sha(source)
        candidates=list((OUT/'recovered-labs').glob('*/'+name))+[OUT/'orchestration'/name,OUT/'revision2'/name]
        matches=[str(p.relative_to(OUT)) for p in candidates if p.is_file() and lab.sha(p)==h]
        target=archive/name;shutil.copy2(source,target)
        if lab.sha(target)!=h:raise RuntimeError('Root helper backup mismatch')
        if matches:source.unlink()
        duplicates.append(dict(name=name,sha256=h,matches=matches,archived=True,removed=bool(matches)))
    lab.write(OUT/'lab-cleanup-v2.json',dict(laboratories=results,accidental_root_helpers=duplicates,
        all_owned_labs_removed=all(r['removed'] and r['port_closed'] and r['credentials_removed'] for r in results)))
    print('Owned lab cleanup verified; credentials removed; root helper recovery preserved')

if __name__=='__main__':main()
