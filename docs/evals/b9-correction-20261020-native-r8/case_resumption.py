"""Authorized case reuse from interrupted r6/r7; no historical exit is inferred."""
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

HERE = Path(__file__).resolve().parent
OLD = '68dffd746793700071f577a58528b0f9636930db'
PATCH = '6d13efc117f33e26f1701dc568b881a1758adfdfdd3f53bc874b0a9989512a50'
WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
INPUTS = 'case-resumption-inputs.json'
AUTH = 'snapshot-resumption-authorization.json'
MANIFEST = 'case-resumption-manifest.json'
VALIDATION = 'case-resumption-validation.json'
SELECTORS = ('retained-r6-observed-ids.json', 'retained-r7-pass-ids.json',
             'full-general-remainder-selected.json')
FAILED = sorted(['apps.agent.tests.test_contracts.CommitmentContractTests.test_fields_match_snapshot',
                 'apps.agent.tests.test_contracts.ToolOutcomeContractTests.test_fields_match_snapshot'])
CAMPAIGNS = {'r6': 'b9-correction-20261017-native-r6', 'r7': 'b9-correction-20261019-native-r7'}
PROOFS = {'r6': '51bed99c98bc8683f2764c841076f6ea47288fe339608fd122c4b405ba9e21db',
          'r7': 'c570dac8c00264eeb919f9c80a61289b7ed021ee2e629552ad8f0e4df0d5179d'}
_CACHE = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def relative(value):
    path = PurePosixPath(value)
    assert value and '\\' not in value and ':' not in value
    assert not path.is_absolute() and '..' not in path.parts and path.as_posix() == value
    return path


def local_descriptor(item):
    path = HERE / relative(item['path'])
    assert path.resolve().is_relative_to(HERE.resolve()) and path.is_file()
    assert sha(path.read_bytes()) == item['sha256'], item['path']
    return path


def metadata():
    data, candidate, auth = read(HERE / INPUTS), read(HERE / 'candidate.json'), read(HERE / AUTH)
    current = candidate['candidate_tree']
    assert data['schema'] == 'b9-case-resumption-inputs/2'
    assert data['source_candidate_tree'] == OLD and data['candidate_tree'] == current != OLD
    assert auth['state'] == 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL'
    assert auth['user_answer'] == 'Sí, corregir esos snapshots y continuar sin repetir PASS'
    assert auth['previous_candidate_tree'] == OLD and auth['candidate_tree'] == current
    assert auth['no_PASS_reruns'] is True
    equivalence = read(local_descriptor(data['snapshot_equivalence']))
    patch = local_descriptor(data['snapshot_patch'])
    assert equivalence['state'] == 'PASS'
    assert equivalence['previous_candidate_tree'] == OLD and equivalence['candidate_tree'] == current
    assert equivalence['allowed_path'] == 'backend/apps/agent/tests/test_contracts.py'
    assert equivalence['patch_sha256'] == auth['patch_sha256'] == sha(patch.read_bytes()) == PATCH
    for key in ('only_two_expected_literal_lists_change_ast', 'assertions_other_AST_unchanged',
                'all_other_3331_blobs_identical', 'test_ids_imports_hooks_unchanged', 'old_FAILs_preserved'):
        assert equivalence[key] is True, key
    assert equivalence['product_runtime_locks_changed'] is False
    assert set(data['sources']) == set(CAMPAIGNS)
    assembly = read(HERE / 'assembly.json')
    assert assembly['candidate_sha'] == current and assembly['port'] == 35490
    assert Path(assembly['workspace']).resolve() == WORK.resolve()
    assert Path(assembly['tree']).resolve() == WORK.resolve() / 'src'
    return data, current


def source(key, spec, bundled):
    assert spec['campaign'] == CAMPAIGNS[key]
    base = HERE / 'referenced-case-evidence' / key if bundled else HERE.with_name(spec['campaign'])
    assert base.is_dir() and not base.is_symlink() and not base.is_junction()
    assert spec['journal'] == ('blocks/full-general.ids.jsonl' if key == 'r6'
                               else 'blocks/full-general-remainder.ids.jsonl')
    assert spec['selected'] == ('full-general-selected.json' if key == 'r6'
                                else 'full-general-remainder-selected.json')
    command = spec['journal'].replace('.ids.jsonl', '.command.json')
    required = {spec['journal'], spec['selected'], spec['proof'], command, 'candidate.json',
                'candidate-sources.json', 'dependency-files.json', 'evaluation-seal.json',
                'recorded_suite.py', 'effective-configuration.json', 'assembly.json', 'invocation-formal.json'}
    assert required <= set(spec['files'])
    for name, wanted in spec['files'].items():
        path = base / relative(name)
        assert path.resolve().is_relative_to(base.resolve()) and path.is_file()
        assert not path.is_symlink() and not path.is_junction()
        assert sha(path.read_bytes()) == wanted, key + ':' + name
        original_base = HERE.with_name(spec['campaign'])
        original = original_base / relative(name)
        if bundled and original_base.exists():
            assert original.is_file() and sha(original.read_bytes()) == wanted, 'Original drift: ' + str(original)
    proof = read(base / spec['proof'])
    assert spec['files'][spec['proof']] == PROOFS[key]
    assert proof['candidate_tree'] == OLD
    if key == 'r6':
        assert proof['state'] == 'PASS_INTEGRITY_WITH_HISTORICAL_GAP'
        assert not proof['input_changes_during_validation']
        integrity = proof['current_byte_integrity']
        assert set(integrity) == {'sources', 'dependencies', 'seal'}
    else:
        assert proof['state'] == 'PASS_INTEGRITY_WITH_RECORDED_FAILURES'
        unchanged = proof['original_inputs_unchanged_during_audit']
        assert unchanged and all(value is True for value in unchanged.values())
        assert not proof['audit_problems'] and not proof['guard_coverage_problems']
        assert proof['current_byte_integrity']['candidate_tree'] == OLD
        integrity = {name: proof['current_byte_integrity'][name]
                     for name in ('sources', 'dependencies', 'evaluation_seal')}
        observer = proof['durable_host_observer']
        assert observer['covers_start'] and observer['covers_end']
        assert not observer['uncovered_cases'] and not observer['gaps_over_ten_seconds']
        assert observer['minimum_ram_bytes'] >= 2 * 1024**3
        assert observer['minimum_disk_bytes'] >= 1024**3
        assert observer['maximum_absolute_wall_monotonic_skew_seconds'] <= 1
        assert proof['prefix']['failed_cases_are_not_dropped_or_changed_to_pass'] is True
    assert all(not row['mismatches'] and not row.get('missing', []) for row in integrity.values())
    assert read(base / 'candidate.json')['candidate_tree'] == OLD
    invocation, cmd = read(base / 'invocation-formal.json'), read(base / command)
    assert invocation['state'] == 'RUNNING' and cmd['state'] == 'RUNNING'
    assert cmd['candidate_sha'] == OLD
    for name in ('dependency-files.json', 'effective-configuration.json'):
        assert (base / name).read_bytes() == (HERE / name).read_bytes(), name
    old_recorder = (base / 'recorded_suite.py').read_bytes()
    current_tree = read(HERE / 'candidate.json')['candidate_tree']
    assert (HERE / 'recorded_suite.py').read_bytes() == old_recorder.replace(OLD.encode(), current_tree.encode())
    rows = [json.loads(line) for line in (base / spec['journal']).read_bytes().splitlines()]
    ids = [row['id'] for row in rows]
    assert len(ids) == len(set(ids)) and set(ids) <= set(read(base / spec['selected']))
    return base, rows


def partition(data, bundled):
    sources = {key: source(key, spec, bundled) for key, spec in data['sources'].items()}
    a, j7 = sources['r6'][1], sources['r7'][1]
    assert Counter(row['outcome'] for row in a) == {'PASS': 2483, 'SKIP': 2}
    assert Counter(row['outcome'] for row in j7) == {'PASS': 405, 'FAIL': 2}
    assert sorted(row['id'] for row in j7 if row['outcome'] == 'FAIL') == FAILED
    a_ids = sorted(row['id'] for row in a)
    b_ids = sorted(row['id'] for row in j7 if row['outcome'] == 'PASS')
    prior_tail = read(sources['r7'][0] / data['sources']['r7']['selected'])
    missing = set(prior_tail) - {row['id'] for row in j7}
    c_ids = sorted(missing | set(FAILED))
    assert len(prior_tail) == len(set(prior_tail)) == 728 and len(missing) == 321
    assert [len(a_ids), len(b_ids), len(c_ids)] == [2485, 405, 323]
    for name, expected in zip(SELECTORS, (a_ids, b_ids, c_ids)):
        assert read(HERE / name) == expected, name
    assert not set(a_ids) & set(b_ids) and not set(a_ids + b_ids) & set(c_ids)
    assert sorted(a_ids + b_ids + c_ids) == read(HERE / 'full-general-selected.json')
    assert len(set(a_ids + b_ids + c_ids)) == 3213
    assert not any(item.endswith('.test_upcoming_window') for item in c_ids)
    return sources, a_ids, b_ids, c_ids


def summary(current):
    return {'state': 'PASS', 'candidate_tree': current, 'source_candidate_tree': OLD,
            'retained_ids': 2890, 'retained_PASS': 2888, 'retained_SKIP': 2, 'new_selected_ids': 323,
            'previous_accepted_cases': 2890, 'prior_pass': 2888, 'prior_skips': 2, 'current_cases': 323,
            'historical_failed_attempts': 2, 'result_general': 3213, 'corrected_failed_case_ids': FAILED,
            'retained_sources': {'r6': {'tests': 2485, 'PASS': 2483, 'SKIP': 2},
                'r7': {'tests': 405, 'PASS': 405, 'SKIP': 0, 'source_journal_observations': 407,
                       'excluded_historical_FAIL': 2}},
            'original_invocation_exits': {'r6': 'UNKNOWN', 'r7': 'UNKNOWN'},
            'historical_disk_and_monotonic_evidence_verified': False,
            'accepted_historical_evidence_limitation': True,
            'manifest': MANIFEST, 'validation': VALIDATION, 'authorization': AUTH,
            'manifest_sha256': sha((HERE / MANIFEST).read_bytes())}


def validate_case_references():
    global _CACHE
    data, current = metadata()
    manifest = read(HERE / MANIFEST)
    assert manifest['inputs_sha256'] == sha((HERE / INPUTS).read_bytes())
    assert manifest['authorization_sha256'] == sha((HERE / AUTH).read_bytes())
    assert manifest['candidate_tree'] == current and manifest['sources'] == data['sources']
    assert manifest['selector_sha256'] == {name: sha((HERE / name).read_bytes()) for name in SELECTORS}
    sources, a, b, c = partition(data, True)
    _CACHE = {'sources': sources, 'retained': a + b, 'remaining': c, 'summary': summary(current)}
    return dict(_CACHE['summary'])


def active():
    if _CACHE is None:
        validate_case_references()
    return _CACHE


def case_summary():
    return dict(active()['summary'])


def retained_case_ids():
    return list(active()['retained'])


def remaining_case_ids():
    return list(active()['remaining'])


def provenance(label='full-general'):
    assert label == 'full-general'
    return dict(case_summary(), origin='COMPOSITE_CASE_EVIDENCE', command_origin='CURRENT_ASSEMBLER',
                campaign=HERE.name, tested_candidate_tree=active()['summary']['candidate_tree'],
                accepted_candidate_tree=active()['summary']['candidate_tree'],
                original_invocation_exit='UNKNOWN', full_general_scope='logical case aggregate')


def prepare():
    assert not (HERE / 'evaluation-seal.json').exists() and not (HERE / 'invocation-formal.json').exists()
    assert not (HERE / MANIFEST).exists() and not (HERE / VALIDATION).exists()
    assert not (HERE / 'referenced-case-evidence').exists()
    data, current = metadata()
    sources, _, _, _ = partition(data, False)
    for key, (base, _) in sources.items():
        for name, wanted in data['sources'][key]['files'].items():
            raw = (base / relative(name)).read_bytes()
            assert sha(raw) == wanted
            target = HERE / 'referenced-case-evidence' / key / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
    write(HERE / MANIFEST, {'schema': 'b9-case-resumption/2', 'candidate_tree': current,
        'source_candidate_tree': OLD, 'sources': data['sources'],
        'inputs_sha256': sha((HERE / INPUTS).read_bytes()),
        'authorization_sha256': sha((HERE / AUTH).read_bytes()),
        'selector_sha256': {name: sha((HERE / name).read_bytes()) for name in SELECTORS},
        'accepted_historical_evidence_limitation': True,
        'historical_disk_and_monotonic_evidence_verified': False})
    write(HERE / VALIDATION, dict(validate_case_references(), full_group_pass=False))
    print('CASE_RESUMPTION_PREPARED', flush=True)


def assemble():
    validate_case_references()
    blocks, label = HERE / 'blocks', 'full-general-remainder'
    result_path, journal_path = blocks / 'full-general.results.json', blocks / 'full-general.ids.jsonl'
    assert not result_path.exists() and not journal_path.exists()
    command_file, result_file, tail_file = [blocks / (label + suffix)
        for suffix in ('.command.json', '.results.json', '.ids.jsonl')]
    command, result = read(command_file), read(result_file)
    current = case_summary()['candidate_tree']
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 0
    assert not command.get('invalidating_incident') and command['candidate_sha'] == current
    assert result['candidate_sha'] == current and result['exit_code'] == 0
    assert result['tests'] == 323 and sorted(result['test_ids']) == remaining_case_ids()
    assert not result['failures'] and not result['errors'] and not result['failed_ids'] and not result.get('xpass', 0)
    tail = [json.loads(line) for line in tail_file.read_bytes().splitlines()]
    assert len(tail) == 323 and sorted(row['id'] for row in tail) == remaining_case_ids()
    assert all(row['outcome'] in ('PASS', 'SKIP', 'XFAIL') for row in tail)
    assert all(next(row['outcome'] for row in tail if row['id'] == item) == 'PASS' for item in FAILED)
    skips = [{'id': row['id'], 'reason': row['reason']} for row in tail if row['outcome'] == 'SKIP']
    assert sorted(skips, key=lambda row: row['id']) == sorted(result['skips'], key=lambda row: row['id'])
    assert sum(row['outcome'] == 'XFAIL' for row in tail) == result.get('xfail', 0)
    groups = []
    for key, (base, rows) in active()['sources'].items():
        spec = read(HERE / INPUTS)['sources'][key]
        accepted = rows if key == 'r6' else [row for row in rows if row['outcome'] == 'PASS']
        groups.append((accepted, {'origin': 'REFERENCED_CASE_PREFIX', 'campaign': spec['campaign'],
            'tested_candidate_tree': OLD, 'accepted_candidate_tree': current,
            'source_artifact': 'referenced-case-evidence/' + key + '/' + spec['journal'],
            'source_sha256': spec['files'][spec['journal']], 'original_invocation_exit': 'UNKNOWN',
            'source_journal_observations': len(rows), 'accepted_case_observations': len(accepted),
            'tests': len(accepted), 'PASS': sum(row['outcome'] == 'PASS' for row in accepted),
            'SKIP': sum(row['outcome'] == 'SKIP' for row in accepted),
            'historical_failed_attempts_preserved': 2 if key == 'r7' else 0,
            'accepted_historical_evidence_limitation': True}))
    groups.append((tail, {'origin': 'CURRENT_EXECUTION', 'campaign': HERE.name,
        'tested_candidate_tree': current, 'accepted_candidate_tree': current,
        'tests': 323, 'command': command_file.relative_to(HERE).as_posix(),
        'command_sha256': sha(command_file.read_bytes()), 'result': result_file.relative_to(HERE).as_posix(),
        'result_sha256': sha(result_file.read_bytes()),
        'source_artifact': tail_file.relative_to(HERE).as_posix(), 'source_sha256': sha(tail_file.read_bytes())}))
    combined = [dict(row, case_provenance=source) for rows, source in groups for row in rows]
    assert len(combined) == len({row['id'] for row in combined}) == 3213
    assert sorted(row['id'] for row in combined) == read(HERE / 'full-general-selected.json')
    logical = dict(result, tests=3213, test_ids=sorted(row['id'] for row in combined),
        skips=[{'id': row['id'], 'reason': row['reason']} for row in combined if row['outcome'] == 'SKIP'],
        exit_code=0, exit_scope='aggregate', exit_code_meaning='aggregate validator success only',
        original_invocation_exits={'r6': 'UNKNOWN', 'r7': 'UNKNOWN'}, logical_aggregate=True,
        seconds_scope='new r8 remainder only; interrupted historical durations unavailable',
        orchestration='authorized r6 cases plus r7 PASS projection plus corrected r8 remainder',
        provenance=provenance(), accepted_historical_evidence_limitation=True,
        historical_disk_and_monotonic_evidence_verified=False,
        historical_failed_attempts=[{'id': item, 'source_campaign': CAMPAIGNS['r7'],
            'original_outcome': 'FAIL', 'superseded_by_corrected_PASS': True,
            'source_journal': 'referenced-case-evidence/r7/blocks/full-general-remainder.ids.jsonl',
            'corrected_candidate_tree': current, 'corrected_journal': tail_file.relative_to(HERE).as_posix()}
            for item in FAILED], source_executions=[source for _, source in groups],
        current_command_sha256=sha(command_file.read_bytes()), current_result_sha256=sha(result_file.read_bytes()))
    validate_case_references()
    with journal_path.open('x', encoding='utf-8', newline='\n') as stream:
        for row in combined:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    write(result_path, logical)
    print('CASE_RESUMPTION_ASSEMBLE_PASS', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'assemble': assemble}[sys.argv[1]]()
