"""Restore only this campaign's independently inventoried evidence."""
import argparse
import json
from pathlib import Path
import tempfile
import zipfile
from preserve_campaign import ROOT, CHUNK, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RuntimeError('Destination must be absent or empty; existing files are never overwritten')
    manifest = json.loads((ROOT / 'preservation-manifest.json').read_text(encoding='utf-8'))
    expected = {row['path']: row for row in manifest['files']}
    assert len(expected) == len(manifest['files'])
    with tempfile.TemporaryDirectory(prefix='b9i-restore-') as temp:
        archive = Path(temp) / 'campaign.zip'
        with archive.open('wb') as output:
            for part in manifest['parts']:
                path = (ROOT / part['path']).resolve()
                assert path.is_relative_to(ROOT.resolve())
                assert path.stat().st_size == part['size'] and digest(path) == part['sha256']
                with path.open('rb') as stream:
                    while data := stream.read(CHUNK):
                        output.write(data)
        assert archive.stat().st_size == manifest['zip_size'] and digest(archive) == manifest['zip_sha256']
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert len(names) == len(set(names)) and set(names) == set(expected)
            targets = {name: (destination / name).resolve() for name in names}
            assert all(path.is_relative_to(destination) for path in targets.values())
            destination.mkdir(parents=True, exist_ok=True)
            for name, path in targets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as stream, path.open('xb') as output:
                    while data := stream.read(CHUNK):
                        output.write(data)
                assert path.stat().st_size == expected[name]['size'] and digest(path) == expected[name]['sha256']
    print(json.dumps({'state': 'PASS', 'restored_files': len(expected), 'destination': str(destination)}))


if __name__ == '__main__':
    main()
