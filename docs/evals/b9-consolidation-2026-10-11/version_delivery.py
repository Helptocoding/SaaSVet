"""Prepare or verify the explicit B9 Git selection. Never commits or publishes."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from conserve_evidence import HERE, ROOT, digest, inspect_stream, save

REVIEW = ROOT / 'docs/evals/inbox-whatsapp-closure-review-2026-10-11'
GUIDANCE = [
    'docs/mapa-interno-b9-2026-09-26.md', 'docs/modules/agent.md',
    'docs/plan-implementacion-auditoria-agente-whatsapp-2026-09md',
    'docs/runbooks/agent-whatsapp.md', 'docs/whatsapp-agent-audit-dossier.md',
]
EXCLUDED = ['DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json']
WORK = ROOT / '.ocr/sessions/b9-consolidation-2026-10-11'
EXPECTED_HEAD = '825db75df68bf076929fa787e77beefe96803350'


def git(*args):
    return subprocess.run(['rtk', 'proxy', 'git', *args], cwd=ROOT, capture_output=True, check=True).stdout


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def staged_names():
    return sorted(x.decode('utf-8') for x in git('diff', '--cached', '--name-only', '-z').split(b'\0') if x)


def selection():
    inventory = read(REVIEW / 'git-inventory.json')
    manifest = read(HERE / 'preservation-manifest.json')
    historical = read(HERE / 'historical-provenance.json')
    archived = {r['path']: (b['source_directory'], r) for b in manifest['bundles'] for r in b['files']}
    frozen_sources = read(ROOT / 'docs/evals/d29-execution-2026-10-10/frozen-sources.json')
    protected_sources = read(ROOT / 'docs/evals/d29-execution-2026-10-10/final-integrity.json')['protected_sources']
    for name, expected in frozen_sources.items():
        if digest(ROOT / name) != expected:
            raise ValueError('D29 frozen source changed: ' + name)
    disposition, selected = [], set(GUIDANCE + ['.gitattributes', '.gitignore'])
    for row in inventory['untracked_files']:
        name = row['path']
        if name in archived:
            group, frozen = archived[name]
            direct = frozen['readable_in_git']
            disposition.append({'path': name, 'bytes': frozen['bytes'], 'sha256': frozen['sha256'],
                                'disposition': 'GIT_DIRECT_AND_PACKAGE' if direct else 'PACKAGE_MEMBER',
                                'bundle': group})
            if direct:
                selected.add(name)
        else:
            source = ROOT / name
            if source.stat().st_size != row['bytes']:
                raise ValueError('Initial direct source size changed: ' + name)
            expected = protected_sources.get(name)
            if expected is not None and digest(source) != expected:
                raise ValueError('Protected direct source changed: ' + name)
            disposition.append({'path': name, 'bytes': row['bytes'], 'sha256': digest(source), 'disposition': 'GIT_DIRECT'})
            selected.add(name)
    for row in historical['files']:
        if digest(ROOT / row['path']) != row['sha256']:
            raise ValueError('Historical source changed')
        selected.add(row['path'])
    for row in inventory['critical_files']:
        if row['exists'] and row['path'] not in GUIDANCE and digest(ROOT / row['path']) != row['sha256']:
            raise ValueError('Critical witness changed: ' + row['path'])
    for folder in (HERE, REVIEW):
        for path in folder.rglob('*'):
            if path.is_file() and 'preservation-checkpoint' not in path.name and not path.name.endswith('.tmp') and '__pycache__' not in path.parts:
                selected.add(path.relative_to(ROOT).as_posix())
    selected.update((HERE / name).relative_to(ROOT).as_posix() for name in ('versioning-disposition.json', 'versioning-verification.json'))
    assert len(disposition) == inventory['untracked_file_count'] == 5869
    assert len(archived) == manifest['files']
    assert not set(EXCLUDED) & selected
    return inventory, manifest, historical, disposition, sorted(selected)


def prepare():
    if git('rev-parse', 'HEAD').decode().strip() != EXPECTED_HEAD:
        raise ValueError('HEAD changed; review before preparing')
    if git('branch', '--show-current').decode().strip() != 'codex/e4-capacity-scheduling':
        raise ValueError('Delivery branch changed')
    inventory, manifest, historical, rows, paths = selection()
    prior = HERE / 'versioning-disposition.json'
    excluded_snapshot = read(prior)['excluded_worktree_state'] if prior.exists() else [
        {'path': p, 'exists': (ROOT / p).is_file(), 'sha256': digest(ROOT / p) if (ROOT / p).is_file() else None} for p in EXCLUDED]
    result = {
        'schema': 'b9-versioning-disposition-v1', 'date': '2026-10-11',
        'branch': git('branch', '--show-current').decode().strip(), 'head_before_delivery': EXPECTED_HEAD,
        'commit_status': 'PENDING_EXPLICIT_AUTHORIZATION', 'push_performed': False,
        'source_inventory_files': len(rows), 'source_inventory_bytes': inventory['untracked_bytes'],
        'unclassified_files': [], 'dispositions': rows,
        'packaged_files': manifest['files'], 'package_bytes': manifest['package_bytes'],
        'direct_original_files': sum(r['disposition'] != 'PACKAGE_MEMBER' for r in rows),
        'historical_recovered_direct_files': historical['count'], 'historical_source_commit': historical['source_commit'],
        'historical_wa02_commits': {'state': 'PATCH_EQUIVALENT_ALREADY_INTEGRATED', 'proof': '../inbox-whatsapp-closure-review-2026-10-11/git-branch-deltas.json'},
        'guidance_documents_updated': GUIDANCE, 'excluded_worktree_state': excluded_snapshot,
        'selection_count': len(paths), 'selected_paths': paths,
        'runtime_modified': False, 'physical_tests_executed': False, 'original_evidence_removed': False,
        'd29_frozen_sources_verified': len(read(ROOT / 'docs/evals/d29-execution-2026-10-10/frozen-sources.json')),
    }
    save('versioning-disposition.json', result)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'stage-paths.txt').write_bytes(b'\0'.join(p.encode() for p in paths) + b'\0')
    scan = read(HERE / 'privacy-scan.json')
    additional = sorted(p for p in paths if p not in {r['path'] for b in manifest['bundles'] for r in b['files']} and '/evidence-packages/' not in p and (ROOT / p).is_file())
    findings = []
    for name in additional:
        with (ROOT / name).open('rb') as stream:
            _, _, labels = inspect_stream(stream)
        if labels:
            findings.append({'path': name, 'rules': labels})
    scan['additional_direct_files_checked'] = len(additional)
    scan['additional_direct_findings'] = findings
    save('privacy-scan.json', scan)
    print(json.dumps({'selected': len(paths), 'direct_original_files': result['direct_original_files'],
                      'packaged_files': manifest['files'], 'additional_scan_findings': findings}, indent=2))
    if scan['findings'] or findings:
        raise ValueError('Credential-pattern findings need review before staging')


def stage():
    prepare()
    allowed = read(HERE / 'versioning-disposition.json')['selected_paths']
    if set(staged_names()) - set(allowed):
        raise ValueError('Existing index has unrelated paths; refusing to alter selection')
    if not (HERE / 'versioning-verification.json').exists():
        save('versioning-verification.json', {'status': 'PREPARING_NOT_ACCEPTANCE'})
    git('add', '-f', '--pathspec-from-file=' + str(WORK / 'stage-paths.txt'), '--pathspec-file-nul')
    verify()
    git('add', '--', (HERE / 'versioning-verification.json').relative_to(ROOT).as_posix())
    print('Explicit selection staged; no commit or push', flush=True)


def verify():
    record = read(HERE / 'versioning-disposition.json')
    paths = record['selected_paths']
    if staged_names() != paths:
        raise ValueError('Staged path inventory differs from explicit selection')
    entries = {}
    for entry in git('ls-files', '--stage', '-z').split(b'\0'):
        if entry:
            metadata, name = entry.split(b'\t', 1)
            mode, oid, level = metadata.split()
            if level != b'0':
                raise ValueError('Unmerged index')
            entries[name.decode('utf-8')] = (mode.decode(), oid.decode())
    mismatches, normalized_text = [], []
    for name in paths:
        source = ROOT / name
        if name in GUIDANCE + ['.gitignore', '.gitattributes']:
            expected = git('hash-object', '--path=' + name, '--', name).decode().strip()
            normalized_text.append(name)
            if entries[name][1] != expected:
                mismatches.append(name)
            continue
        value = hashlib.sha1()
        value.update(('blob ' + str(source.stat().st_size) + '\0').encode())
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(128 * 1024), b''):
                value.update(block)
        # The verification receipt necessarily changes when this result is saved.
        if name.endswith('/versioning-verification.json'):
            continue
        if entries[name][1] != value.hexdigest():
            mismatches.append(name)
    for row in record['excluded_worktree_state']:
        source = ROOT / row['path']
        if source.is_file() != row['exists'] or row['exists'] and digest(source) != row['sha256']:
            raise ValueError('Unrelated worktree change was altered')
    if mismatches:
        raise ValueError('Index bytes differ from local source: ' + repr(mismatches))
    current_head = git('rev-parse', 'HEAD').decode().strip()
    if current_head != EXPECTED_HEAD:
        raise ValueError('Unexpected commit or branch movement')
    if git('branch', '--show-current').decode().strip() != record['branch']:
        raise ValueError('Unexpected delivery branch change')
    result = {
        'status': 'PASS', 'date': '2026-10-11', 'branch': record['branch'], 'head': current_head,
        'selected_staged_paths': len(paths), 'staged_paths_match_explicit_selection': True,
        'staged_blob_bytes_checked': len(paths) - 1 - len(normalized_text), 'staged_blob_byte_mismatches': mismatches,
        'editable_text_checked_after_git_normalization': normalized_text,
        'self_receipt_excluded_from_own_hash_check': True,
        'all_5869_initial_files_classified': True, 'unrelated_worktree_changes_preserved': True,
        'runtime_changed': False, 'application_tests_executed': False, 'commit_created': False, 'push_performed': False,
    }
    save('versioning-verification.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'stage', 'verify'))
    command = parser.parse_args().command
    {'prepare': prepare, 'stage': stage, 'verify': verify}[command]()
