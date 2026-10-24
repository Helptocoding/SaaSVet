"""Preserve this campaign, prove recovery, and stage only explicit paths."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from restore_native import restore

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SHARED = {'.gitattributes', '.gitignore', 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def save(name, data):
    (HERE / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def run(*args, stdin=None):
    result = subprocess.run(['rtk', 'proxy', *map(str, args)], cwd=REPO, input=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(str(args) + ': ' + result.stderr.decode(errors='replace') + result.stdout.decode(errors='replace'))
    return result.stdout

def staged_blobs(wanted):
    mapping = {}
    for entry in filter(None, run('git', 'ls-files', '--stage', '-z').split(b'\0')):
        meta, name = entry.split(b'\t', 1)
        mode, oid, stage = meta.decode().split()
        name = name.decode()
        if name in wanted:
            assert stage == '0'
            mapping[name] = oid
    assert set(mapping) == set(wanted), sorted(set(wanted) - set(mapping))
    unique = list(dict.fromkeys(mapping.values()))
    raw = run('git', 'cat-file', '--batch', stdin=('\n'.join(unique) + '\n').encode())
    blobs, offset = {}, 0
    for expected in unique:
        end = raw.index(b'\n', offset)
        oid, kind, size = raw[offset:end].decode().split()
        assert oid == expected and kind == 'blob'
        offset = end + 1
        size = int(size)
        blobs[oid] = raw[offset:offset + size]
        offset += size
        assert raw[offset:offset + 1] == b'\n'
        offset += 1
    assert offset == len(raw)
    return {name: blobs[oid] for name, oid in mapping.items()}

def main():
    assert not (HERE / 'preservation-manifest.json').exists(), 'Already preserved; no overwrite'
    original = json.loads((HERE / 'checkout-before.json').read_text(encoding='utf-8'))
    head = run('git', 'rev-parse', 'HEAD').decode().strip()
    branch = run('git', 'branch', '--show-current').decode().strip()
    assert head == original['head'] and branch == original['branch']
    prior = json.loads((HERE / 'preservation-of-prior-work.json').read_text(encoding='utf-8'))
    assert not prior['prior_campaign_mismatches'] and prior['unrelated_unchanged']
    native = json.loads((HERE / 'native-closure.json').read_text(encoding='utf-8'))
    assert native['state'] == 'PASS' and native['host_clock_configuration_changed'] is False
    names = set(filter(None, run('git', 'diff', '--cached', '--name-only', '-z').decode().split('\0')))
    baseline = {name: digest(data) for name, data in staged_blobs(names).items()}
    save('index-before-delivery.json', baseline)
    assert HERE.name not in (REPO / '.gitattributes').read_text(encoding='utf-8')
    assert HERE.name not in (REPO / '.gitignore').read_text(encoding='utf-8')
    attributes = (f'\n# B9E Windows native-20261017-r5: preserve original evidence bytes.\n'
        f'docs/evals/{HERE.name}/** -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n'
        f'docs/evals/{HERE.name}/evidence-packages/* -diff\n'
        f'docs/evals/{HERE.name}/receipt-adapter.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\n'
        f'docs/evals/{HERE.name}/native-adaptation-diffs/*.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\n'
        f'docs/evals/{HERE.name}/referenced-evidence/**/*.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\n'
        f'docs/evals/{HERE.name}/correction.diff whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\n')
    ignore = (f'\n# Original logs are included in the independently verified evidence package.\n'
        f'docs/evals/{HERE.name}/**/*.log\n'
        f'docs/evals/{HERE.name}/**/__pycache__/\n')
    for name, text in (('.gitattributes', attributes), ('.gitignore', ignore)):
        with (REPO / name).open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    save('checkout-final.json', {'head': head, 'branch': branch, 'previous_staged_paths': len(baseline),
        'status_before_staging': run('git', 'status', '--porcelain=v1', '-uall').decode(),
        'commits_created': 0, 'pushes_performed': 0})
    paths = sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                   and 'evidence-packages' not in p.parts)
    inventory = {p.relative_to(HERE).as_posix(): {'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size} for p in paths}
    save('artifact-index.json', inventory)
    paths.append(HERE / 'artifact-index.json')
    files = {p.relative_to(HERE).as_posix(): {'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size} for p in paths}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in paths:
            archive.write(p, p.relative_to(HERE).as_posix())
    data = buffer.getvalue()
    package = HERE / 'evidence-packages'
    package.mkdir()
    parts = []
    for n, start in enumerate(range(0, len(data), 40 * 1024**2), 1):
        content = data[start:start + 40 * 1024**2]
        target = package / ('campaign.zip.part' + str(n).zfill(3))
        target.write_bytes(content)
        parts.append({'path': target.relative_to(HERE).as_posix(), 'sha256': digest(content), 'bytes': len(content)})
    save('preservation-manifest.json', {'schema': 'b9i-native-20261017-r5-preservation-v1', 'files': files,
        'parts': parts, 'archive_sha256': digest(data)})
    with tempfile.TemporaryDirectory(prefix='b9i-native-20261017-r5-recovery-') as temporary:
        proof = restore(HERE, Path(temporary) / 'restored')
        cli = json.loads(run(sys.executable, '-B', HERE / 'restore_native.py', '--destination', Path(temporary) / 'cli-restored'))
        assert cli['state'] == 'PASS'
    save('preservation-verification.json', {'internal_restore': proof, 'actual_cli_restore': cli,
        'package_sha256': digest(data), 'raw_logs_preserved_without_git_normalization': True})
    selection = sorted({p.relative_to(REPO).as_posix() for p in HERE.rglob('*') if p.is_file()
                        and p.suffix != '.log' and '__pycache__' not in p.parts} | SHARED |
        {(HERE / name).relative_to(REPO).as_posix() for name in ('git-selection.json', 'delivery-verification.json')})
    save('git-selection.json', {'paths': selection, 'explicit': True, 'raw_logs_excluded_from_git': True})
    save('delivery-verification.json', {'state': 'VERIFYING', 'selected_paths': len(selection)})
    # Pathspec input avoids the Windows command-line length limit.
    run('git', 'add', '--pathspec-from-file=-', '--pathspec-file-nul', stdin=('\0'.join(selection) + '\0').encode())
    run('git', 'diff', '--cached', '--check')
    staged = staged_blobs(set(selection) | set(baseline))
    prior_drift = [name for name, h in baseline.items() if name not in SHARED and digest(staged[name]) != h]
    mismatches, normalized = [], []
    for name in selection:
        local = (REPO / name).read_bytes()
        if local != staged[name]:
            if name in ('.gitattributes', '.gitignore') and local.replace(b'\r\n', b'\n') == staged[name].replace(b'\r\n', b'\n'):
                normalized.append(name)
            else:
                mismatches.append(name)
    drift = [name for name, row in files.items() if digest((HERE / name).read_bytes()) != row['sha256']]
    assert not prior_drift and not mismatches and not drift, (prior_drift, mismatches, drift)
    save('delivery-verification.json', {'state': 'PASS', 'selected_paths': len(selection),
        'evidence_git_blobs_equal_local_bytes': True, 'root_text_normalized_paths': normalized,
        'prior_staged_paths_checked': len(baseline), 'prior_staged_drift_outside_three_delivery_files': prior_drift,
        'evidence_drift': drift, 'cached_diff_check_exit_code': 0, 'recovered_members': proof['recovered_members'],
        'commits_created': 0, 'pushes_performed': 0})
    relative = (HERE / 'delivery-verification.json').relative_to(REPO).as_posix()
    run('git', 'add', '--', relative)
    assert run('git', 'show', ':' + relative) == (HERE / 'delivery-verification.json').read_bytes()
    run('git', 'diff', '--cached', '--check')
    print(json.dumps({'delivery': 'PASS', 'selected_paths': len(selection), 'recovered_members': proof['recovered_members']}))

if __name__ == '__main__':
    main()
