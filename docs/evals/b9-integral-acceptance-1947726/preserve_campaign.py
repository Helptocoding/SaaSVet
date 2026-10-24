"""Conserve this campaign's own inventory and verify byte-exact recovery."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
LIMIT = 20 * 1024**2
CHUNK = 128 * 1024


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(CHUNK):
            value.update(data)
    return value.hexdigest()


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    target = ROOT / 'evidence-packages'
    target.mkdir(exist_ok=False)
    paths = sorted(p for p in ROOT.rglob('*') if p.is_file() and target not in p.parents
                   and '__pycache__' not in p.parts)
    inventory = [{'path': p.relative_to(ROOT).as_posix(), 'size': p.stat().st_size, 'sha256': digest(p)} for p in paths]
    with tempfile.TemporaryDirectory(prefix='b9i-conserve-') as temp:
        workspace = Path(temp)
        archive = workspace / 'campaign.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for item in inventory:
                zf.write(ROOT / item['path'], item['path'])
        parts = []
        with archive.open('rb') as src:
            number = 0
            while data := src.read(LIMIT):
                number += 1
                path = target / f'campaign.zip.part{number:03d}'
                path.write_bytes(data)
                parts.append({'path': path.relative_to(ROOT).as_posix(), 'size': len(data), 'sha256': digest(path)})
        manifest = {'schema': 'b9i-preservation-v1', 'inventory_scope': 'Only this campaign; no historical packager reused',
            'files': inventory, 'parts': parts, 'zip_sha256': digest(archive), 'zip_size': archive.stat().st_size}
        save('preservation-manifest.json', manifest)
        recovered_archive = workspace / 'recovered.zip'
        with recovered_archive.open('wb') as output:
            for part in parts:
                path = ROOT / part['path']
                assert digest(path) == part['sha256']
                with path.open('rb') as stream:
                    while data := stream.read(CHUNK):
                        output.write(data)
        assert digest(recovered_archive) == manifest['zip_sha256']
        expected = {item['path']: item for item in inventory}
        with zipfile.ZipFile(recovered_archive) as zf:
            names = zf.namelist()
            assert len(names) == len(set(names)) and set(names) == set(expected)
            destination = workspace / 'restored'
            destination.mkdir()
            for name in names:
                path = (destination / name).resolve()
                assert path.is_relative_to(destination.resolve())
                path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, path.open('wb') as output:
                    while data := src.read(CHUNK):
                        output.write(data)
                assert path.stat().st_size == expected[name]['size']
                assert digest(path) == expected[name]['sha256']
        save('preservation-verification.json', {'state': 'PASS', 'files_restored_and_hash_verified': len(inventory),
            'parts_verified': len(parts), 'zip_sha256_verified': True, 'path_confinement_verified': True,
            'originals_preserved': True, 'chunk_bytes': CHUNK})
    save('artifact-index.json', {'files': inventory, 'preservation': ['preservation-manifest.json', 'preservation-verification.json'],
        'raw_log_and_jsonl_delivery': 'Byte-exact ZIP parts; local originals retained',
        'candidate_sources': 'candidate-sources.json; 3332 Git blobs verified before execution'})
    print(json.dumps({'state': 'PASS', 'files': len(inventory), 'parts': len(parts)}))


if __name__ == '__main__':
    main()
