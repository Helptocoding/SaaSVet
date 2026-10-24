"""Authorized r6/r7/r8 case reuse; preserve every historical FAIL and real exit."""
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

HERE = Path(__file__).resolve().parent
CLOCK = '68dffd746793700071f577a58528b0f9636930db'
PREVIOUS = '5e11236daabf4ef70ea9d0f08fee52aed5c30ff2'
SNAPSHOT_PATCH = '6d13efc117f33e26f1701dc568b881a1758adfdfdd3f53bc874b0a9989512a50'
BASELINE_PATCH = '483810b0b9474e9683316d33622480319d1e08f12a2cd66337a22482505e4aa3'
WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
INPUTS, AUTH = 'case-resumption-inputs.json', 'baseline-resumption-authorization.json'
MANIFEST, VALIDATION = 'case-resumption-manifest.json', 'case-resumption-validation.json'
SELECTORS = ('retained-r6-observed-ids.json', 'retained-r7-pass-ids.json',
             'retained-r8-valid-ids.json', 'full-general-remainder-selected.json')
SNAPSHOTS = sorted(['apps.agent.tests.test_contracts.CommitmentContractTests.test_fields_match_snapshot',
                    'apps.agent.tests.test_contracts.ToolOutcomeContractTests.test_fields_match_snapshot'])
FAILED = ['apps.core.tests.test_tenant_scoping_audit.TenantScopingAuditTests.test_no_unbaselined_objects_access_without_for_organization']
CAMPAIGNS = {'r6': 'b9-correction-20261017-native-r6', 'r7': 'b9-correction-20261019-native-r7',
             'r8': 'b9-correction-20261020-native-r8'}
TREES = {'r6': CLOCK, 'r7': CLOCK, 'r8': PREVIOUS}
EXITS = {'r6': 'UNKNOWN', 'r7': 'UNKNOWN', 'r8': 1}
PROOFS = {'r6': '51bed99c98bc8683f2764c841076f6ea47288fe339608fd122c4b405ba9e21db',
          'r7': 'c570dac8c00264eeb919f9c80a61289b7ed021ee2e629552ad8f0e4df0d5179d',
          'r8': '80a3ebbb7ae3d817d0a6d23c0658b3e8e05ac8dc54fe7be18fe336296e543eb0'}
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


def descriptor(item):
    path = HERE / relative(item['path'])
    assert path.resolve().is_relative_to(HERE.resolve()) and path.is_file()
    assert sha(path.read_bytes()) == item['sha256'], item['path']
    return path


def metadata():
    data, candidate, auth = read(HERE / INPUTS), read(HERE / 'candidate.json'), read(HERE / AUTH)
    current = candidate['candidate_tree']
    assert data['schema'] == 'b9-case-resumption-inputs/3'
    assert data['source_candidate_tree'] == PREVIOUS and data['candidate_tree'] == current != PREVIOUS
    assert auth['state'] == 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL'
    assert auth['user_answer'] == 'Sí, corregir ese baseline y continuar sin repetir PASS'
    assert auth['previous_candidate_tree'] == PREVIOUS and auth['candidate_tree'] == current
    for key in ('no_PASS_reruns', 'all_old_FAILs_preserved', 'accepted_historical_evidence_limitation',
                'all_new_guards_and_remaining_original_stages_required'):
        assert auth[key] is True, key
    assert auth['retained_general_PASS'] == 3200 and auth['retained_expected_SKIPs'] == 12
    assert auth['corrected_FAILED_ids'] == 1 and auth['historical_FAILED_attempts'] == 3
    assert auth['product_runtime_locks_changed'] is False
    baseline = read(descriptor(data['baseline_equivalence']))
    assert baseline['state'] == 'PASS' and baseline['previous_candidate_tree'] == PREVIOUS
    assert baseline['candidate_tree'] == current
    assert baseline['allowed_path'] == 'backend/apps/core/tests/test_tenant_scoping_audit.py'
    assert baseline['patch_sha256'] == auth['patch_sha256'] == sha(descriptor(data['baseline_patch']).read_bytes()) == BASELINE_PATCH
    for key in ('only_one_reviewed_baseline_tuple_added_AST', 'all_other_AST_unchanged',
                'scanner_assertions_exclusions_test_ids_imports_hooks_unchanged',
                'all_other_3331_blobs_identical', 'all_old_FAILs_preserved'):
        assert baseline[key] is True, key
    assert baseline['product_runtime_locks_changed'] is False
    snapshot = read(descriptor(data['snapshot_equivalence']))
    assert snapshot['state'] == 'PASS' and snapshot['previous_candidate_tree'] == CLOCK
    assert snapshot['candidate_tree'] == PREVIOUS
    assert snapshot['allowed_path'] == 'backend/apps/agent/tests/test_contracts.py'
    assert snapshot['patch_sha256'] == sha(descriptor(data['snapshot_patch']).read_bytes()) == SNAPSHOT_PATCH
    for key in ('only_two_expected_literal_lists_change_ast', 'assertions_other_AST_unchanged',
                'all_other_3331_blobs_identical', 'test_ids_imports_hooks_unchanged', 'old_FAILs_preserved'):
        assert snapshot[key] is True, key
    assert snapshot['product_runtime_locks_changed'] is False and set(data['sources']) == set(CAMPAIGNS)
    assembly = read(HERE / 'assembly.json')
    assert assembly['candidate_sha'] == current and assembly['port'] == 35490
    assert Path(assembly['workspace']).resolve() == WORK.resolve()
    assert Path(assembly['tree']).resolve() == WORK.resolve() / 'src'
    return data, current


def verify_r8(base, spec, rows, command, invocation):
    label = 'full-general-remainder'
    result = read(base / ('blocks/' + label + '.results.json'))
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 1
    assert command['invalidating_incident'] is None
    assert invocation['state'] == 'COMPLETED' and invocation['exit_code'] == 2
    assert result['candidate_sha'] == PREVIOUS and result['exit_code'] == 1
    assert result['tests'] == 323 and result['failures'] == 1 and not result['errors']
    assert not result['xfail'] and not result['xpass'] and result['failed_ids'] == FAILED
    assert sorted(result['test_ids']) == sorted(row['id'] for row in rows)
    skips = sorted((row['id'], row['reason']) for row in rows if row['outcome'] == 'SKIP')
    assert skips == sorted((row['id'], row['reason']) for row in result['skips']) and len(skips) == 10
    stop = read(base / 'STOP.json')
    assert stop['state'] == 'PENDING_CLASSIFICATION' and stop['failed_ids'] == FAILED
    assert read(base / ('blocks/' + label + '.gate.json'))['state'] == 'NONPASS_REQUIRES_CLASSIFICATION'
    for phase in ('before', 'after'):
        for prefix, field, expected in (('integrity', 'checked_files', 3332),
                                        ('dependency-check', 'checked', 44636),
                                        ('seal-check', 'checked', len(read(base / 'evaluation-seal.json')['files']))):
            receipt = read(base / (prefix + '-' + phase + '-' + label + '.json'))
            assert receipt[field] == expected and not receipt['mismatches']
    monitor = read(base / ('monitor-' + label + '.json'))
    assert monitor and all(row['host']['physical_available'] >= 2 * 1024**3 and
        row['host']['disk_available'] >= 1024**3 and abs(row['wall_minus_monotonic_seconds']) <= 1 and
        row['awake']['state'] == 'ACTIVE_CONFIRMED' for row in monitor)
    proof = read(base / spec['proof'])
    assert spec['files'][spec['proof']] == PROOFS['r8']
    assert proof['state'] == 'PASS_INTEGRITY_WITH_RECORDED_FAILURE' and proof['candidate_tree'] == PREVIOUS
    assert proof['outcomes'] == {'PASS': 312, 'SKIP': 10, 'FAIL': 1} and proof['failed_ids'] == FAILED
    assert proof['suite_exit_code'] == 1 and proof['controller_exit_code'] == 2
    assert proof['invalidating_incident'] is None and not proof['current_seal_mismatches']
    assert (proof['sources'], proof['dependencies'], proof['sealed_files']) == (3332, 44636, 172)
    assert proof['historical_r6_limitation_unchanged'] is True
    assert proof['runtime_preserved_for_possible_authorized_continuation'] is True
    assert all(spec['files'].get(name) == wanted for name, wanted in proof['files'].items())
    assert proof['monitor'] == {'samples': len(monitor),
        'min_RAM_GiB': min(row['host']['physical_available'] for row in monitor) / 1024**3,
        'min_disk_GiB': min(row['host']['disk_available'] for row in monitor) / 1024**3,
        'max_abs_clock_seconds': max(abs(row['wall_minus_monotonic_seconds']) for row in monitor)}
    assert read(base / 'final-classification.json')['decision'] == 'FAIL'
    assert read(base / 'resource-observer-closure.json')['state'] == 'PASS'
    awake = read(base / 'awake-request/closure.json')
    assert awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and awake['matches_original_thread_state'] is True


def source(key, spec, bundled):
    assert spec['campaign'] == CAMPAIGNS[key]
    base = HERE / 'referenced-case-evidence' / key if bundled else HERE.with_name(spec['campaign'])
    assert base.is_dir() and not base.is_symlink() and not base.is_junction()
    expected_label = 'full-general' if key == 'r6' else 'full-general-remainder'
    assert spec['journal'] == 'blocks/' + expected_label + '.ids.jsonl'
    assert spec['selected'] == expected_label + '-selected.json'
    command_name = 'blocks/' + expected_label + '.command.json'
    required = {spec['journal'], spec['selected'], spec['proof'], command_name, 'candidate.json',
                'candidate-sources.json', 'dependency-files.json', 'evaluation-seal.json',
                'recorded_suite.py', 'effective-configuration.json', 'assembly.json', 'invocation-formal.json'}
    if key == 'r8':
        required |= {'blocks/full-general-remainder.results.json', 'blocks/full-general-remainder.gate.json',
                     'STOP.json', 'monitor-full-general-remainder.json', 'final-classification.json',
                     'resource-observer-closure.json', 'awake-request/closure.json'}
        required |= {prefix + '-' + phase + '-full-general-remainder.json'
                     for prefix in ('integrity', 'dependency-check', 'seal-check') for phase in ('before', 'after')}
    assert required <= set(spec['files'])
    for name, wanted in spec['files'].items():
        path = base / relative(name)
        assert path.resolve().is_relative_to(base.resolve()) and path.is_file()
        assert not path.is_symlink() and not path.is_junction()
        assert sha(path.read_bytes()) == wanted, key + ':' + name
        original_base, original = HERE.with_name(spec['campaign']), HERE.with_name(spec['campaign']) / relative(name)
        if bundled and original_base.exists():
            assert original.is_file() and sha(original.read_bytes()) == wanted, 'Original drift: ' + str(original)
    assert read(base / 'candidate.json')['candidate_tree'] == TREES[key]
    command, invocation = read(base / command_name), read(base / 'invocation-formal.json')
    assert command['candidate_sha'] == TREES[key]
    for name in ('dependency-files.json', 'effective-configuration.json', 'recorded_suite.py'):
        assert (base / name).read_bytes() == (HERE / name).read_bytes(), name
    rows = [json.loads(line) for line in (base / spec['journal']).read_bytes().splitlines()]
    ids = [row['id'] for row in rows]
    assert len(ids) == len(set(ids)) and set(ids) <= set(read(base / spec['selected']))
    if key == 'r8':
        verify_r8(base, spec, rows, command, invocation)
    else:
        assert command['state'] == invocation['state'] == 'RUNNING'
        proof = read(base / spec['proof'])
        assert spec['files'][spec['proof']] == PROOFS[key] and proof['candidate_tree'] == CLOCK
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
            assert proof['current_byte_integrity']['candidate_tree'] == CLOCK
            integrity = {name: proof['current_byte_integrity'][name] for name in ('sources', 'dependencies', 'evaluation_seal')}
            observer = proof['durable_host_observer']
            assert observer['covers_start'] and observer['covers_end'] and not observer['uncovered_cases']
            assert not observer['gaps_over_ten_seconds'] and observer['minimum_ram_bytes'] >= 2 * 1024**3
            assert observer['minimum_disk_bytes'] >= 1024**3 and observer['maximum_absolute_wall_monotonic_skew_seconds'] <= 1
            assert proof['prefix']['failed_cases_are_not_dropped_or_changed_to_pass'] is True
        assert all(not row['mismatches'] and not row.get('missing', []) for row in integrity.values())
    return base, rows


def partition(data, bundled):
    sources = {key: source(key, spec, bundled) for key, spec in data['sources'].items()}
    a, j7, j8 = (sources[key][1] for key in ('r6', 'r7', 'r8'))
    assert Counter(row['outcome'] for row in a) == {'PASS': 2483, 'SKIP': 2}
    assert Counter(row['outcome'] for row in j7) == {'PASS': 405, 'FAIL': 2}
    assert Counter(row['outcome'] for row in j8) == {'PASS': 312, 'SKIP': 10, 'FAIL': 1}
    assert sorted(row['id'] for row in j7 if row['outcome'] == 'FAIL') == SNAPSHOTS
    assert [row['id'] for row in j8 if row['outcome'] == 'FAIL'] == FAILED
    assert all(next(row['outcome'] for row in j8 if row['id'] == item) == 'PASS' for item in SNAPSHOTS)
    selections = (sorted(row['id'] for row in a), sorted(row['id'] for row in j7 if row['outcome'] == 'PASS'),
                  sorted(row['id'] for row in j8 if row['outcome'] in ('PASS', 'SKIP')), FAILED)
    assert [len(ids) for ids in selections] == [2485, 405, 322, 1]
    for name, expected in zip(SELECTORS, selections):
        assert read(HERE / name) == expected, name
    all_ids = [item for ids in selections for item in ids]
    assert len(all_ids) == len(set(all_ids)) == 3213
    assert sorted(all_ids) == read(HERE / 'full-general-selected.json')
    assert sorted(row['id'] for row in j8) == read(sources['r8'][0] / data['sources']['r8']['selected'])
    prior_tail = read(sources['r7'][0] / data['sources']['r7']['selected'])
    assert len(prior_tail) == len(set(prior_tail)) == 728
    assert set(prior_tail) == {row['id'] for row in j7} | {row['id'] for row in j8}
    critical = set().union(*(set(read(HERE / (name + '-selected.json'))) for name in ('directed', 'b0', 'b3', 'b4', 'b5')))
    assert not critical & {row['id'] for row in a + j8 if row['outcome'] == 'SKIP'}
    preserved = read(HERE / 'preserved-failed-cases.json')['failed_cases']
    original_failures = [(CAMPAIGNS[key], row) for key, (_, rows) in sources.items()
                         for row in rows if row['outcome'] == 'FAIL']
    assert len(preserved) == len(original_failures) == 3
    assert len({(row['source_campaign'], row['id']) for row in preserved}) == 3
    for campaign, row in original_failures:
        saved = next(item for item in preserved if item['source_campaign'] == campaign and item['id'] == row['id'])
        assert all(saved.get(key) == value for key, value in row.items())
    return sources, list(selections[0] + selections[1] + selections[2]), FAILED


def summary(current):
    return {'state': 'PASS', 'candidate_tree': current, 'source_candidate_tree': PREVIOUS,
            'retained_ids': 3212, 'retained_PASS': 3200, 'retained_SKIP': 12, 'new_selected_ids': 1,
            'previous_accepted_cases': 3212, 'prior_pass': 3200, 'prior_skips': 12, 'current_cases': 1,
            'historical_failed_attempts': 3, 'result_general': 3213, 'corrected_failed_case_ids': FAILED,
            'snapshot_corrected_case_ids': SNAPSHOTS,
            'retained_sources': {'r6': {'tests': 2485, 'PASS': 2483, 'SKIP': 2},
                'r7': {'tests': 405, 'PASS': 405, 'SKIP': 0, 'source_journal_observations': 407, 'excluded_historical_FAIL': 2},
                'r8': {'tests': 322, 'PASS': 312, 'SKIP': 10, 'source_journal_observations': 323, 'excluded_historical_FAIL': 1}},
            'original_invocation_exits': EXITS, 'historical_disk_and_monotonic_evidence_verified': False,
            'accepted_historical_evidence_limitation': True, 'manifest': MANIFEST, 'validation': VALIDATION,
            'authorization': AUTH, 'manifest_sha256': sha((HERE / MANIFEST).read_bytes())}


def validate_case_references():
    global _CACHE
    data, current = metadata()
    manifest = read(HERE / MANIFEST)
    assert manifest['inputs_sha256'] == sha((HERE / INPUTS).read_bytes())
    assert manifest['authorization_sha256'] == sha((HERE / AUTH).read_bytes())
    assert manifest['preserved_failed_cases_sha256'] == sha((HERE / 'preserved-failed-cases.json').read_bytes())
    assert manifest['candidate_tree'] == current and manifest['sources'] == data['sources']
    assert manifest['selector_sha256'] == {name: sha((HERE / name).read_bytes()) for name in SELECTORS}
    sources, retained, remaining = partition(data, True)
    _CACHE = {'sources': sources, 'retained': retained, 'remaining': remaining, 'summary': summary(current)}
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
                campaign=HERE.name, tested_candidate_tree=case_summary()['candidate_tree'],
                accepted_candidate_tree=case_summary()['candidate_tree'], full_general_scope='logical case aggregate')


def prepare():
    assert not (HERE / 'evaluation-seal.json').exists() and not (HERE / 'invocation-formal.json').exists()
    assert not (HERE / MANIFEST).exists() and not (HERE / VALIDATION).exists()
    assert not (HERE / 'referenced-case-evidence').exists()
    data, current = metadata()
    sources, _, _ = partition(data, False)
    for key, (base, _) in sources.items():
        for name, wanted in data['sources'][key]['files'].items():
            raw = (base / relative(name)).read_bytes()
            assert sha(raw) == wanted
            target = HERE / 'referenced-case-evidence' / key / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
    write(HERE / MANIFEST, {'schema': 'b9-case-resumption/3', 'candidate_tree': current,
        'source_candidate_tree': PREVIOUS, 'sources': data['sources'], 'inputs_sha256': sha((HERE / INPUTS).read_bytes()),
        'authorization_sha256': sha((HERE / AUTH).read_bytes()),
        'preserved_failed_cases_sha256': sha((HERE / 'preserved-failed-cases.json').read_bytes()),
        'selector_sha256': {name: sha((HERE / name).read_bytes()) for name in SELECTORS},
        'accepted_historical_evidence_limitation': True, 'historical_disk_and_monotonic_evidence_verified': False})
    write(HERE / VALIDATION, dict(validate_case_references(), full_group_pass=False))
    print('CASE_RESUMPTION_PREPARED', flush=True)


def assemble():
    validate_case_references()
    blocks, label = HERE / 'blocks', 'full-general-remainder'
    result_path, journal_path = blocks / 'full-general.results.json', blocks / 'full-general.ids.jsonl'
    assert not result_path.exists() and not journal_path.exists()
    command_file, result_file, tail_file = [blocks / (label + suffix) for suffix in ('.command.json', '.results.json', '.ids.jsonl')]
    command, result, current = read(command_file), read(result_file), case_summary()['candidate_tree']
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 0
    assert command['invalidating_incident'] is None and command['candidate_sha'] == current
    assert result['candidate_sha'] == current and result['exit_code'] == 0
    assert result['tests'] == 1 and result['test_ids'] == FAILED
    assert not any(result[key] for key in ('failures', 'errors', 'failed_ids', 'skips', 'xfail', 'xpass'))
    tail = [json.loads(line) for line in tail_file.read_bytes().splitlines()]
    assert len(tail) == 1 and tail[0]['id'] == FAILED[0] and tail[0]['outcome'] == 'PASS'
    groups, historical = [], []
    for key, (base, rows) in active()['sources'].items():
        spec = read(HERE / INPUTS)['sources'][key]
        accepted = [row for row in rows if row['outcome'] in ('PASS', 'SKIP')]
        source_info = {'origin': 'REFERENCED_CASE_PREFIX', 'campaign': spec['campaign'],
            'tested_candidate_tree': TREES[key], 'accepted_candidate_tree': current,
            'source_artifact': 'referenced-case-evidence/' + key + '/' + spec['journal'],
            'source_sha256': spec['files'][spec['journal']], 'original_invocation_exit': EXITS[key],
            'source_journal_observations': len(rows), 'accepted_case_observations': len(accepted),
            'tests': len(accepted), 'PASS': sum(row['outcome'] == 'PASS' for row in accepted),
            'SKIP': sum(row['outcome'] == 'SKIP' for row in accepted),
            'historical_failed_attempts_preserved': sum(row['outcome'] == 'FAIL' for row in rows),
            'accepted_historical_evidence_limitation': True}
        groups.append((accepted, source_info))
        for row in rows:
            if row['outcome'] != 'FAIL':
                continue
            corrected_source = 'referenced-case-evidence/r8/blocks/full-general-remainder.ids.jsonl' if key == 'r7' else tail_file.relative_to(HERE).as_posix()
            historical.append({'id': row['id'], 'source_campaign': spec['campaign'], 'original_outcome': 'FAIL',
                'source_journal': source_info['source_artifact'], 'original_invocation_exit': EXITS[key],
                'superseded_by_corrected_PASS': True, 'corrected_candidate_tree': PREVIOUS if key == 'r7' else current,
                'corrected_journal': corrected_source})
    assert len(historical) == 3
    groups.append((tail, {'origin': 'CURRENT_EXECUTION', 'campaign': HERE.name, 'tested_candidate_tree': current,
        'accepted_candidate_tree': current, 'tests': 1, 'command': command_file.relative_to(HERE).as_posix(),
        'command_sha256': sha(command_file.read_bytes()), 'result': result_file.relative_to(HERE).as_posix(),
        'result_sha256': sha(result_file.read_bytes()), 'source_artifact': tail_file.relative_to(HERE).as_posix(),
        'source_sha256': sha(tail_file.read_bytes())}))
    combined = [dict(row, case_provenance=source_info) for rows, source_info in groups for row in rows]
    assert len(combined) == len({row['id'] for row in combined}) == 3213
    assert sorted(row['id'] for row in combined) == read(HERE / 'full-general-selected.json')
    logical = dict(result, tests=3213, test_ids=sorted(row['id'] for row in combined),
        skips=[{'id': row['id'], 'reason': row['reason']} for row in combined if row['outcome'] == 'SKIP'],
        exit_code=0, exit_scope='aggregate', exit_code_meaning='aggregate validator success only',
        original_invocation_exits=EXITS, logical_aggregate=True,
        seconds_scope='new r9 single case only; interrupted historical durations unavailable',
        orchestration='authorized r6 cases, r7 PASS, r8 PASS/SKIP, and one corrected r9 case',
        provenance=provenance(), accepted_historical_evidence_limitation=True,
        historical_disk_and_monotonic_evidence_verified=False, historical_failed_attempts=historical,
        source_executions=[source_info for _, source_info in groups],
        current_command_sha256=sha(command_file.read_bytes()), current_result_sha256=sha(result_file.read_bytes()))
    validate_case_references()
    with journal_path.open('x', encoding='utf-8', newline='\n') as stream:
        for row in combined:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    write(result_path, logical)
    print('CASE_RESUMPTION_ASSEMBLE_PASS', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'assemble': assemble}[sys.argv[1]]()
