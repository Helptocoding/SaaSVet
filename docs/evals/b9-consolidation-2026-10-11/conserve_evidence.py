"""Preserve the frozen local evidence as portable, byte-verifiable Git assets.

No application imports, database access, providers, commits, or source removal.
Restore/verify need only Python's standard library. Paths in archives stay relative
to the repository and all existing destinations are refused on restore.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CHUNK = 128 * 1024
PART_BYTES = 20 * 1024 * 1024
HISTORICAL_SHA = '68a4a77252060fc2d5eae66c2e48423f85406e8c'
HISTORICAL_PATHS = [
    'docs/evals/e4-causal-diagnosis-2026-10-03.md',
    'docs/evals/e4-causal-diagnosis-2026-10-03/',
    'docs/evals/e4-causal-diagnosis-results.json',
]
SECRET_PATTERNS = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'openai_key': re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}'),
    'github_token': re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}'),
    'aws_access_key': re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
    'slack_token': re.compile(rb'\bxox[baprs]-[A-Za-z0-9-]{20,}'),
    'meta_token': re.compile(rb'\bEAA[A-Za-z0-9]{80,}'),
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            value.update(chunk)
    return value.hexdigest()


def save(name, data):
    output = HERE / name
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)


def git(*args):
    return subprocess.run(['rtk', 'proxy', 'git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def safe_relative(name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or not rel.parts or any(p in ('..', '.') or ':' in p for p in rel.parts) or '\\' in name:
        raise ValueError('Unsafe relative evidence path')
    return rel


def fs_path(path):
    """Use Windows extended paths for deep historical evidence, after validation."""
    absolute = str(Path(path).resolve())
    if os.name != 'nt' or absolute.startswith('\\\\?\\'):
        return Path(absolute)
    if absolute.startswith('\\\\'):
        return Path('\\\\?\\UNC\\' + absolute[2:])
    return Path('\\\\?\\' + absolute)


def target_path(base, name):
    rel = safe_relative(name)
    target = base.joinpath(*rel.parts).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError('Evidence path escapes destination')
    return fs_path(target)


def recover_history():
    output = HERE / 'historical-provenance.json'
    if output.exists():
        prior = json.loads(output.read_text(encoding='utf-8'))
        if all((ROOT / x['path']).is_file() and digest(ROOT / x['path']) == x['sha256'] for x in prior['files']):
            print('Historical provenance already verified', flush=True)
            return
        raise RuntimeError('Existing historical provenance no longer matches; refusing overwrite')
    work = ROOT / '.ocr' / 'sessions' / 'b9-consolidation-2026-10-11'
    work.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(dir=work, prefix='history-') as temporary:
        import tarfile
        tar_path = Path(temporary) / 'historical.tar'
        git('archive', '--format=tar', '--output=' + str(tar_path), HISTORICAL_SHA, '--', *HISTORICAL_PATHS)
        with tarfile.open(tar_path, 'r:') as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError('Historical archive contains non-file member')
                target = target_path(ROOT, member.name)
                data = archive.extractfile(member).read()
                if target.exists():
                    if not target.is_file() or target.read_bytes() != data:
                        raise FileExistsError('Historical destination differs: ' + member.name)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                records.append({'path': member.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    save('historical-provenance.json', {
        'schema': 'b9-historical-provenance-v1', 'source_commit': HISTORICAL_SHA,
        'method': 'Git archive of exact historical blobs; no cherry-pick, merge or branch switch',
        'count': len(records), 'files': sorted(records, key=lambda r: r['path']),
    })
    print('Recovered historical files: ' + str(len(records)), flush=True)


def keep_readable(path, group):
    name = Path(path).name
    p = ROOT / path
    if p.suffix.lower() == '.md':
        return True
    if str(PurePosixPath(path).parent) == group and p.suffix.lower() == '.py':
        return True
    markers = ('manifest', 'artifact-index', 'physical-verification', 'scenario-result',
               'execution-receipt', 'authorized-verification', 'observed-predicate-blockers',
               'observed-window-limitation', 'execution-summary', 'final-phase-receipt',
               'closure.json', 'input-integrity', 'r204-duration-audit')
    return p.suffix.lower() == '.json' and p.stat().st_size <= 2 * 1024 * 1024 and any(m in name for m in markers)


def inspect_stream(stream, destination=None):
    value, size, tail, labels = hashlib.sha256(), 0, b'', set()
    for block in iter(lambda: stream.read(CHUNK), b''):
        value.update(block)
        size += len(block)
        if destination is not None:
            destination.write(block)
        sample = tail + block
        labels.update(label for label, pattern in SECRET_PATTERNS.items() if pattern.search(sample))
        tail = sample[-512:]
    return size, value.hexdigest(), sorted(labels)


def pack():
    if (HERE / 'preservation-manifest.json').exists():
        raise FileExistsError('Preservation manifest already exists; verify instead of overwriting')
    prior = json.loads((ROOT / 'docs/evals/inbox-whatsapp-closure-review-2026-10-11/git-inventory.json').read_text(encoding='utf-8'))
    grouped = {}
    for row in prior['untracked_files']:
        name = row['path']
        if name.startswith('docs/evals/') and len(PurePosixPath(name).parts) > 3:
            group = '/'.join(PurePosixPath(name).parts[:3])
            grouped.setdefault(group, []).append(name)
    assets = HERE / 'evidence-packages'
    assets.mkdir(exist_ok=True)
    work = ROOT / '.ocr' / 'sessions' / 'b9-consolidation-2026-10-11'
    work.mkdir(parents=True, exist_ok=True)
    bundles, findings = [], []
    for group, names in sorted(grouped.items()):
        print('Packing ' + group + ' (' + str(len(names)) + ' files)', flush=True)
        records = []
        with tempfile.TemporaryDirectory(dir=work, prefix='pack-') as temporary:
            zip_path = Path(temporary) / 'payload.zip'
            existing = sorted(assets.glob(PurePosixPath(group).name + '.zip.part-*'))
            parts = []
            if existing:
                for number, target in enumerate(existing, 1):
                    if target.name != PurePosixPath(group).name + '.zip.part-' + str(number).zfill(3):
                        raise ValueError('Non-contiguous existing package parts')
                    parts.append({'path': target.relative_to(HERE).as_posix(), 'bytes': target.stat().st_size, 'sha256': digest(target)})
                with zip_path.open('xb') as output:
                    for target in existing:
                        with target.open('rb') as source:
                            shutil.copyfileobj(source, output, CHUNK)
                print('Reusing existing package after member/hash verification', flush=True)
            mode = 'r' if existing else 'w'
            with zipfile.ZipFile(zip_path, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                if existing and (sorted(archive.namelist()) != sorted(names) or len(set(n.casefold() for n in names)) != len(names)):
                    raise ValueError('Existing archive member inventory differs')
                for name in sorted(names):
                    safe_relative(name)
                    source = ROOT / name
                    if not source.is_file() or source.is_symlink():
                        raise ValueError('Frozen evidence missing or not a regular file: ' + name)
                    info = zipfile.ZipInfo(name, (2026, 10, 11, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    if existing:
                        with archive.open(name) as stream:
                            size, sha, labels = inspect_stream(stream)
                        if source.stat().st_size != size or digest(source) != sha:
                            raise ValueError('Existing package differs from original: ' + name)
                    else:
                        with source.open('rb') as stream, archive.open(info, 'w', force_zip64=True) as dest:
                            size, sha, labels = inspect_stream(stream, dest)
                    if labels:
                        findings.append({'path': name, 'rules': sorted(labels)})
                    records.append({'path': name, 'bytes': size, 'sha256': sha,
                                    'readable_in_git': keep_readable(name, group)})
            if not existing:
              with zip_path.open('rb') as stream:
                number = 1
                while stream.tell() < zip_path.stat().st_size:
                    relative = 'evidence-packages/' + PurePosixPath(group).name + '.zip.part-' + str(number).zfill(3)
                    target = HERE / relative
                    if target.exists():
                        raise FileExistsError('Refusing package overwrite: ' + relative)
                    value, size = hashlib.sha256(), 0
                    with target.open('xb') as output:
                        while size < PART_BYTES:
                            block = stream.read(min(CHUNK, PART_BYTES - size))
                            if not block:
                                break
                            output.write(block)
                            value.update(block)
                            size += len(block)
                    parts.append({'path': relative, 'bytes': size, 'sha256': value.hexdigest()})
                    number += 1
            bundles.append({'source_directory': group, 'files': records, 'parts': parts,
                            'zip_sha256': digest(zip_path), 'uncompressed_bytes': sum(r['bytes'] for r in records)})
            save('preservation-checkpoint.json', {'status': 'PARTIAL_NOT_ACCEPTANCE', 'bundles': bundles, 'findings': findings})
    manifest = {
        'schema': 'b9-evidence-preservation-v1', 'date': '2026-10-11',
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'branch': git('branch', '--show-current').decode().strip(),
        'format': 'ZIP/deflate, original relative paths; concatenate numbered parts in order',
        'maximum_part_bytes': PART_BYTES, 'source_inventory_date': prior['date'],
        'source_files_removed': False, 'historical_receipts_modified': False,
        'bundles': bundles, 'files': sum(len(b['files']) for b in bundles),
        'uncompressed_bytes': sum(b['uncompressed_bytes'] for b in bundles),
        'package_bytes': sum(p['bytes'] for b in bundles for p in b['parts']),
    }
    save('preservation-manifest.json', manifest)
    save('privacy-scan.json', {'method': 'Streaming high-confidence token/private-key patterns; no values emitted',
                             'rules': sorted(SECRET_PATTERNS), 'files': manifest['files'],
                             'bytes': manifest['uncompressed_bytes'], 'findings': findings,
                             'limitation': 'Pattern scan is not legal approval or proof of absence of all secrets/PII.'})
    print(json.dumps({k: manifest[k] for k in ('files', 'uncompressed_bytes', 'package_bytes')}) + '; findings=' + str(len(findings)), flush=True)


def checked_zip(bundle, temporary):
    path = Path(temporary) / 'payload.zip'
    with path.open('xb') as output:
        for part in bundle['parts']:
            source = target_path(HERE, part['path'])
            if source.stat().st_size != part['bytes'] or digest(source) != part['sha256']:
                raise ValueError('Package part integrity failed: ' + part['path'])
            with source.open('rb') as stream:
                shutil.copyfileobj(stream, output, CHUNK)
    if digest(path) != bundle['zip_sha256']:
        raise ValueError('Concatenated ZIP integrity failed')
    return path


def restore_bundle(bundle, zip_path, destination, allow_identical=False):
    expected = {r['path']: r for r in bundle['files']}
    with zipfile.ZipFile(zip_path, 'r') as archive:
        names = archive.namelist()
        if len(names) != len(expected) or len(set(n.casefold() for n in names)) != len(names) or set(names) != set(expected):
            raise ValueError('Unexpected, missing or duplicate ZIP members')
        for name in names:
            target = target_path(destination, name)
            if target.exists():
                if allow_identical and target.is_file() and target.stat().st_size == expected[name]['bytes'] and digest(target) == expected[name]['sha256']:
                    continue
                raise FileExistsError('Restore refuses existing target: ' + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            value, size = hashlib.sha256(), 0
            with archive.open(name) as stream, target.open('xb') as output:
                for block in iter(lambda: stream.read(CHUNK), b''):
                    output.write(block)
                    value.update(block)
                    size += len(block)
            if size != expected[name]['bytes'] or value.hexdigest() != expected[name]['sha256']:
                raise ValueError('Restored evidence integrity failed: ' + name)
            if digest(target) != expected[name]['sha256']:
                raise ValueError('On-disk restored evidence integrity failed: ' + name)


def verify(destination=None, allow_identical=False):
    manifest = json.loads((HERE / 'preservation-manifest.json').read_text(encoding='utf-8'))
    work = ROOT / '.ocr' / 'sessions' / 'b9-consolidation-2026-10-11'
    work.mkdir(parents=True, exist_ok=True)
    root_dest = fs_path(destination) if destination else None
    if root_dest:
        if root_dest.exists() and any(root_dest.iterdir()) and not allow_identical:
            raise FileExistsError('Restore requires a new or empty destination')
        root_dest.mkdir(parents=True, exist_ok=True)
    checked, original, total_bytes = 0, 0, 0
    for bundle in manifest['bundles']:
        print('Verifying restore ' + bundle['source_directory'], flush=True)
        required = bundle['uncompressed_bytes'] + sum(p['bytes'] for p in bundle['parts']) + 256 * CHUNK
        if shutil.disk_usage(work).free < required:
            raise OSError('Insufficient free space for isolated bundle verification')
        with tempfile.TemporaryDirectory(dir=fs_path(work), prefix='restore-') as temporary:
            temp = Path(temporary).resolve()
            if not temp.is_relative_to(fs_path(work).resolve()):
                raise ValueError('Temporary restore escaped intended workspace')
            zip_path = checked_zip(bundle, temp)
            restore_bundle(bundle, zip_path, root_dest or temp / 'clean-root', allow_identical)
            for row in bundle['files']:
                if not root_dest:
                    source = ROOT / row['path']
                    if not source.is_file() or digest(source) != row['sha256']:
                        raise ValueError('Original frozen file changed: ' + row['path'])
                    original += 1
                checked += 1
                total_bytes += row['bytes']
    result = {'status': 'PASS', 'method': 'Every package part and ZIP verified; every member restored to clean disk and rehashed',
              'files_restored_and_verified': checked, 'bytes_restored_and_verified': total_bytes,
              'original_files_unchanged': original if not root_dest else 'NOT_CHECKED_ON_EXTERNAL_RESTORE',
              'bundles': len(manifest['bundles']), 'manifest_sha256': digest(HERE / 'preservation-manifest.json'),
              'application_tests_executed': False, 'commit_created': False}
    if not root_dest:
        save('preservation-verification.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('recover-history', 'pack', 'verify', 'restore'))
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--allow-identical', action='store_true', help='Allow an existing destination only when every existing evidence file has its exact recorded hash; never overwrite')
    args = parser.parse_args()
    if args.command == 'recover-history':
        recover_history()
    elif args.command == 'pack':
        pack()
    elif args.command == 'restore':
        if not args.destination:
            parser.error('restore requires --destination')
        verify(args.destination, args.allow_identical)
    else:
        verify()
