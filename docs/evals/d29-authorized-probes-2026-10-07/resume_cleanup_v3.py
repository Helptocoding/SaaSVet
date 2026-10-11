"""Finish only positively identified private-lab cleanup; never reconnect to DB."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from inspect_cleanup_v3 import closed, inspect

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2].resolve()
TEMP = Path(tempfile.gettempdir()).resolve()
SPECS = (('vet-d29-authorized-20261007-03e5n2jy', 55969), ('vet-d29-authorized-20261007-l8icq_3c', 60036))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))

def write(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2)

def safe_target(name):
    target = TEMP / name
    resolved = target.resolve()
    if resolved != target or resolved.parent != TEMP or name not in {s[0] for s in SPECS}:
        raise RuntimeError('Owned target outside verified temp scope')
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()):
        raise RuntimeError('Unexpected link at owned target')
    return target

def main():
    initial = inspect()
    if initial['matching_processes']:
        raise RuntimeError('Owned helper still running; do not race cleanup')
    if Path(read(OUT/'environment.json')['task']).resolve() != safe_target(SPECS[0][0]):
        raise RuntimeError('Lab ownership mismatch')
    labs = []
    for name, port in SPECS:
        path = safe_target(name)
        archive = OUT/'recovered-labs'/name
        if path.exists():
            state = read(path/'session.json')
            cfg = state['config']
            data = Path(state['data']).resolve()
            scripts = Path(state['orchestration']).resolve()
            if data != path/'pgdata' or scripts != path/'orchestration':
                raise RuntimeError('Unexpected owned lab layout')
            if cfg['HOST'] != '127.0.0.1' or int(cfg['PORT']) != port or not cfg['NAME'].startswith('test_'):
                raise RuntimeError('Unexpected DB ownership')
            archive.mkdir(parents=True, exist_ok=False)
            for source in list(scripts.glob('*.py')) + list(scripts.glob('*.ps1')):
                shutil.copy2(source, archive/source.name)
            ctl = TEMP/'vet-b8b-pg16-bin/pgsql/bin/pg_ctl.exe'
            with (archive/'pg-status-before-stop.log').open('x', encoding='utf-8') as f:
                status = subprocess.run(['rtk','proxy',str(ctl),'-D',str(data),'status'], stdout=f, stderr=subprocess.STDOUT, timeout=30)
            if status.returncode not in (0, 3):
                raise RuntimeError('Unknown PostgreSQL status')
            if status.returncode == 0:
                with (archive/'pg-stop.log').open('x', encoding='utf-8') as f:
                    stop = subprocess.run(['rtk','proxy',str(ctl),'-D',str(data),'stop','-m','fast','-w','-t','20'], stdout=f, stderr=subprocess.STDOUT, timeout=30)
                if stop.returncode:
                    raise RuntimeError('Private PostgreSQL stop failed')
            if not closed(port):
                raise RuntimeError('Private port still open')
            for log in ('pg.stdout', 'pg.stderr'):
                if (path/log).is_file():
                    shutil.copy2(path/log, archive/log)
            # Revalidate the absolute target immediately before recursive removal.
            if safe_target(name) != path:
                raise RuntimeError('Target changed before removal')
            shutil.rmtree(path)
            completion = 'Removal by validated Python filesystem operation; pg_ctl status verified first.'
        else:
            if not archive.is_dir() or not (archive/'pg-status-before-stop.log').is_file():
                raise RuntimeError('Missing earlier cleanup evidence')
            completion = 'Earlier PowerShell removal completed after wrapper timeout; absent directory and closed port verified independently.'
        if path.exists() or not closed(port):
            raise RuntimeError('Cleanup verification failed')
        hashes = {p.name: sha(p) for p in archive.iterdir() if p.is_file()}
        labs.append(dict(path=str(path), removed=True, port=port, port_closed=True, credentials_removed=True,
            private_databases_removed='Entire owned private cluster directory removed with no server on its port',
            database_inventory_at_close='Unavailable after OutOfMemory/connection timeout; no claim of successful SQL DROP for interrupted regression DBs.',
            completion=completion, recovered_source_hashes=hashes))
        print('Verified cleanup: '+name, flush=True)
    dup_archive = OUT/'accidental-root-copies'
    dup_archive.mkdir(exist_ok=False)
    duplicates = []
    for name in ('clock_guard.py','evaluation_provider.py','host-event-cut.ps1','load_case.py','prepared_probe.py','verify_case.py','worker_entry.py'):
        source = ROOT/name
        if not source.exists():
            continue
        if source.resolve().parent != ROOT or source.is_symlink():
            raise RuntimeError('Unexpected root helper location')
        digest = sha(source)
        target = dup_archive/name
        shutil.copy2(source, target)
        if sha(target) != digest:
            raise RuntimeError('Root-helper archive mismatch')
        candidates = list((OUT/'recovered-labs').glob('*/'+name)) + [OUT/'orchestration'/name, OUT/'revision2'/name]
        matches = [str(p.relative_to(OUT)) for p in candidates if p.is_file() and sha(p) == digest]
        if not matches:
            raise RuntimeError('No provenance match for root helper '+name)
        source.unlink()
        duplicates.append(dict(name=name,sha256=digest,matches=matches,archived=True,removed=True))
    final = inspect()
    if final['matching_processes']:
        raise RuntimeError('Owned process remains after cleanup')
    value = dict(laboratories=labs,accidental_root_helpers=duplicates,all_owned_labs_removed=True,
        reason='Cleanup after PostgreSQL OutOfMemory; no runtime, power, clock, or database tuning.',
        earlier_cleanup_interruption='PowerShell recursive removal exceeded wrapper 60s timeout; first target subsequently disappeared. Independently verified before continuing.',
        final_process_and_port_inspection=final)
    write(OUT/'lab-cleanup-v2.json', value)
    print('Cleanup complete; evidence preserved; no credentials archived.', flush=True)

if __name__ == '__main__':
    main()
