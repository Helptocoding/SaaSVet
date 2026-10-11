"""Offline integrity controls for the archive utility; no application scenarios."""
from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import conserve_evidence as utility
from conserve_evidence import ROOT, checked_zip, digest, fs_path, restore_bundle, save


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': sha(data)}


def reject(operation, exception):
    try:
        operation()
    except exception:
        return True
    raise AssertionError('Unsafe operation was not rejected')


def main():
    work = ROOT / '.ocr/sessions/b9-consolidation-2026-10-11'
    work.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(dir=fs_path(work), prefix='archive-guards-') as temporary:
        temp = Path(temporary).resolve()
        assert temp.is_relative_to(fs_path(work).resolve())
        payload = b'byte-preservation\r\n\x00\xff'
        name = 'docs/evals/offline-control/data.bin'
        archive_path = temp / 'valid.zip'
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.writestr(name, payload)
        bundle = {'files': [record(name, payload)]}
        destination = temp / 'restored'
        restore_bundle(bundle, archive_path, destination)
        checks['valid_roundtrip_exact_bytes'] = (destination / name).read_bytes() == payload
        restore_bundle(bundle, archive_path, destination, allow_identical=True)
        checks['identical_existing_file_allowed_without_overwrite'] = True
        (destination / name).write_bytes(b'local change')
        checks['different_existing_file_rejected'] = reject(lambda: restore_bundle(bundle, archive_path, destination, True), FileExistsError)
        assert (destination / name).read_bytes() == b'local change'
        checks['different_existing_file_preserved'] = True

        bad = temp / 'escape.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            archive.writestr('../escape.bin', payload)
        checks['escaping_path_rejected'] = reject(lambda: restore_bundle({'files': [record('../escape.bin', payload)]}, bad, temp / 'escape-root'), ValueError)
        assert not (temp / 'escape.bin').exists()

        duplicate = temp / 'duplicate.zip'
        names = ('docs/evals/data.bin', 'DOCS/evals/data.bin')
        with zipfile.ZipFile(duplicate, 'w') as archive:
            for item in names:
                archive.writestr(item, payload)
        checks['case_insensitive_duplicate_members_rejected'] = reject(lambda: restore_bundle({'files': [record(item, payload) for item in names]}, duplicate, temp / 'duplicate-root'), ValueError)
        checks['missing_member_rejected'] = reject(lambda: restore_bundle({'files': [record('absent.bin', payload)]}, archive_path, temp / 'missing-root'), ValueError)
        checks['wrong_member_hash_rejected'] = reject(lambda: restore_bundle({'files': [record(name, b'wrong')]}, archive_path, temp / 'bad-hash-root'), ValueError)

        long_name = 'docs/evals/' + 'nested/' * 40 + 'data.bin'
        long_zip = temp / 'long-path.zip'
        with zipfile.ZipFile(long_zip, 'w') as archive:
            archive.writestr(long_name, payload)
        restore_bundle({'files': [record(long_name, payload)]}, long_zip, temp / 'long-root')
        checks['deep_windows_path_roundtrip'] = (temp / 'long-root' / long_name).read_bytes() == payload

        concat = temp / 'concat'
        concat.mkdir()
        expected = digest(archive_path)
        package = {'parts': [{'path': archive_path.name, 'bytes': archive_path.stat().st_size, 'sha256': expected}], 'zip_sha256': expected}
        with archive_path.open('ab') as stream:
            stream.write(b'altered')
        original_here = utility.HERE
        try:
            utility.HERE = temp
            checks['tampered_package_part_rejected_before_restore'] = reject(lambda: checked_zip(package, concat), ValueError)
        finally:
            utility.HERE = original_here
    assert all(checks.values())
    result = {'status': 'PASS', 'scope': 'Archive utility integrity only; no R1-04 fixture or application execution',
              'checks': checks, 'application_tests_executed': False, 'runtime_changed': False}
    save('preservation-guards.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
