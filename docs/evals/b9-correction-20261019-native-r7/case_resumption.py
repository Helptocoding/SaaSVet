"""Portable, explicitly authorized reuse of the interrupted r6 case prefix."""
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

HERE = Path(__file__).resolve().parent
SOURCE_NAME = 'b9-correction-20261017-native-r6'
SOURCE = HERE.with_name(SOURCE_NAME)
BUNDLE = HERE / 'referenced-case-evidence/r6'
WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
SHA = '68dffd746793700071f577a58528b0f9636930db'
PROOF = 'diagnostics/resumption-20261019/prefix-validation.json'
PROOF_SHA = '51bed99c98bc8683f2764c841076f6ea47288fe339608fd122c4b405ba9e21db'
JOURNAL = 'blocks/full-general.ids.jsonl'
JOURNAL_SHA = '9695650ebf6af50eb5c3f584b9975296f1abc21cceade08cac757e4d45d3c69e'
AUTH = 'case-resumption-authorization.json'
MANIFEST = 'case-resumption-manifest.json'
VALIDATION = 'case-resumption-validation.json'
RETAINED = 'retained-general-observed-ids.json'
REMAINDER = 'full-general-remainder-selected.json'
_CACHE = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def safe_relative(value):
    path = PurePosixPath(value)
    assert value and '\\' not in value and ':' not in value
    assert not path.is_absolute() and '..' not in path.parts and path.as_posix() == value
    return path


def required_files(base):
    proof_raw = (base / PROOF).read_bytes()
    assert sha(proof_raw) == PROOF_SHA
    proof = json.loads(proof_raw)
    assert proof['state'] == 'PASS_INTEGRITY_WITH_HISTORICAL_GAP' and proof['candidate_tree'] == SHA
    assert proof['historical_gap']['state'] == 'DISK_CLOCK_MONITOR_UNAVAILABLE'
    assert proof['historical_gap']['full_group_pass'] is False
    assert not proof['input_changes_during_validation']
    assert all(not row['mismatches'] for row in proof['current_byte_integrity'].values())
    files = {name: row['sha256'] for name, row in proof['input_artifacts'].items()}
    assert files[JOURNAL] == JOURNAL_SHA
    files[PROOF] = PROOF_SHA
    files['diagnostics/resumption-20261019/verify_prefix.py'] = proof['helper_sha256']
    for row in proof['historical_observations'].values():
        files[row['path']] = row['sha256']
    seal_raw = (base / 'evaluation-seal.json').read_bytes()
    assert sha(seal_raw) == files['evaluation-seal.json']
    seal = json.loads(seal_raw)
    for relative in ('recorded_suite.py', 'effective-configuration.json', 'assembly.json'):
        suffix = '/' + SOURCE_NAME + '/' + relative
        matches = [value for name, value in seal['files'].items()
                   if name.replace('\\', '/').endswith(suffix)]
        assert len(matches) == 1, relative
        files[relative] = matches[0]
    for relative in files:
        safe_relative(relative)
    return files, proof


def validate_inputs(base):
    auth = read(HERE / AUTH)
    assert auth['accepted_historical_evidence_limitation'] is True
    assert auth['user_reply'] == 'Sí, continuar con esa limitación'
    assert auth['candidate_tree'] == SHA and auth['prefix_validation_sha256'] == PROOF_SHA
    if 'source_journal_sha256' in auth:
        assert auth['source_journal_sha256'] == JOURNAL_SHA
    selected = read(base / 'full-general-selected.json')
    rows = [json.loads(line) for line in (base / JOURNAL).read_bytes().splitlines()]
    retained, remaining = read(HERE / RETAINED), read(HERE / REMAINDER)
    assert len(selected) == len(set(selected)) == 3213
    assert len(rows) == len(retained) == len(set(retained)) == 2485
    assert sorted(row['id'] for row in rows) == retained
    assert Counter(row['outcome'] for row in rows) == {'PASS': 2483, 'SKIP': 2}
    assert len(remaining) == len(set(remaining)) == 728 and remaining == sorted(remaining)
    assert not set(retained) & set(remaining) and sorted(retained + remaining) == selected
    assert not any(item.endswith('.test_upcoming_window') for item in remaining)
    assembly = read(HERE / 'assembly.json')
    assert assembly['candidate_sha'] == SHA and assembly['port'] == 35490
    assert Path(assembly['workspace']).resolve() == WORK.resolve()
    assert Path(assembly['tree']).resolve() == WORK.resolve() / 'src'
    for name in ('candidate-sources.json', 'dependency-files.json', 'full-general-selected.json',
                 'recorded_suite.py', 'effective-configuration.json'):
        assert (HERE / name).read_bytes() == (base / name).read_bytes(), name
    return retained, remaining


def summary(manifest):
    return {'state': 'PASS', 'retained_ids': 2485, 'retained_PASS': 2483, 'retained_SKIP': 2,
            'new_selected_ids': 728, 'candidate_tree': SHA, 'source_campaign': SOURCE_NAME,
            'historical_disk_and_monotonic_evidence_verified': False,
            'accepted_historical_evidence_limitation': True,
            'manifest': MANIFEST, 'validation': VALIDATION, 'authorization': AUTH,
            'prefix_validation_sha256': PROOF_SHA,
            'prefix_journal': 'referenced-case-evidence/r6/' + JOURNAL,
            'prefix_journal_sha256': JOURNAL_SHA,
            'manifest_sha256': sha((HERE / MANIFEST).read_bytes())}


def validate_case_references():
    """Rehash every bundled reference and every original still present, once per phase."""
    global _CACHE
    manifest = read(HERE / MANIFEST)
    assert manifest['candidate_tree'] == SHA and manifest['source_campaign'] == SOURCE_NAME
    assert manifest['bundle'] == 'referenced-case-evidence/r6'
    expected, proof = required_files(BUNDLE)
    assert set(manifest['files']) == set(expected)
    for relative, wanted in expected.items():
        row = manifest['files'][relative]
        assert row['sha256'] == wanted
        assert row['bundle_relative'] == 'referenced-case-evidence/r6/' + relative
        assert row['original_relative'] == '../' + SOURCE_NAME + '/' + relative
        path = BUNDLE / safe_relative(relative)
        assert path.resolve().is_relative_to(BUNDLE.resolve()) and path.is_file()
        assert sha(path.read_bytes()) == wanted, relative
        if SOURCE.exists():
            original = SOURCE / relative
            assert original.resolve().is_relative_to(SOURCE.resolve()) and original.is_file()
            assert sha(original.read_bytes()) == wanted, 'Original drift: ' + relative
    assert sha((HERE / AUTH).read_bytes()) == manifest['authorization_sha256']
    retained, remaining = validate_inputs(BUNDLE)
    assert manifest['retained_test_ids'] == retained and manifest['new_selected_test_ids'] == remaining
    assert manifest['retained_selector_sha256'] == sha((HERE / RETAINED).read_bytes())
    assert manifest['remaining_selector_sha256'] == sha((HERE / REMAINDER).read_bytes())
    _CACHE = {'manifest': manifest, 'proof': proof, 'summary': summary(manifest)}
    return dict(_CACHE['summary'])


def active():
    if _CACHE is None:
        validate_case_references()
    return _CACHE


def case_summary():
    return dict(active()['summary'])


def retained_case_ids():
    return list(active()['manifest']['retained_test_ids'])


def remaining_case_ids():
    return list(active()['manifest']['new_selected_test_ids'])


def provenance(label='full-general'):
    assert label == 'full-general'
    return dict(case_summary(), origin='COMPOSITE_CASE_EVIDENCE', command_origin='CURRENT_ASSEMBLER',
                campaign=HERE.name, tested_candidate_tree=SHA, accepted_candidate_tree=SHA,
                original_invocation_exit='UNKNOWN', full_general_scope='logical case aggregate')


def prepare():
    assert not (HERE / 'evaluation-seal.json').exists() and not (HERE / 'invocation-formal.json').exists()
    assert not (HERE / MANIFEST).exists() and not (HERE / VALIDATION).exists() and not BUNDLE.exists()
    files, proof = required_files(SOURCE)
    retained, remaining = validate_inputs(SOURCE)
    records = {}
    for relative, wanted in files.items():
        raw = (SOURCE / relative).read_bytes()
        assert sha(raw) == wanted, relative
        target = BUNDLE / safe_relative(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        assert target.read_bytes() == raw
        records[relative] = {'sha256': wanted, 'bytes': len(raw),
            'bundle_relative': 'referenced-case-evidence/r6/' + relative,
            'original_relative': '../' + SOURCE_NAME + '/' + relative}
    write(HERE / MANIFEST, {'schema': 'b9-case-resumption/1', 'candidate_tree': SHA,
        'source_campaign': SOURCE_NAME, 'bundle': 'referenced-case-evidence/r6', 'files': records,
        'authorization_sha256': sha((HERE / AUTH).read_bytes()),
        'retained_test_ids': retained, 'new_selected_test_ids': remaining,
        'retained_selector_sha256': sha((HERE / RETAINED).read_bytes()),
        'remaining_selector_sha256': sha((HERE / REMAINDER).read_bytes()),
        'historical_disk_and_monotonic_evidence_verified': False,
        'accepted_historical_evidence_limitation': True})
    write(HERE / VALIDATION, dict(validate_case_references(), prefix_validation_state=proof['state'],
        full_group_pass=False, original_invocation_exit='UNKNOWN'))
    print('CASE_RESUMPTION_PREPARED', flush=True)


def assemble():
    validate_case_references()
    blocks = HERE / 'blocks'
    receipt_path, journal_path = blocks / 'full-general.results.json', blocks / JOURNAL.split('/')[-1]
    assert not receipt_path.exists() and not journal_path.exists()
    label = 'full-general-remainder'
    command_path = blocks / (label + '.command.json')
    result_path = blocks / (label + '.results.json')
    tail_path = blocks / (label + '.ids.jsonl')
    command, result = read(command_path), read(result_path)
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 0
    assert not command.get('invalidating_incident') and command['candidate_sha'] == SHA
    assert result['candidate_sha'] == SHA and result['exit_code'] == 0
    assert result['tests'] == 728 and sorted(result['test_ids']) == remaining_case_ids()
    assert not result['failures'] and not result['errors'] and not result['failed_ids']
    prefix_raw, tail_raw = (BUNDLE / JOURNAL).read_bytes(), tail_path.read_bytes()
    prefix = [json.loads(line) for line in prefix_raw.splitlines()]
    tail = [json.loads(line) for line in tail_raw.splitlines()]
    assert len(tail) == 728 and sorted(row['id'] for row in tail) == remaining_case_ids()
    assert all(row['outcome'] in ('PASS', 'SKIP', 'XFAIL') for row in tail)
    tail_skips = [{'id': row['id'], 'reason': row['reason']} for row in tail if row['outcome'] == 'SKIP']
    assert sorted(tail_skips, key=lambda row: row['id']) == sorted(result['skips'], key=lambda row: row['id'])
    assert sum(row['outcome'] == 'XFAIL' for row in tail) == result.get('xfail', 0)
    assert not result.get('xpass', 0)
    combined = prefix + tail
    assert len(combined) == len({row['id'] for row in combined}) == 3213
    assert sorted(row['id'] for row in combined) == read(HERE / 'full-general-selected.json')
    logical = dict(result, test_ids=sorted(row['id'] for row in combined), tests=3213,
        skips=[{'id': row['id'], 'reason': row['reason']} for row in combined if row['outcome'] == 'SKIP'],
        exit_code=0, exit_scope='aggregate', exit_code_meaning='aggregate validator success only',
        original_invocation_exit='UNKNOWN', logical_aggregate=True,
        seconds_scope='new remainder only; original invocation duration unavailable',
        orchestration='authorized case prefix plus independently recorded remainder',
        provenance=provenance(), accepted_historical_evidence_limitation=True,
        historical_disk_and_monotonic_evidence_verified=False,
        source_executions=[{'origin': 'REFERENCED_CASE_PREFIX', 'campaign': SOURCE_NAME,
            'tests': 2485, 'PASS': 2483, 'SKIP': 2, 'journal': 'referenced-case-evidence/r6/' + JOURNAL,
            'journal_sha256': JOURNAL_SHA, 'original_invocation_exit': 'UNKNOWN'},
            {'origin': 'CURRENT_EXECUTION', 'campaign': HERE.name, 'tests': 728,
             'command': command_path.relative_to(HERE).as_posix(), 'command_sha256': sha(command_path.read_bytes()),
             'result': result_path.relative_to(HERE).as_posix(), 'result_sha256': sha(result_path.read_bytes()),
             'journal': tail_path.relative_to(HERE).as_posix(), 'journal_sha256': sha(tail_raw)}])
    validate_case_references()
    prefix_provenance = {'origin': 'REFERENCED_CASE_PREFIX', 'campaign': SOURCE_NAME,
        'source_artifact': 'referenced-case-evidence/r6/' + JOURNAL, 'source_sha256': JOURNAL_SHA,
        'accepted_historical_evidence_limitation': True,
        'historical_disk_and_monotonic_evidence_verified': False}
    tail_provenance = {'origin': 'CURRENT_EXECUTION', 'campaign': HERE.name,
        'source_artifact': tail_path.relative_to(HERE).as_posix(), 'source_sha256': sha(tail_raw)}
    with journal_path.open('x', encoding='utf-8', newline='\n') as stream:
        for source_rows, source_provenance in ((prefix, prefix_provenance), (tail, tail_provenance)):
            for row in source_rows:
                stream.write(json.dumps(dict(row, case_provenance=source_provenance),
                                        ensure_ascii=False) + '\n')
    write(receipt_path, logical)
    print('CASE_RESUMPTION_ASSEMBLE_PASS', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'assemble': assemble}[sys.argv[1]]()
