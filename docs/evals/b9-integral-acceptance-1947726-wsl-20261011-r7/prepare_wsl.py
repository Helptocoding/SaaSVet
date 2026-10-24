"""Prepare an isolated Linux candidate; no application test is run here."""
from __future__ import annotations
import base64
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

EVIDENCE = Path(__file__).resolve().parent
REPO = EVIDENCE.parents[2]
OLD = REPO / 'docs/evals/b9-integral-acceptance-1947726'
SHA = '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
WORK = Path('/home/lap/b9i-wsl-1947726-20261011-r7')
TREE = WORK / 'src'
RTK = WORK / 'tools/rtk'
PYTHON = WORK / 'venv/bin/python'
PG = WORK / 'pgroot/usr/lib/postgresql/16/bin'
NODE = WORK / 'node-v20.20.2-linux-x64/bin/node'
PNPM = WORK / 'pnpm/package/bin/pnpm.cjs'
DATA = WORK / 'pgdata'
PORT = 35479
GIB = 1024**3

def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def resources():
    mem = {k: int(v.strip().split()[0]) * 1024 for k, v in
           (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
    return {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'physical_available': mem['MemAvailable'], 'physical_total': mem['MemTotal'],
            'disk_available': shutil.disk_usage('/mnt/c').free,
            'linux_virtual_disk_available': shutil.disk_usage('/home/lap').free}

def environment():
    # Do not import Windows pnpm or application/provider secrets through PATH/env.
    return dict(HOME=str(WORK / 'home'), PATH=':'.join(map(str, [RTK.parent, NODE.parent, PYTHON.parent, PG,
        WORK / 'uv', Path('/usr/local/bin'), Path('/usr/bin'), Path('/bin')])),
        LANG='C.UTF-8', LC_ALL='C.UTF-8', TMPDIR=str(WORK / 'tmp'), PYTHONDONTWRITEBYTECODE='1',
        PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', DJANGO_SETTINGS_MODULE='config.settings',
        SECRET_KEY='b9i-wsl-disposable-test-only', ENVIRONMENT='dev', DEBUG='False',
        DATABASE_URL=f'postgresql://b9e@127.0.0.1:{PORT}/test_b9i_control',
        DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='', DISCORD_WEBHOOK_URL='',
        HEALTHCHECK_AGENT_WORKER_URL='', HEALTHCHECK_AGENT_SENDER_URL='',
        AGENT_LLM_API_KEY='', AGENT_LLM_BASE_URL='', WHATSAPP_ACCESS_TOKEN='',
        WHATSAPP_APP_SECRET='', WHATSAPP_VERIFY_TOKEN='',
        VITE_API_URL='http://127.0.0.1:8000/api',
        LD_LIBRARY_PATH=str(WORK / 'pgroot/usr/lib/x86_64-linux-gnu'),
        UV_PYTHON_INSTALL_DIR=str(WORK / 'python'), UV_CACHE_DIR=str(WORK / 'uv-cache'),
        UV_PYTHON_BIN_DIR=str(WORK / 'python-bin'), PIP_CACHE_DIR=str(WORK / 'pip-cache'),
        XDG_CACHE_HOME=str(WORK / 'home/.cache'), XDG_DATA_HOME=str(WORK / 'home/.local/share'))

def run(*args, cwd=REPO, env=None):
    prefix = [str(RTK), 'proxy'] if RTK.exists() else []
    return subprocess.check_output(prefix + list(map(str, args)), cwd=cwd,
        env=env or environment(), stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)

def command(label, args, cwd=WORK):
    receipt = EVIDENCE / (label + '.command.json')
    if receipt.exists():
        raise RuntimeError('Refusing duplicate command: ' + label)
    started = time.monotonic()
    argv = [str(RTK), 'proxy', *map(str, args)]
    save(receipt.name, {'state':'RUNNING', 'argv':argv, 'cwd':str(cwd), 'resources_before':resources()})
    with (EVIDENCE / (label + '.log')).open('wb') as log:
        p = subprocess.run(argv, cwd=cwd, env=environment(), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT)
    save(receipt.name, {'state':'COMPLETED', 'argv':argv, 'cwd':str(cwd), 'exit_code':p.returncode,
        'seconds':time.monotonic()-started, 'resources_after':resources()})
    if p.returncode:
        raise RuntimeError(label + ' exit=' + str(p.returncode))
    print(label + ': PASS', flush=True)

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent':'B9E-candidate-evaluation'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

def download(url, name, digest=None):
    data = fetch(url)
    actual = sha256(data)
    if digest and actual != digest.removeprefix('sha256:'):
        raise RuntimeError('Download checksum mismatch: ' + name)
    (WORK / 'downloads' / name).write_bytes(data)
    journal = EVIDENCE / 'downloads.json'
    records = json.loads(journal.read_text()) if journal.exists() else []
    records.append({'url':url, 'file':name, 'sha256':actual, 'expected_sha256':digest, 'bytes':len(data)})
    save(journal.name, records)
    return data

def extract(data, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
        archive.extractall(destination, filter='data')

def github_asset(repo, name, destination, executable):
    release = json.loads(fetch('https://api.github.com/repos/' + repo + '/releases/latest'))
    asset = next(a for a in release['assets'] if a['name'] == name)
    digest = asset.get('digest')
    if not digest:
        checksum = next(a for a in release['assets'] if a['name'] == name + '.sha256')
        digest = fetch(checksum['browser_download_url']).decode().split()[0]
    data = download(asset['browser_download_url'], name, digest)
    extract(data, destination)
    found = next(destination.rglob(executable))
    found.chmod(0o755)
    save(repo.replace('/', '-') + '.json', {'tag':release['tag_name'], 'asset':asset['name'],
        'sha256':sha256(data), 'executable':str(found)})
    return found

def integrity(label):
    manifest = json.loads((EVIDENCE / 'candidate-sources.json').read_text())
    mismatches = [row['path'] for row in manifest['files']
        if not (TREE / row['path']).is_file() or sha256((TREE / row['path']).read_bytes()) != row['sha256']]
    save('integrity-' + label + '.json', {'checked_files':len(manifest['files']), 'mismatches':mismatches})
    if mismatches:
        raise RuntimeError('Candidate source changed')

def assemble():
    if WORK.exists() or (EVIDENCE / 'assembly.json').exists():
        raise RuntimeError('Workspace/assembly already exists')
    WORK.mkdir()
    for name in ('tmp','home','downloads','tools'):
        (WORK / name).mkdir()
    save('assembly.json', {'candidate_sha':SHA, 'workspace':str(WORK), 'tree':str(TREE),
        'python':str(PYTHON), 'pg_bin':str(PG), 'node':str(NODE), 'pnpm':str(PNPM),
        'phase':'PREPARING', 'os':'Ubuntu-24.04 / WSL2', 'port':PORT})
    # RTK is bootstrapped before invoking any command that has its filter.
    binary = github_asset('rtk-ai/rtk', 'rtk-x86_64-unknown-linux-musl.tar.gz', WORK / 'rtk-archive', 'rtk')
    shutil.copy2(binary, RTK)
    save('rtk-version.json', {'version':run(RTK, '--version').decode().strip(), 'gain':run(RTK, 'gain').decode()})
    snapshot = resources()
    save('resource-preparation.json', {'observed':snapshot,
        'preparation_budget_bytes':GIB, 'suite_budget_bytes':3*GIB,
        'memory_reserve_bytes':2*GIB, 'backing_disk_reserve_bytes':GIB,
        'check_host_memory_before_formal_execution':True})
    save('checkout-before.json', {'head':run('git','rev-parse','HEAD').decode().strip(),
        'branch':run('git','branch','--show-current').decode().strip(),
        'status':run('git','--no-optional-locks','status','--porcelain=v1','-uall').decode(),
        'index_sha256':sha256((REPO/'.git/index').read_bytes()),
        'unrelated':{p:{'exists':(REPO/p).exists(), 'sha256':sha256((REPO/p).read_bytes()) if (REPO/p).exists() else None}
            for p in ('DEPLOY_VPS_PLAN.md','DEPLOY_VPS_STATUS.md','skills-lock.json')},
        'prior_campaign_files':{str(p.relative_to(OLD)):sha256(p.read_bytes()) for p in OLD.rglob('*') if p.is_file()}})
    archive = run('git','-c','core.autocrlf=false','-c','core.eol=lf','archive','--format=tar',SHA)
    extract(archive, TREE)
    objects = run('git','ls-tree','-r','-z',SHA).split(b'\0')
    files, mismatch = [], []
    for entry in filter(None, objects):
        metadata, raw_path = entry.split(b'\t',1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        data = (TREE / path).read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if kind != 'blob' or actual != oid:
            mismatch.append(path)
        files.append({'path':path,'git_blob':oid,'mode':mode,'sha256':sha256(data),'bytes':len(data)})
    save('candidate-sources.json', {'candidate_sha':SHA,'archive_sha256':sha256(archive),'files':files,'mismatches':mismatch})
    if mismatch:
        raise RuntimeError('Candidate export differs from Git blobs')
    shutil.copy2(OLD/'scope-manifest.json', EVIDENCE/'scope-manifest.json')
    # Helpers and authorized plan are prepared before assembly, then sealed.
    print('ASSEMBLED: '+str(len(files))+' exact Git blobs',flush=True)

def runtimes():
    uv = github_asset('astral-sh/uv','uv-x86_64-unknown-linux-gnu.tar.gz',WORK/'uv-archive','uv')
    (WORK/'uv').mkdir()
    shutil.copy2(uv,WORK/'uv/uv')
    command('python-install',[WORK/'uv/uv','python','install','3.13.2'])
    base = next((WORK/'python').glob('cpython-3.13.2-*/bin/python3.13'))
    command('venv-create',[base,'-m','venv',WORK/'venv'])
    command('python-dependencies',[PYTHON,'-m','pip','install','--no-cache-dir','-r',TREE/'backend/requirements.lock'])
    command('pip-check',[PYTHON,'-m','pip','check'])
    # Legacy process tests select sys._base_executable. Prepare that private prefix
    # from the identical lock before sealing; no candidate or interpreter redirect.
    prefix = base.resolve().parent.parent
    assert prefix.is_relative_to((WORK/'python').resolve()) and prefix != (WORK/'python').resolve()
    command('base-python-dependencies',[PYTHON,'-m','pip','install','--prefix',prefix,
        '--ignore-installed','--no-cache-dir','-r',TREE/'backend/requirements.lock'])
    command('base-python-pip-check',[WORK/'uv/uv','pip','check','--python',base])
    metadata_code = "import importlib.metadata as m,json,sys,sysconfig; print(json.dumps(dict(executable=sys.executable,base_executable=sys._base_executable,prefix=sys.prefix,site_packages=sysconfig.get_path('purelib'),packages=sorted([dict(name=d.metadata['Name'],version=d.version) for d in m.distributions()],key=lambda x:x['name'].lower()))))"
    save('base-python-environment.json',json.loads(run(base,'-B','-c',metadata_code)))

    save('python-environment.json', {'version':run(PYTHON,'--version').decode().strip(),
        'packages':json.loads(run(PYTHON,'-m','pip','list','--format=json')),
        'requirements_sha256':sha256((TREE/'backend/requirements.lock').read_bytes())})
    name='node-v20.20.2-linux-x64.tar.xz'
    checks=fetch('https://nodejs.org/dist/v20.20.2/SHASUMS256.txt').decode()
    digest=next(line.split()[0] for line in checks.splitlines() if line.split()[-1]==name)
    extract(download('https://nodejs.org/dist/v20.20.2/'+name,name,digest),WORK)
    metadata=json.loads(fetch('https://registry.npmjs.org/pnpm/9.15.9'))
    package=fetch(metadata['dist']['tarball'])
    expected=metadata['dist']['integrity'].removeprefix('sha512-')
    if base64.b64encode(hashlib.sha512(package).digest()).decode()!=expected:
        raise RuntimeError('pnpm registry SRI mismatch')
    extract(package,WORK/'pnpm')
    save('pnpm-package.json',{'version':metadata['version'],'url':metadata['dist']['tarball'],
        'integrity':metadata['dist']['integrity'],'sha256':sha256(package)})
    save('toolchain.json',{'node':run(NODE,'--version').decode().strip(),
        'pnpm':run(NODE,PNPM,'--version').decode().strip(),'python':run(PYTHON,'--version').decode().strip()})
    command('frontend-install',[NODE,PNPM,'install','--frozen-lockfile','--store-dir',WORK/'pnpm-store'],cwd=TREE/'frontend')
    integrity('after-install')
    print('RUNTIMES_PREPARED',flush=True)

def postgres_packages():
    index_url='https://apt.postgresql.org/pub/repos/apt/dists/noble-pgdg/main/binary-amd64/Packages.gz'
    raw=download(index_url,'pgdg-Packages.gz')
    records=[]
    for block in gzip.decompress(raw).decode().split('\n\n'):
        record={}
        for line in block.splitlines():
            if line and not line[0].isspace() and ': ' in line:
                key,value=line.split(': ',1); record[key]=value
        records.append(record)
    selected=[]
    for package in ('postgresql-16','postgresql-client-16','libpq5'):
        matches=[r for r in records if r.get('Package')==package and
            (package=='libpq5' or (r['Version'].startswith('16.15-') and '~' not in r['Version']))]
        if not matches:
            raise RuntimeError('Exact stable PostgreSQL package unavailable: '+package)
        record=matches[0]
        name=Path(record['Filename']).name
        download('https://apt.postgresql.org/pub/repos/apt/'+record['Filename'],name,record['SHA256'])
        command('unpack-'+package,['dpkg-deb','-x',WORK/'downloads'/name,WORK/'pgroot'])
        selected.append(record)
    save('postgresql-packages.json',selected)
    for binary in ('postgres','initdb','psql','pg_ctl'):
        output=run('ldd',PG/binary).decode()
        (EVIDENCE/('ldd-'+binary+'.txt')).write_text(output,encoding='utf-8')
    print('POSTGRES_PACKAGES_UNPACKED; inspect ldd before starting',flush=True)

def main():
    action=sys.argv[1]
    try:
        {'assemble':assemble,'runtimes':runtimes,'postgres-packages':postgres_packages}[action]()
    except Exception as exc:
        name='preparation-incident-'+action
        serial=1
        while (EVIDENCE/(name+('-'+str(serial) if serial>1 else '')+'.json')).exists():
            serial+=1
        save(name+('-'+str(serial) if serial>1 else '')+'.json',{'type':type(exc).__name__,'message':str(exc),
            'tests_executed':False,'resources':resources()})
        raise

if __name__=='__main__':
    main()
