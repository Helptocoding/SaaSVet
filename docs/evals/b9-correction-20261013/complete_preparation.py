"""Reuse the B9 assembly after focused correction verification."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
from prepare_wsl import EVIDENCE, REPO, WORK, TREE, PYTHON, NODE, PNPM, SHA, save, run, command, download, fetch, extract, integrity


def main():
    focused = json.loads((EVIDENCE/'diagnostic.results.json').read_text())
    assert not focused['failures'] and not focused['errors'] and not focused['xfail'] and not focused['xpass']
    assert not json.loads((EVIDENCE/'diagnostic.command.json').read_text())['invalidating_incident']
    folder = EVIDENCE/'focused'; folder.mkdir(exist_ok=True)
    for name in ['discovery.json', 'discovery.command.json', 'discovery.log', 'dependency-files.json', 'postgresql-preflight.json']:
        assert not (folder/name).exists(), 'Preserve previous focused receipt: '+name
        shutil.copy2(EVIDENCE/name, folder/name)
    # Discovery gets its own invocation/receipt in the formal preparation.
    (EVIDENCE/'discovery.command.json').unlink()
    (EVIDENCE/'discovery.log').unlink()
    assembly = json.loads((EVIDENCE/'assembly.json').read_text())
    assembly.update(phase='PREPARING', candidate_kind='Git tree', base_commit='194772677ca4e9fe1a1dec7f4dafa48396a6c583',
                    focused_verification_completed=True)
    save('assembly.json', assembly)
    name='node-v20.20.2-linux-x64.tar.xz'
    checks=fetch('https://nodejs.org/dist/v20.20.2/SHASUMS256.txt').decode()
    checksum=next(line.split()[0] for line in checks.splitlines() if line.split()[-1]==name)
    extract(download('https://nodejs.org/dist/v20.20.2/'+name,name,checksum),WORK)
    metadata=json.loads(fetch('https://registry.npmjs.org/pnpm/9.15.9'))
    package=fetch(metadata['dist']['tarball'])
    assert base64.b64encode(hashlib.sha512(package).digest()).decode() == metadata['dist']['integrity'].removeprefix('sha512-')
    extract(package,WORK/'pnpm')
    save('pnpm-package.json',{'version':metadata['version'],'url':metadata['dist']['tarball'],
         'integrity':metadata['dist']['integrity'],'sha256':hashlib.sha256(package).hexdigest()})
    save('toolchain.json',{'node':run(NODE,'--version').decode().strip(),
         'pnpm':run(NODE,PNPM,'--version').decode().strip(),'python':run(PYTHON,'--version').decode().strip()})
    command('frontend-install',[NODE,PNPM,'install','--frozen-lockfile','--store-dir',WORK/'pnpm-store'],cwd=TREE/'frontend')
    import psycopg
    with psycopg.connect(host='127.0.0.1',port=35481,user='b9e',dbname='postgres',autocommit=True) as conn:
        conn.execute('CREATE DATABASE test_b9i_control')
    command('discovery',[PYTHON,'-B',EVIDENCE/'discover_candidate.py'],cwd=TREE/'backend')
    files=['backend/apps/agent/tests/b9e_profile.py','backend/apps/agent/tests/b9a_harness.py','backend/apps/agent/tests/test_b9a_e2e.py']
    assert not run('git','diff','--exit-code','08310461337a284386299ec47c54125f2139bf7f',SHA,'--',*files)
    historical=json.loads((TREE/'docs/evals/profile-beta-1-e4-sql-2026-10-02/saturation.json').read_text())
    save('profile-compatibility.json',{'candidate_sha':SHA,'identical_git_sources':files,
         'historical_candidate':'08310461337a284386299ec47c54125f2139bf7f','historical_gates':list(historical['gates']),
         'warmup_seconds':30,'measurement_seconds':300,'drain_seconds':20,'smoke':False,
         'actual_read_llm_calls':2,'no_workload_or_gate_changes':True})
    asset='gitleaks_8.18.4_linux_x64.tar.gz'; base='https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/'
    checks=fetch(base+'gitleaks_8.18.4_checksums.txt').decode()
    checksum=next(line.split()[0] for line in checks.splitlines() if line.split()[-1]==asset)
    extract(download(base+asset,asset,checksum),WORK/'gitleaks')
    command('gitleaks-version',[WORK/'gitleaks/gitleaks','version'])
    command('history-clone',['git','clone','--no-hardlinks','--no-checkout',REPO,WORK/'history'])
    base_commit='194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    command('history-checkout',['git','checkout','--detach',base_commit],cwd=WORK/'history')
    assert run('git','rev-parse','--is-shallow-repository',cwd=WORK/'history').strip()==b'false'
    changes=json.loads((EVIDENCE/'candidate.json').read_text())['changed_paths']
    for name in changes:
        target=WORK/'security-patch'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(TREE/name,target)
    save('security-history.json',{'head':base_commit,'full_history':True,'candidate_tree':SHA,
         'additional_current_tree_paths':changes,'patch_scan_source':str(WORK/'security-patch')})
    command('audit-venv',[PYTHON,'-m','venv',WORK/'audit-venv'])
    command('audit-tool-install',[WORK/'audit-venv/bin/python','-m','pip','install','--no-cache-dir','pip-audit'])
    save('audit-toolchain.json',json.loads(run(WORK/'audit-venv/bin/python','-m','pip','list','--format=json')))
    command('interpreters',[PYTHON,'-B',EVIDENCE/'interpreter_preflight.py'],cwd=TREE/'backend')
    save('base-python-environment.json',json.loads((EVIDENCE/'interpreter-preflight.json').read_text())['interpreters']['legacy_base'])
    integrity('ready')
    from stage_wsl import host_resources
    save('host-resource-preflight-observation.json',host_resources())
    save('environment-ready.json',{'candidate_sha':SHA,'candidate_kind':'Git tree','state':'READY_FOR_SEAL',
         'focused_tests':focused['tests'],'focused_failures':0,'focused_errors':0,
         'formal_tests_executed':False,'product_sources_changed':False})
    print('ACCEPTANCE_PREPARATION_PASS',flush=True)


if __name__=='__main__':
    main()
