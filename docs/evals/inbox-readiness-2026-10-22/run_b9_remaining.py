"""One finite continuation: advisory audits, then five unchanged profiles, stop on failure."""
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from b9_runtime import *

BLOCKS = OUT/'blocks'
SCENARIOS = ['base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation']
SEAL = {}


class StopCampaign(Exception):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop(state, phase, cause, **details):
    save('b9-STOP.json', dict(state=state, phase=phase, cause=cause, no_rerun=True, **details))
    print(json.dumps(dict(state=state, phase=phase, cause=cause)), flush=True)
    raise StopCampaign(cause)


def verify(label):
    changed = [p for p,h in SEAL.items() if not Path(p).is_file() or digest(Path(p)) != h]
    save('b9-integrity-'+label+'.json', dict(state='PASS' if not changed else 'PENDING', checked=len(SEAL), mismatches=changed))
    if changed:
        stop('PENDING', label, 'Sealed candidate, evidence or toolchain changed', mismatches=changed)


def admission(label):
    host = resources()
    if host['physical_available'] < 2*GIB or host['disk_available'] < GIB:
        stop('PENDING', label, 'Original amended resource reserve unavailable', host=host)
    if not ctypes.windll.kernel32.SetThreadExecutionState(0x80000001):
        stop('PENDING', label, 'Owned awake request unavailable')
    return host


def seal():
    assert not (OUT/'b9-start.json').exists() and not (OUT/'b9-STOP.json').exists()
    required = ['security-verification.json', 'security-correction-verification.json',
                'b9-retained-reference-validation.json', 'b9-native-preflight.json',
                'b9-postgresql-preflight.json', 'b9-interpreter-preflight.json',
                'b9-clock-preflight.json', 'audit-toolchain.json']
    for name in required:
        assert json.loads((OUT/name).read_text(encoding='utf-8'))['state'] == 'PASS', name
    original = json.loads((OLD/'candidate-sources.json').read_text(encoding='utf-8'))
    paths = [TREE/r['path'] for r in original['files']]
    assert all(p.is_file() and digest(p) == r['sha256'] for p,r in zip(paths,original['files']))
    paths += [OUT/name for name in required] + list(OUT.glob('*.py'))
    paths += list(OLD.glob('*.py')) + list(OLD.glob('*.json')) + list(OLD.glob('*.md')) + list(OLD.glob('*.diff'))
    paths += [ROOT/'.gitleaks.toml', ROOT/'.gitleaksignore', OUT/'B9-RESUMPTION.md',
              OLD/'native_support.py', OLD/'candidate-sources.json', RTK, Path(sys.executable),
              DATA/'postgresql.conf', DATA/'pg_hba.conf']
    for folder in (WORK/'python', WORK/'audit-site', WORK/'node-v20.20.2-win-x64', WORK/'pnpm'):
        paths += [p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [p for p in PG.iterdir() if p.suffix.lower() in ('.exe','.dll')]
    # Preserve exact referenced backend and frontend receipt bytes between blocks.
    for name in ('completed-reference-manifest.json', 'completed-prefix-manifest.json'):
        manifest = json.loads((OLD/name).read_text(encoding='utf-8'))
        paths.append(OLD/name)
        source = OLD/manifest['bundle_relative']
        for name, row in manifest['files'].items():
            path = source/name
            assert digest(path) == row['sha256'], str(path)
            paths.append(path)
    SEAL.update({str(p):digest(p) for p in dict.fromkeys(paths)})
    save('b9-evaluation-seal.json', dict(candidate_tree=original['candidate_sha'], files=SEAL))
    host = admission('preflight')
    save('b9-start.json', dict(state='PASS', candidate_tree=original['candidate_sha'],
        resources=host, original_r12_FAIL_preserved=True, evidence_mode='COMPOSITE_ACCEPTANCE',
        accepted_historical_evidence_limitation=True, continuous_campaign_claimed=False,
        original_contract_unchanged=True, original_5_gib_floor_claimed=False,
        ram_reserve_bytes=2*GIB, disk_reserve_bytes=GIB, clock_limit_seconds=1,
        profiles_per_variant_max=1, current_backend_full_runs=0, current_frontend_full_runs=0,
        production_activation_authorized=False))


def execute(label, args, *, cwd=None, extra_env=None, advisory=False):
    receipt = BLOCKS/(label+'.command.json')
    assert not receipt.exists() and not (OUT/'b9-STOP.json').exists()
    verify('before-'+label)
    host = admission(label)
    env = environment()
    env.update(extra_env or {})
    argv = [str(RTK), 'proxy', *map(str,args)]
    data = dict(state='RUNNING', formal_run_number=1, argv=argv, cwd=str(cwd or TREE/'backend'),
                advisory=advisory, resources_before=host)
    save(str(receipt.relative_to(OUT)), data)
    print('BLOCK_START '+label, flush=True)
    samples = []
    invalid = None
    origin, wall = time.monotonic(), time.time()
    last_wall = wall
    with (BLOCKS/(label+'.command.log')).open('wb') as log:
        proc = subprocess.Popen(argv, cwd=cwd or TREE/'backend', env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        data['owned_wrapper_pid'] = proc.pid
        while proc.poll() is None:
            now, current = time.monotonic(), time.time()
            try:
                host = resources()
                awake = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
                skew = (current-wall)-(now-origin)
                if current < last_wall or abs(skew) > 1:
                    invalid = 'Clock discontinuity'
                elif not awake:
                    invalid = 'Owned awake request unavailable'
                elif host['physical_available'] < 2*GIB:
                    invalid = 'Memory reserve exhausted'
                elif host['disk_available'] < GIB:
                    invalid = 'Backing disk reserve exhausted'
                elif now-origin > 1200:
                    invalid = 'Bounded owned process lifetime exceeded'
                samples.append(dict(elapsed_seconds=now-origin, wall_minus_monotonic_seconds=skew,
                                    host=host, owned_awake_request_confirmed=awake))
            except Exception as exc:
                invalid = 'Native observer unavailable: '+type(exc).__name__
            if invalid:
                killed = subprocess.run([str(RTK),'proxy','taskkill.exe','/PID',str(proc.pid),'/T','/F'],
                    stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
                data['owned_tree_termination'] = dict(exit_code=killed.returncode, foreign_processes_targeted=False)
                proc.wait(timeout=30)
                break
            last_wall = current
            time.sleep(1)
        code = proc.wait()
    data.update(state='COMPLETED', exit_code=code, seconds=time.monotonic()-origin,
                invalidating_incident=invalid, resources_after=resources())
    save(str(receipt.relative_to(OUT)), data)
    save('monitor-'+label+'.json', samples)
    verify('after-'+label)
    print('BLOCK_END '+label+' exit='+str(code), flush=True)
    if invalid:
        stop('PENDING', label, invalid)
    admission('after-'+label)
    return code


def gate(label, state='PASS', **details):
    save('blocks/'+label+'.gate.json', dict(state=state, **details))


def create_db(name):
    import psycopg
    from psycopg import sql
    assert name.startswith('test_b9i_profile_')
    with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))


def main():
    BLOCKS.mkdir(exist_ok=True)
    seal()
    # Both audits remain advisory, exactly as in the original B9 contract.
    audits = [
        ('pip-audit', [sys.executable,'-m','pip_audit','-r',TREE/'backend/requirements.lock',
                       '--format=json','--output',BLOCKS/'pip-audit.json'], TREE,
         dict(PYTHONPATH=str(WORK/'audit-site'), PIP_CONFIG_FILE=os.devnull, PIP_INDEX_URL='https://pypi.org/simple')),
        ('pnpm-audit', [NODE,PNPM,'audit','--json'], TREE/'frontend', {})]
    for label,args,cwd,env in audits:
        code = execute(label,args,cwd=cwd,extra_env=env,advisory=True)
        gate(label, 'ADVISORY_NONZERO' if code else 'PASS', exit_code=code)
    for scenario in SCENARIOS:
        label = 'profile-'+scenario
        name = 'test_b9i_profile_'+scenario
        create_db(name)
        env = dict(DATABASE_URL=f'postgresql://b9e@127.0.0.1:{PORT}/{name}')
        code = execute(label+'-migrate',[PYTHON,'-B','manage.py','migrate','--no-input'],extra_env=env)
        if code:
            stop('PENDING', label, 'Private profile migration failed', exit_code=code)
        path = BLOCKS/(label+'.json')
        code = execute(label,[PYTHON,'-B','-m','apps.agent.tests.b9e_profile',
                             '--scenario',scenario,'--output',path],extra_env=env)
        if code or not path.exists():
            stop('PENDING', label, 'Profile receipt absent/interrupted', exit_code=code)
        result = json.loads(path.read_text(encoding='utf-8'))
        if result.get('smoke_only') is not False or result.get('warmup_seconds') != 30 or result.get('measurement_seconds') != 300 or not result.get('gates'):
            stop('PENDING', label, 'Original profile contract metadata invalid')
        if result.get('technical_pass') is not True or not all(v is True for v in result['gates'].values()):
            gate(label,'FAIL',gates=result['gates'])
            stop('FAIL', label, 'Original applicable profile gate violated',gates=result['gates'])
        gate(label, gates=result['gates'])
    save('b9-technical-completion.json', dict(state='PASS',
        candidate_tree='f5f18d71847a46d66644775cd90d30268f072e3b',
        acceptance_label='PASS_BAJO_CONDICION_DE_EVIDENCIA_ENMENDADA',
        original_r12_FAIL_preserved=True, accepted_historical_evidence_limitation=True,
        evidence_mode='COMPOSITE_ACCEPTANCE', continuous_campaign_claimed=False,
        current_inbox_phase3_candidate_certified=False, activation='PENDING_ACTIVATION_REQUIREMENTS'))


if __name__ == '__main__':
    try:
        main()
    except StopCampaign:
        raise SystemExit(2)
    except Exception as exc:
        save('b9-controller-incident.json',dict(type=type(exc).__name__, message=str(exc)))
        if not (OUT/'b9-STOP.json').exists():
            save('b9-STOP.json',dict(state='PENDING',phase='controller',cause=str(exc),no_rerun=True))
        raise
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        if (OUT/'b9-owned-cluster.json').exists() and DATA.exists():
            try:
                run(PG/'pg_ctl.exe','-D',DATA,'-m','fast','-w','stop')
                save('b9-cleanup.json',dict(state='PASS', owned_cluster_stopped=True, artifacts_preserved=True,
                     other_servers_touched=False, ordinary_database_touched=False))
            except Exception as exc:
                save('b9-cleanup.json',dict(state='PENDING', error_type=type(exc).__name__))
