"""Read-only candidate assembly and preflight. Does not execute application tests."""
from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
SHA = '194772677ca4e9fe1a1dec7f4dafa48396a6c583'
WORK = Path(os.environ['TEMP']) / 'b9i-1947726'
TREE = WORK / 'src'
PYTHON = Path(os.environ['TEMP']) / 'vet-b8b-locked/Scripts/python.exe'
PG = Path(os.environ['TEMP']) / 'vet-b8b-pg16-bin/pgsql/bin'


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def run(*args, cwd=REPO):
    return subprocess.check_output(['rtk', 'proxy', *map(str, args)], cwd=cwd, stdin=subprocess.DEVNULL)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Memory(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                *[(name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]]


def resources():
    mem = Memory()
    mem.length = ctypes.sizeof(mem)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        raise OSError('Cannot read memory budget')
    return {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'physical_total': mem.total, 'physical_available': mem.available,
            'page_available': mem.page_available, 'disk_available': shutil.disk_usage(REPO).free}


def download(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main():
    resume = '--resume-assembly' in sys.argv
    if WORK.exists() and not resume:
        raise RuntimeError('Campaign assembly already exists; refusing to overwrite or rerun')
    if resume:
        assert json.loads((EVIDENCE / 'assembly.json').read_text())['phase'] == 'PREPARING'
        save('assembly-incident.json', {'phase': 'PREPARATION_ONLY', 'tests_executed': False,
            'cause': 'RTK proxy buffers interactive cat-file output; byte verification changed to Git blob SHA-1 calculation',
            'owned_processes_stopped': [30892, 33872, 34876, 29308], 'candidate_sources_modified': False,
            'export_issue': 'Git archive applied host autocrlf; rebuild export with core.autocrlf=false and core.eol=lf before sealing or tests'})
    else:
        WORK.mkdir()
    save('assembly.json', {'candidate_sha': SHA, 'workspace': str(WORK), 'tree': str(TREE),
                           'python': str(PYTHON), 'pg_bin': str(PG), 'phase': 'PREPARING'})
    before = resources()
    # Reserve 1 GiB disk and 2 GiB physical memory beyond a sequential block budget.
    budget = {'sequential_only': True, 'memory_block_bytes': 3 * 1024**3,
              'memory_reserve_bytes': 2 * 1024**3, 'disk_campaign_bytes': 2 * 1024**3,
              'disk_reserve_bytes': 1024**3, 'no_foreign_process_termination': True}
    if not resume:
        save('resource-preflight.json', {'observed': before, 'budget': budget,
        'memory_ok': before['physical_available'] >= budget['memory_block_bytes'] + budget['memory_reserve_bytes'],
            'disk_ok': before['disk_available'] >= budget['disk_campaign_bytes'] + budget['disk_reserve_bytes']})
    if before['physical_available'] < 5 * 1024**3 or (not resume and before['disk_available'] < 3 * 1024**3):
        raise RuntimeError('Insufficient resources for frozen sequential campaign budget')
    if not resume:
        save('checkout-before.json', {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
        'branch': run('git', 'branch', '--show-current').decode().strip(),
        'status': run('git', 'status', '--porcelain=v1', '-uall').decode(),
        'unrelated': {p: {'exists': (REPO / p).exists(), 'sha256': sha256((REPO / p).read_bytes()) if (REPO / p).exists() else None}
                      for p in ('DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json')}})
    archive = WORK / 'candidate.tar'
    run('git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'archive', '--format=tar', '-o', archive, SHA)
    TREE.mkdir(exist_ok=resume)
    with tarfile.open(archive) as tf:
        tf.extractall(TREE, filter='data')
    assert run('git', 'rev-parse', '--show-object-format').decode().strip() == 'sha1'
    listing = run('git', 'ls-tree', '-rz', '--full-tree', SHA)
    entries = []
    for record in listing.split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        if kind != 'blob':
            raise RuntimeError('Unsupported non-blob candidate entry')
        entries.append((name.decode(), mode, oid))
    sources = {}
    mismatches = []
    for name, mode, oid in entries:
        path = TREE / name
        data = path.read_bytes() if path.is_file() else b''
        actual_oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        sources[name] = {'git_blob': oid, 'git_mode': mode, 'size': len(data), 'sha256': sha256(data)}
        if actual_oid != oid:
            mismatches.append(name)
    if mismatches:
        save('export-mismatches.json', mismatches)
        raise RuntimeError('Exact Git export verification failed; see export-mismatches.json')
    save('candidate-sources.json', {'candidate_sha': SHA, 'files': sources, 'count': len(sources),
                                   'total_bytes': sum(v['size'] for v in sources.values()), 'mismatches': mismatches})
    # Archive is our own temporary duplicate; retain its digest before freeing it.
    archive_hash = sha256(archive.read_bytes())
    archive.unlink()
    scope = json.loads((EVIDENCE / 'scope-manifest.json').read_text(encoding='utf-8'))
    save('witness-check.json', [{'path': w['path'], 'expected': w['sha256'],
        'actual': sha256((REPO / w['path']).read_bytes()),
        'matches': w['sha256'] == sha256((REPO / w['path']).read_bytes())} for w in scope['witnesses']])
    lock = TREE / 'backend/requirements.lock'
    packages = json.loads(run(PYTHON, '-m', 'pip', 'list', '--format=json'))
    normalize = lambda s: s.lower().replace('_', '-').replace('.', '-')
    installed = {normalize(p['name']): p['version'] for p in packages}
    pinned = {}
    for line in lock.read_text().splitlines():
        if '==' in line and not line.lstrip().startswith('#'):
            name, version = line.strip().split('==')
            pinned[normalize(name.split('[')[0])] = version
    differences = {k: {'expected': v, 'actual': installed.get(k)} for k, v in pinned.items() if installed.get(k) != v}
    save('python-environment.json', {'executable': str(PYTHON), 'version': run(PYTHON, '--version').decode().strip(),
        'lock_sha256': sha256(lock.read_bytes()), 'packages': packages, 'lock_differences': differences,
        'pip_check': run(PYTHON, '-m', 'pip', 'check').decode().strip()})
    if differences:
        raise RuntimeError('Locked Python environment mismatch')
    # Official Node 20 release, byte-verified against the same release SHASUMS.
    releases = json.loads(download('https://nodejs.org/dist/index.json'))
    release = next(r for r in releases if r['version'].startswith('v20.') and 'win-x64-zip' in r['files'])
    version = release['version']
    filename = f'node-{version}-win-x64.zip'
    url = f'https://nodejs.org/dist/{version}/{filename}'
    sums = download(f'https://nodejs.org/dist/{version}/SHASUMS256.txt')
    expected = next(line.split()[0] for line in sums.decode().splitlines() if line.split()[-1] == filename)
    data = download(url)
    if sha256(data) != expected:
        raise RuntimeError('Node download SHA256 mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(WORK)
    node = WORK / filename.removesuffix('.zip') / 'node.exe'
    # pnpm package is pinned and integrity checked against npm registry metadata.
    pnpm_version = '9.15.9'
    metadata = json.loads(download(f'https://registry.npmjs.org/pnpm/{pnpm_version}'))
    pnpm_data = download(metadata['dist']['tarball'])
    import base64
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(pnpm_data).digest()).decode()
    if integrity != metadata['dist']['integrity']:
        raise RuntimeError('pnpm download integrity mismatch')
    pnpm_dir = WORK / 'pnpm'
    with tarfile.open(fileobj=io.BytesIO(pnpm_data), mode='r:gz') as tf:
        tf.extractall(pnpm_dir, filter='data')
    pnpm = pnpm_dir / 'package/bin/pnpm.cjs'
    versions = {'node': run(node, '--version').decode().strip(), 'pnpm': run(node, pnpm, '--version').decode().strip(),
        'postgres': run(PG / 'postgres.exe', '--version').decode().strip(), 'node_url': url, 'node_sha256': expected,
        'pnpm_integrity': integrity, 'node_executable': str(node), 'pnpm_script': str(pnpm)}
    save('toolchain.json', versions)
    save('assembly.json', {'candidate_sha': SHA, 'workspace': str(WORK), 'tree': str(TREE),
        'python': str(PYTHON), 'pg_bin': str(PG), 'node': str(node), 'pnpm': str(pnpm),
        'phase': 'ASSEMBLED_NOT_EXECUTED', 'archive_sha256': archive_hash,
        'exact_git_blobs_verified': len(sources), 'resource_after_assembly': resources()})
    print(json.dumps({'phase': 'ASSEMBLED_NOT_EXECUTED', 'files': len(sources), 'versions': versions, 'resources': resources()}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        save('preparation-incident.json', {'type': type(exc).__name__, 'message': str(exc), 'tests_executed': False})
        raise
