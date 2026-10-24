"""Freeze three source journals and the single corrected selection; never run tests."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.with_name('b9-correction-20261020-native-r8')
REPO = HERE.parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    p = HERE / name
    assert not p.exists(), p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def main():
    assert read(HERE / 'previous-cluster-retirement.json')['state'] == 'PASS'
    candidate = read(HERE / 'candidate.json')
    original = read(PRIOR / 'case-resumption-inputs.json')
    sources = {key: value for key, value in original['sources'].items()}
    proof_name = 'diagnostics/completed-prefix-validation.json'
    proof = read(PRIOR / proof_name)
    files = dict(proof['files'])
    required = [proof_name, 'candidate.json', 'candidate-sources.json', 'dependency-files.json',
        'recorded_suite.py', 'effective-configuration.json', 'assembly.json',
        'awake-request/control.json', 'resource-observer-control.json',
        'full-general-remainder-selected.json', 'full-general-selected.json',
        'final-classification.json', 'blocks/full-general-remainder.gate.json', 'snapshot-resumption-authorization.json',
        'snapshot-equivalence.json', 'snapshot-correction.diff']
    files.update({name: sha(PRIOR / name) for name in required})
    sources['r8'] = {'campaign': PRIOR.name, 'journal': 'blocks/full-general-remainder.ids.jsonl',
        'selected': 'full-general-remainder-selected.json', 'proof': proof_name, 'files': files}
    journals = {}
    for key, source in sources.items():
        folder = HERE.with_name(source['campaign'])
        assert all(sha(folder / name) == h for name, h in source['files'].items()), key
        journals[key] = [json.loads(line) for line in (folder / source['journal']).read_text(encoding='utf-8').splitlines() if line]
    a = sorted(row['id'] for row in journals['r6'])
    b = sorted(row['id'] for row in journals['r7'] if row['outcome'] == 'PASS')
    c = sorted(row['id'] for row in journals['r8'] if row['outcome'] in ('PASS', 'SKIP'))
    selected = sorted(row['id'] for row in journals['r8'] if row['outcome'] == 'FAIL')
    assert len(a) == 2485 and len(b) == 405 and len(c) == 322 and len(selected) == 1
    assert len(set(a + b + c + selected)) == 3213
    assert sorted(a + b + c + selected) == read(HERE / 'full-general-selected.json')
    for name, values in [('retained-r6-observed-ids.json', a), ('retained-r7-pass-ids.json', b),
                         ('retained-r8-valid-ids.json', c), ('full-general-remainder-selected.json', selected)]:
        save(name, values)
    save('case-resumption-inputs.json', {'schema': 'b9-case-resumption-inputs/3',
        'source_candidate_tree': '5e11236daabf4ef70ea9d0f08fee52aed5c30ff2',
        'candidate_tree': candidate['candidate_tree'], 'sources': sources,
        'snapshot_equivalence': {'path': 'snapshot-equivalence.json', 'sha256': sha(HERE / 'snapshot-equivalence.json')},
        'snapshot_patch': {'path': 'snapshot-correction.diff', 'sha256': sha(HERE / 'snapshot-correction.diff')},
        'baseline_equivalence': {'path': 'baseline-equivalence.json', 'sha256': sha(HERE / 'baseline-equivalence.json')},
        'baseline_patch': {'path': 'baseline-correction.diff', 'sha256': sha(HERE / 'baseline-correction.diff')}})
    failed = []
    for key in ('r7', 'r8'):
        for row in journals[key]:
            if row['outcome'] == 'FAIL':
                failed.append(dict(row, source_campaign=sources[key]['campaign']))
    assert len(failed) == 3
    save('preserved-failed-cases.json', {'state': 'ALL_ORIGINAL_FAILS_PRESERVED',
        'failed_cases': failed, 'historical_failed_attempts': 3,
        'r7_snapshots_now_PASS_in_retained_r8': True,
        'r8_baseline_failure_selected_only': selected,
        'failed_cases_presented_as_reused_PASS': False,
        'source_journal_sha256': {key: sources[key]['files'][sources[key]['journal']] for key in ('r7', 'r8')}})
    work = Path(read(HERE / 'assembly.json')['workspace'])
    for name in candidate['changed_paths']:
        source = work / 'src' / name
        assert source.read_bytes().replace(b'\r\n', b'\n') == (REPO / name).read_bytes().replace(b'\r\n', b'\n')
        target = work / 'security-patch' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    prior = {}
    for folder in HERE.parent.iterdir():
        if folder.is_dir() and folder != HERE and (folder.name.startswith('b9-correction-') or folder.name.startswith('b9-integral-acceptance-1947726')):
            prior.update({p.relative_to(REPO).as_posix(): sha(p) for p in folder.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts})
    save('prior-evidence-before.json', prior)
    print('R9_SELECTION_FROZEN_3212_RETAINED_PLUS_1_NO_TESTS', len(prior), flush=True)


if __name__ == '__main__':
    main()
