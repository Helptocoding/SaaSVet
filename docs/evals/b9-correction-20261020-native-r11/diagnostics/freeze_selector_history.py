"""Snapshot closed zero-case evidence and already-completed r9 receipts only."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parents[1]
PRIOR = HERE.with_name('b9-correction-20261020-native-r10')
REPO = HERE.parents[2]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(name, value):
    target = HERE / name
    assert not target.exists(), target
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    retirement = json.loads((HERE / 'previous-cluster-retirement.json').read_text(encoding='utf-8'))
    assert retirement['state'] == 'PASS' and retirement['previous_campaign'] == PRIOR.name
    assert retirement.get('old_final_logs_closed_before_prior_evidence_snapshot') is True or retirement.get('old_final_logs_stable_before_prior_evidence_snapshot') is True
    assert sha(Path(retirement['previous_log']['path'])) == retirement['previous_log']['sha256']
    source_bundle = PRIOR / 'referenced-completed-evidence/r9'
    target_bundle = HERE / 'referenced-completed-evidence/r9'
    assert not target_bundle.exists()
    shutil.copytree(source_bundle, target_bundle)
    existing = json.loads((HERE / 'completed-reference-manifest.json').read_text(encoding='utf-8'))
    assert all(sha(target_bundle / p) == row['sha256'] for p, row in existing['files'].items())
    history = HERE / 'referenced-selector-evidence/r10'
    assert not history.exists()
    inventory = {}
    for source in sorted(PRIOR.rglob('*')):
        if not source.is_file() or '__pycache__' in source.parts:
            continue
        relative = source.relative_to(PRIOR)
        if relative.parts[0] == 'referenced-completed-evidence':
            continue
        assert not source.is_symlink() and not source.is_junction()
        destination = history / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        wanted = sha(source)
        assert sha(destination) == wanted
        inventory[relative.as_posix()] = {'sha256': wanted, 'bytes': source.stat().st_size}
    save('selector-history-manifest.json', {'schema': 'b9-zero-case-selector-history/1',
        'source_campaign': PRIOR.name, 'source_candidate_tree': existing['candidate_tree'],
        'candidate_tree': existing['candidate_tree'], 'bundle_relative': 'referenced-selector-evidence/r10',
        'files': inventory, 'source_application_tests_executed': 0,
        'excluded_only': ['referenced-completed-evidence', '__pycache__']})
    prior_files = {}
    for folder in HERE.parent.iterdir():
        if folder.is_dir() and folder != HERE and (folder.name.startswith('b9-correction-') or
                folder.name.startswith('b9-integral-acceptance-1947726')):
            prior_files.update({p.relative_to(REPO).as_posix(): sha(p) for p in folder.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior_files)
    print('R11_HISTORY_FROZEN', len(inventory), 'r9_files', len(existing['files']),
        'all_prior_files', len(prior_files), flush=True)


if __name__ == '__main__':
    main()
