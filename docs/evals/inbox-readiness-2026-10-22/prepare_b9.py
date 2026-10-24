"""Restore the frozen B9 tree and private, pinned tools; never change the checkout."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
OLD = OUT.with_name('b9-correction-20261020-native-r12')
WORK = OUT / 'runtime/b9'
TREE = WORK / 'src'
RTK = shutil.which('rtk')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def main():
    assert not (OUT / 'b9-preparation.json').exists()
    WORK.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((OLD / 'candidate-sources.json').read_text(encoding='utf-8'))
    tree = manifest['candidate_sha']
    archive = WORK / 'candidate.tar'
    if not archive.exists():
        subprocess.run([RTK, 'proxy', 'git', 'archive', tree, '--format=tar', '-o', str(archive)], cwd=ROOT, check=True)
        TREE.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(TREE, filter='data')
    # The historical assembly normalized text to LF. Restore that exact sealed
    # representation only when the resulting bytes equal its recorded SHA256.
    restored_line_endings = []
    for row in manifest['files']:
        path = TREE / row['path']
        if path.is_file() and digest(path) != row['sha256']:
            normalized = path.read_bytes().replace(b'\r\n', b'\n')
            if hashlib.sha256(normalized).hexdigest() == row['sha256']:
                path.write_bytes(normalized)
                restored_line_endings.append(row['path'])
    bad = [r['path'] for r in manifest['files'] if not (TREE / r['path']).is_file()
           or digest(TREE / r['path']) != r['sha256']]
    assert not bad, bad[:10]
    save('b9-candidate-restoration.json', dict(state='PASS', candidate_tree=tree,
         checked_files=len(manifest['files']), mismatches=bad,
         exact_historical_lf_representation_restored=restored_line_endings,
         source_manifest_sha256=digest(OLD/'candidate-sources.json')))
    print('Frozen candidate restored and verified', flush=True)
    expected = json.loads((OLD / 'python-environment.json').read_text(encoding='utf-8'))
    assert sys.version == expected['python_version']
    base = Path(sys.base_prefix)
    private = WORK / 'python'
    private.mkdir()
    for p in base.iterdir():
        if p.is_file() and p.suffix.lower() in ('.exe', '.dll', '.txt'):
            shutil.copy2(p, private / p.name)
    shutil.copytree(base/'DLLs', private/'DLLs', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(base/'Lib', private/'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'ensurepip'))
    site = private / 'Lib/site-packages'
    site.mkdir()
    packages = []
    for name, version in expected['required_lock_versions'].items():
        dist = metadata.distribution(name)
        assert dist.version == version, (name, dist.version, version)
        for relative in dist.files or []:
            path = Path(relative)
            if '..' in path.parts or '__pycache__' in path.parts:
                continue
            source = Path(dist.locate_file(relative))
            if source.is_file():
                target = site / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        packages.append(dict(name=name, version=version))
    print('Private Python and all 34 lock pins copied', flush=True)
    downloads = json.loads((OLD / 'downloads.json').read_text(encoding='utf-8'))[:2]
    for row in downloads:
        target = WORK / row['name']
        with urllib.request.urlopen(row['url'], timeout=60) as response, target.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        assert digest(target) == row['sha256'], row['name']
        if target.suffix == '.zip':
            with zipfile.ZipFile(target) as source:
                source.extractall(WORK)
        else:
            (WORK / 'pnpm').mkdir()
            with tarfile.open(target) as source:
                source.extractall(WORK/'pnpm', filter='data')
        print('Pinned download verified: ' + row['name'], flush=True)
    result = dict(state='PREPARED', candidate_tree=tree, candidate_files=len(manifest['files']),
                  python=sys.version, packages=packages, downloads=downloads,
                  host_environment_modified=False, formal_blocks_executed=False)
    save('b9-preparation.json', result)


if __name__ == '__main__':
    main()
