"""Preserve 354 Vitest PASS cases and execute only the authorized corrected timeout."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOURCE_CAMPAIGN = 'b9-correction-20261020-native-r9'
OLD_TREE = 'b271e314817da51e99811cb18921fd7c9f59e58a'
NEW_TREE = 'f5f18d71847a46d66644775cd90d30268f072e3b'
TARGET = 'frontend/src/pages/inbox/index.test.jsx'
TARGET_FILE = 'src/pages/inbox/index.test.jsx'
TARGET_NAME = 'Inbox — aislamiento del borrador un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto'
OLD_SOURCE_SHA = '8a98f6857430d5dee656e3b3ddc57a1bcecfd1f98a3c28f72cd328681d03961f'
NEW_SOURCE_SHA = '21de54d2d3d1b1ad629b76aca48242249c22889c1cfb0962cabc529956a2ecd2'
PATCH_SHA = '3d94186cda394428dc02e633b6b8d7478a3ad3b07382b5970645fcd0fdea1bf9'
PROOF = 'diagnostics/backend-and-frontend-prefix-validation.json'
PROOF_SHA = '575339d8ca2f810039c48fe15db3a7c345189ed617f31988f03a4a993caa5449'
AUTH, EQUIVALENCE = 'frontend-resumption-authorization.json', 'frontend-equivalence.json'
MANIFEST, VALIDATION = 'frontend-resumption-manifest.json', 'frontend-resumption-validation.json'
RETAINED, REMAINDER, FULL = ('frontend-retained-pass-selected.json',
                            'frontend-remainder-selected.json', 'frontend-full-selected.json')
ORIGINAL_JSON, ORIGINAL_COMMAND = 'blocks/frontend-tests.json', 'blocks/frontend-test.command.json'
ORIGINAL_LOG = 'blocks/frontend-test.command.log'
RAW_REMAINDER = 'blocks/frontend-test-remainder.json'
REMAINDER_COMMAND = 'blocks/frontend-test-remainder.command.json'
ASSEMBLER_COMMAND = 'blocks/frontend-test-assemble.command.json'
LOGICAL_RESULT = 'blocks/frontend-tests.json'
_CACHE = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def identity_key(item):
    return item['file'], item['fullName']


def identities(cases):
    return sorted((case['identity'] for case in cases), key=identity_key)


def safe_file(value, root):
    value = value.replace('\\', '/')
    prefix = str(root).replace('\\', '/').rstrip('/') + '/'
    if value.startswith(prefix):
        value = value[len(prefix):]
    path = PurePosixPath(value)
    assert value and ':' not in value and not path.is_absolute() and '..' not in path.parts
    assert path.as_posix() == value
    return value


def cases_from_vitest(data, frontend_root):
    cases = []
    for suite in data['testResults']:
        filename = safe_file(suite['name'], frontend_root)
        for case in suite['assertionResults']:
            assert case['fullName'] and isinstance(case['fullName'], str)
            cases.append({'identity': {'file': filename, 'fullName': case['fullName']},
                          'status': case['status'], 'vitest_assertion': case})
    assert len(cases) == len({identity_key(case['identity']) for case in cases})
    assert data['numTotalTests'] == len(cases)
    assert data['numPassedTests'] == sum(case['status'] == 'passed' for case in cases)
    assert data['numFailedTests'] == sum(case['status'] == 'failed' for case in cases)
    return cases


def declarations(check_private=False):
    auth, equivalent, candidate = read(HERE / AUTH), read(HERE / EQUIVALENCE), read(HERE / 'candidate.json')
    assert auth['state'] == 'USER_AUTHORIZED_BEFORE_FORMAL_SEAL'
    assert auth['user_answer'] == 'Sí, ajustar ese armado y continuar sin repetir PASS'
    for declaration in (auth, equivalent):
        assert declaration['previous_candidate_tree'] == OLD_TREE and declaration['candidate_tree'] == NEW_TREE
        assert declaration['allowed_path'] == TARGET and declaration['patch_sha256'] == PATCH_SHA
        assert declaration['product_runtime_locks_changed'] is False
    assert candidate['candidate_tree'] == NEW_TREE and candidate['previous_candidate_tree'] == OLD_TREE
    assert auth['retained_frontend_PASS'] == 354 and auth['new_frontend_selected_ids'] == 1
    for key in ('no_PASS_reruns', 'original_frontend_timeout_and_exit_1_preserved',
                'all_new_guards_and_remaining_original_stages_required',
                'eight_assertions_and_original_5000ms_timeout_unchanged'):
        assert auth[key] is True, key
    assert equivalent['state'] == 'PASS'
    for key in ('normalized_complete_module_AST_identical', 'only_two_input_setup_statements_changed',
                'eight_assertions_and_original_5000ms_timeout_unchanged', 'all_other_3331_blobs_identical',
                'test_ids_imports_hooks_unchanged', 'retained_backend_and_frontend_build_unaffected',
                'original_timeout_and_all_historical_FAILs_preserved'):
        assert equivalent[key] is True, key
    assert equivalent['original_sha256'] == OLD_SOURCE_SHA and equivalent['corrected_sha256'] == NEW_SOURCE_SHA
    assert sha((HERE / 'frontend-correction.diff').read_bytes()) == PATCH_SHA
    analysis_raw = (HERE / 'frontend-proposal-analysis.json').read_bytes()
    assert sha(analysis_raw) == equivalent['proposal_analysis_sha256']
    analysis = json.loads(analysis_raw)
    assert analysis['normalized_complete_module_AST_identical'] is True and analysis['test_expect_calls'] == 8
    assert analysis['assertions_imports_timeouts_test_ids_clicks_navigation_promises_confirmations_unchanged'] is True
    corrected = (REPO / TARGET).read_bytes().replace(b'\r\n', b'\n')
    assert sha(corrected) == NEW_SOURCE_SHA
    original = corrected.decode('utf-8')
    for composer in ('firstComposer', 'returnedComposer'):
        after = f'        fireEvent.change({composer}, {{ target: {{ value: "Texto idéntico, intención nueva" }} }});'
        before = f'        await user.type({composer}, "Texto idéntico, intención nueva");'
        assert original.count(after) == 1
        original = original.replace(after, before, 1)
    assert sha(original.encode('utf-8')) == OLD_SOURCE_SHA
    if check_private:
        from native_support import TREE
        assert (TREE / TARGET).read_bytes() == corrected


def original_cases():
    from backend_resumption import source_root, validate_references
    validate_references()
    base = source_root()
    proof_raw = (base / PROOF).read_bytes()
    assert sha(proof_raw) == PROOF_SHA
    proof = json.loads(proof_raw)
    assert proof['state'] == 'PASS_COMPLETE_PREFIX_WITH_FRONTEND_TIMEOUT' and proof['candidate_tree'] == OLD_TREE
    assert proof['frontend_cases'] == {'tests': 355, 'PASS': 354, 'TIMEOUT': 1}
    assert proof['frontend_test_exit_code'] == 1 and proof['invalidating_incident'] is None
    assert proof['no_product_assertion_failure_demonstrated'] is True
    for name in (ORIGINAL_JSON, ORIGINAL_COMMAND, ORIGINAL_LOG):
        assert sha((base / name).read_bytes()) == proof['files'][name]
    command = read(base / ORIGINAL_COMMAND)
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 1
    assert command['candidate_sha'] == OLD_TREE and command['invalidating_incident'] is None
    assert 'Test timed out in 5000ms' in (base / ORIGINAL_LOG).read_text(encoding='utf-8')
    assembly = read(base / 'assembly.json')
    data = read(base / ORIGINAL_JSON)
    cases = cases_from_vitest(data, Path(assembly['tree']) / 'frontend')
    assert len(cases) == 355 and data['numPendingTests'] == data['numTodoTests'] == 0
    assert sum(case['status'] == 'passed' for case in cases) == 354
    failed = [case for case in cases if case['status'] == 'failed']
    assert len(failed) == 1 and failed[0]['identity'] == {'file': TARGET_FILE, 'fullName': TARGET_NAME}
    assert identities(failed) == [{'file': TARGET_FILE, 'fullName': TARGET_NAME}]
    assert len(proof['failed_frontend_cases']) == 1
    assert proof['failed_frontend_cases'][0]['fullName'] == TARGET_NAME
    return base, cases


def metadata_summary():
    return {'state': 'PASS', 'retained_pass': 354, 'new_selected_ids': 1, 'total_cases': 355,
        'source_campaign': SOURCE_CAMPAIGN, 'source_candidate_tree': OLD_TREE, 'candidate_tree': NEW_TREE,
        'original_command_exit_code': 1, 'original_outcome': 'PENDING_TIMEOUT', 'timeout_ms': 5000,
        'logical_aggregate': True, 'frontend_manifest': MANIFEST, 'frontend_validation': VALIDATION,
        'remainder_command': REMAINDER_COMMAND, 'remainder_result': RAW_REMAINDER,
        'assembler_command': ASSEMBLER_COMMAND, 'logical_result': LOGICAL_RESULT,
        'retained_selector': RETAINED, 'remainder_selector': REMAINDER, 'full_selector': FULL,
        'previous_PASS_cases_rerun': 0, 'original_timeout_and_exit_preserved': True}


def validate_frontend_references():
    global _CACHE
    declarations()
    base, cases = original_cases()
    manifest = read(HERE / MANIFEST)
    assert manifest['schema'] == 'b9-frontend-resumption/1'
    assert manifest['candidate_tree'] == NEW_TREE and manifest['source_candidate_tree'] == OLD_TREE
    assert manifest['completed_manifest_sha256'] == sha((HERE / 'completed-reference-manifest.json').read_bytes())
    assert set(manifest['local_inputs']) == {AUTH, EQUIVALENCE, 'candidate.json',
        'frontend-correction.diff', 'frontend-proposal-analysis.json', RETAINED, REMAINDER, FULL}
    assert set(manifest['original_artifacts']) == {PROOF, ORIGINAL_JSON, ORIGINAL_COMMAND, ORIGINAL_LOG}
    for name, wanted in manifest['local_inputs'].items():
        assert sha((HERE / name).read_bytes()) == wanted, name
    for name, wanted in manifest['original_artifacts'].items():
        assert sha((base / name).read_bytes()) == wanted, name
    retained = [case for case in cases if case['status'] == 'passed']
    selected = [{'file': TARGET_FILE, 'fullName': TARGET_NAME}]
    assert read(HERE / RETAINED) == identities(retained)
    assert read(HERE / REMAINDER) == selected and read(HERE / FULL) == identities(cases)
    assert not {identity_key(item) for item in selected} & {identity_key(item) for item in identities(retained)}
    assert sorted(identities(retained) + selected, key=identity_key) == identities(cases)
    _CACHE = {'base': base, 'cases': cases, 'retained': retained, 'summary': metadata_summary()}
    return dict(_CACHE['summary'])


def summary():
    if _CACHE is None:
        validate_frontend_references()
    return dict(_CACHE['summary'])


def prepare():
    assert not (HERE / 'evaluation-seal.json').exists() and not (HERE / 'invocation-formal.json').exists()
    assert not (HERE / MANIFEST).exists() and not (HERE / VALIDATION).exists()
    declarations(check_private=True)
    base, cases = original_cases()
    for name, selection in ((RETAINED, identities([case for case in cases if case['status'] == 'passed'])),
                            (REMAINDER, [{'file': TARGET_FILE, 'fullName': TARGET_NAME}]), (FULL, identities(cases))):
        write(HERE / name, selection)
    local = (AUTH, EQUIVALENCE, 'candidate.json', 'frontend-correction.diff', 'frontend-proposal-analysis.json',
             RETAINED, REMAINDER, FULL)
    write(HERE / MANIFEST, {'schema': 'b9-frontend-resumption/1', 'candidate_tree': NEW_TREE,
        'source_candidate_tree': OLD_TREE, 'source_campaign': SOURCE_CAMPAIGN,
        'completed_manifest_sha256': sha((HERE / 'completed-reference-manifest.json').read_bytes()),
        'local_inputs': {name: sha((HERE / name).read_bytes()) for name in local},
        'original_artifacts': {name: sha((base / name).read_bytes())
                               for name in (PROOF, ORIGINAL_JSON, ORIGINAL_COMMAND, ORIGINAL_LOG)},
        'previous_PASS_cases_rerun': 0, 'original_command_exit_code': 1, 'original_outcome': 'PENDING_TIMEOUT'})
    write(HERE / VALIDATION, dict(validate_frontend_references(), application_tests_executed=False))
    print('FRONTEND_RESUMPTION_PREPARED', flush=True)


def run():
    validate_frontend_references()
    declarations(check_private=True)
    from native_support import NODE, PNPM, RTK, TREE, environment
    assert not (HERE / RAW_REMAINDER).exists() and not (HERE / 'frontend-remainder-selection.json').exists()
    pattern = '^' + re.escape(TARGET_NAME) + '$'
    argv = [str(RTK), 'proxy', str(NODE), str(PNPM), 'run', 'test', TARGET_FILE,
            '--testNamePattern', pattern, '--reporter=default', '--reporter=json',
            '--outputFile=' + str(HERE / RAW_REMAINDER)]
    write(HERE / 'frontend-remainder-selection.json', {'state': 'EXACT_ONE_CASE_SELECTED',
        'argv': argv, 'cwd': str(TREE / 'frontend'), 'identity': read(HERE / REMAINDER)[0],
        'test_timeout_override': False, 'retries_added': False, 'pool_or_concurrency_changed': False,
        'default_timeout_preserved_ms': 5000, 'previous_PASS_cases_selected': 0})
    result = subprocess.run(argv, cwd=TREE / 'frontend', env=environment(), stdin=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    raise SystemExit(result.returncode)


def assemble():
    validate_frontend_references()
    assert not (HERE / LOGICAL_RESULT).exists()
    command, data = read(HERE / REMAINDER_COMMAND), read(HERE / RAW_REMAINDER)
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 0
    assert command['candidate_sha'] == NEW_TREE and command['invalidating_incident'] is None
    assert data['success'] is True and data['numPassedTests'] == 1 and data['numFailedTests'] == 0
    assert data['numTodoTests'] == 0
    assembly = read(HERE / 'assembly.json')
    cases = cases_from_vitest(data, Path(assembly['tree']) / 'frontend')
    passed = [case for case in cases if case['status'] == 'passed']
    assert len(passed) == 1 and identities(passed) == read(HERE / REMAINDER)
    filtered = [case for case in cases if case['status'] != 'passed']
    original_file_cases = {identity_key(case['identity']) for case in _CACHE['cases']
                           if case['identity']['file'] == TARGET_FILE}
    assert all(case['status'] in ('pending', 'skipped') and identity_key(case['identity']) in original_file_cases
               for case in filtered)
    assert all(case['identity']['file'] == TARGET_FILE for case in cases)
    selection = read(HERE / 'frontend-remainder-selection.json')
    assert selection['identity'] == read(HERE / REMAINDER)[0] and selection['previous_PASS_cases_selected'] == 0
    raw_sha = sha((HERE / RAW_REMAINDER).read_bytes())
    original_sha = sha((_CACHE['base'] / ORIGINAL_JSON).read_bytes())
    combined = []
    for rows, origin, campaign, tree, artifact, digest in (
        (_CACHE['retained'], 'REFERENCED_PASS', SOURCE_CAMPAIGN, OLD_TREE,
         'referenced-completed-evidence/r9/' + ORIGINAL_JSON, original_sha),
        (passed, 'CURRENT_EXECUTION', HERE.name, NEW_TREE, RAW_REMAINDER, raw_sha)):
        combined.extend({'identity': row['identity'], 'status': 'passed', 'provenance': {
            'origin': origin, 'campaign': campaign, 'candidate_tree': tree, 'artifact': artifact,
            'sha256': digest, 'accepted_candidate_tree': NEW_TREE}} for row in rows)
    assert len(combined) == len({identity_key(case['identity']) for case in combined}) == 355
    assert identities(combined) == read(HERE / FULL)
    validate_frontend_references()
    write(HERE / LOGICAL_RESULT, {'schema': 'b9-frontend-logical-aggregate/1', 'state': 'PASS',
        'candidate_tree': NEW_TREE, 'exit_scope': 'aggregate', 'exit_code': 0,
        'exit_code_meaning': 'current aggregate validator success; no whole Vitest invocation claimed',
        'logical_aggregate': True, 'continuous_single_campaign': False,
        'case_counts': {'total': 355, 'passed': 355, 'failed': 0, 'skipped': 0, 'pending': 0, 'todo': 0},
        'cases': sorted(combined, key=lambda case: identity_key(case['identity'])),
        'retained_pass': 354, 'current_pass': 1, 'previous_PASS_cases_rerun': 0,
        'original_command_exit_code': 1, 'original_outcome': 'PENDING_TIMEOUT',
        'original_timeout': {'identity': {'file': TARGET_FILE, 'fullName': TARGET_NAME}, 'timeout_ms': 5000,
            'command_exit_code': 1, 'source_campaign': SOURCE_CAMPAIGN,
            'source_json': 'referenced-completed-evidence/r9/' + ORIGINAL_JSON,
            'source_command': 'referenced-completed-evidence/r9/' + ORIGINAL_COMMAND,
            'source_log': 'referenced-completed-evidence/r9/' + ORIGINAL_LOG,
            'historical_record_changed': False, 'corrected_current_result': RAW_REMAINDER},
        'filtered_case_metadata': {'state': 'NOT_SELECTED_BY_APPROVED_FILTER', 'count': len(filtered),
            'cases': identities(filtered), 'counted_as_acceptance_skips': False,
            'raw_statuses_preserved_in': RAW_REMAINDER},
        'current_remainder_command': REMAINDER_COMMAND,
        'current_remainder_command_sha256': sha((HERE / REMAINDER_COMMAND).read_bytes()),
        'current_remainder_json': RAW_REMAINDER, 'current_remainder_json_sha256': raw_sha,
        'actual_assembler_command': ASSEMBLER_COMMAND, 'provenance': metadata_summary()})
    print('FRONTEND_CASE_AGGREGATE_PASS 355 cases; 354 retained and one current', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'run': run, 'assemble': assemble}[sys.argv[1]]()
