"""Prepare backend-only diagnostic resources from the exact candidate."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
from prepare_wsl import EVIDENCE, REPO, WORK, TREE, RTK, PYTHON, PG, DATA, PORT, SHA, NODE, PNPM, save, run, environment, fetch, download, extract, command, integrity, resources

PRIOR = EVIDENCE.parent / 'b9-integral-acceptance-1947726-wsl-20261012-r9'


def setup():
    assert not WORK.exists() and not (EVIDENCE / 'assembly.json').exists()
    assert resources()['disk_available'] >= 2 * 1024**3
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', PORT)) != 0
    for name in ['tools', 'tmp', 'home', 'downloads']:
        (WORK / name).mkdir(parents=True)
    bootstrap = Path('/mnt/c/Users/LAP/AppData/Local/Temp/b9-clock-isolation-r9-pid3g53x/rtk-linux')
    assert hashlib.sha256(bootstrap.read_bytes()).hexdigest() == 'b947215511bfd8f5f6eb12c6b6d4a9f70b72e9ce37442cfa4df2352b033cd0ea'
    shutil.copy2(bootstrap, RTK)
    RTK.chmod(0o755)
    save('assembly.json', {'candidate_sha': SHA, 'workspace': str(WORK), 'tree': str(TREE),
         'port': PORT, 'phase':'PREPARING','purpose':'New fixed integral acceptance, no focused test rerun', 'tests_executed': False})
    save('checkout-before.json', {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
         'branch': run('git', 'branch', '--show-current').decode().strip(),
         'unrelated': {n: {'exists': (REPO/n).exists(), 'sha256': hashlib.sha256((REPO/n).read_bytes()).hexdigest() if (REPO/n).exists() else None}
                       for n in ['DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json']}})
    assert json.loads((EVIDENCE/'checkout-before.json').read_text())['head'] == '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
    # Preserve every prior campaign, including r9 delivery metadata and raw logs.
    prior = {}
    for folder in EVIDENCE.parent.iterdir():
        if folder.is_dir() and (folder.name.startswith('b9-integral-acceptance-1947726') or folder.name.startswith('b9-correction-')) and folder != EVIDENCE:
            prior.update({p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    archive = run('git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', SHA)
    extract(archive, TREE)
    manifest = json.loads((PRIOR/'candidate-sources.json').read_text())
    manifest['candidate_sha'] = SHA
    manifest['candidate_kind'] = 'Git tree with two authorized test corrections; base commit 1947726'
    manifest['archive_sha256'] = hashlib.sha256(archive).hexdigest()
    entries = [entry for entry in run('git','ls-tree','-r','-z',SHA).split(b'\0') if entry]
    manifest['files'] = []
    for entry in entries:
        meta, raw = entry.split(b'\t',1)
        mode, kind, oid = meta.decode().split()
        path = raw.decode()
        content = (TREE/path).read_bytes()
        assert kind == 'blob' and hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest() == oid
        manifest['files'].append({'path':path,'git_blob':oid,'mode':mode,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)})
    save('candidate-sources.json', manifest)
    integrity('after-export')
    print('EXACT_CANDIDATE_PREPARED', flush=True)
    uv_meta = json.loads((PRIOR/'astral-sh-uv.json').read_text())
    url = 'https://github.com/astral-sh/uv/releases/download/' + uv_meta['tag'] + '/' + uv_meta['asset']
    extract(download(url, uv_meta['asset'], uv_meta['sha256']), WORK/'uv-archive')
    (WORK/'uv').mkdir()
    shutil.copy2(next((WORK/'uv-archive').rglob('uv')), WORK/'uv/uv')
    command('python-install', [WORK/'uv/uv', 'python', 'install', '3.13.2'])
    base = next((WORK/'python').glob('cpython-3.13.2-*/bin/python3.13'))
    command('venv-create', [base, '-m', 'venv', WORK/'venv'])
    command('python-dependencies', [PYTHON, '-m', 'pip', 'install', '--no-cache-dir', '-r', TREE/'backend/requirements.lock'])
    command('pip-check', [PYTHON, '-m', 'pip', 'check'])
    # Keep both interpreter prefixes compatible with historical process helpers.
    prefix = base.resolve().parent.parent
    assert prefix.is_relative_to((WORK/'python').resolve())
    command('base-python-dependencies', [PYTHON, '-m', 'pip', 'install', '--prefix', prefix,
             '--ignore-installed', '--no-cache-dir', '-r', TREE/'backend/requirements.lock'])
    command('base-python-pip-check', [WORK/'uv/uv', 'pip', 'check', '--python', base])
    save('python-environment.json', {'version': run(PYTHON, '--version').decode().strip(),
         'packages': json.loads(run(PYTHON, '-m', 'pip', 'list', '--format=json')),
         'requirements_sha256': hashlib.sha256((TREE/'backend/requirements.lock').read_bytes()).hexdigest(),
         'base_python': str(base), 'frontend_installed': False})
    for record in json.loads((PRIOR/'postgresql-packages.json').read_text()):
        name = Path(record['Filename']).name
        download('https://apt.postgresql.org/pub/repos/apt/' + record['Filename'], name, record['SHA256'])
        command('unpack-' + record['Package'], ['dpkg-deb', '-x', WORK/'downloads'/name, WORK/'pgroot'])
    for binary in ['postgres', 'initdb', 'psql', 'pg_ctl']:
        linkage = run('ldd', PG/binary).decode()
        assert 'not found' not in linkage, linkage
        (EVIDENCE/('ldd-'+binary+'.txt')).write_text(linkage,encoding='utf-8')
    assert '16.15' in run(PG/'postgres', '--version').decode()
    print('LOCKED_BACKEND_RUNTIME_PREPARED', flush=True)



def frontend():
    import base64
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

    integrity("after-frontend-install")
    print("FRONTEND_PREPARATION_PASS",flush=True)


if __name__=="__main__":
    {"setup":setup,"frontend":frontend}[sys.argv[1]]()
