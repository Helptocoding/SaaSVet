"""Preserve completed acceptance results and the real Vitest timeout after STOP."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent.parent


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save(name, data):
    with (HERE / name).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def main():
    assert read('invocation-formal.json')['state'] == 'COMPLETED'
    assert read('STOP.json')['phase'] == 'frontend-test'
    command = read('blocks/frontend-test.command.json')
    assert command['state'] == 'COMPLETED' and command['exit_code'] == 1
    assert command['invalidating_incident'] is None
    result = read('blocks/frontend-tests.json')
    cases = [dict(file=file['name'], **row) for file in result['testResults'] for row in file['assertionResults']]
    assert Counter(row['status'] for row in cases) == {'passed': 354, 'failed': 1}
    failed = [row for row in cases if row['status'] == 'failed']
    log = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', (HERE / 'blocks/frontend-test.command.log').read_text(encoding='utf-8', errors='replace'))
    assert 'Test timed out in 5000ms' in log
    assert failed[0]['title'] == 'un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto'
    assert read('blocks/full.gate.json')['state'] == 'PASS'
    assert read('blocks/full.results.json')['tests'] == 3331
    assert read('blocks/frontend-build.gate.json')['state'] == 'PASS'
    files = ['invocation-formal.json', 'STOP.json', 'evaluation-seal.json', 'candidate.json',
        'candidate-sources.json', 'dependency-files.json', 'full-selected.json',
        'full-general-selected.json', 'full-partition.json', 'case-resumption-inputs.json',
        'case-resumption-manifest.json', 'case-resumption-validation.json', 'reuse-manifest.json',
        'reuse-validation.json', 'blocks/full.ids.jsonl', 'blocks/full.results.json', 'blocks/full.gate.json',
        'blocks/frontend-tests.json', 'blocks/frontend-test.command.json', 'blocks/frontend-test.command.log',
        'blocks/frontend-build.gate.json', 'blocks/frontend-build.command.json',
        'monitor-frontend-test.json', 'monitor-frontend-build.json',
        'awake-request/closure.json', 'resource-observer-closure.json']
    for label in ('full-general-remainder', 'full-general-assemble', 'frontend-build', 'frontend-test'):
        for prefix in ('integrity', 'dependency-check', 'seal-check'):
            for phase in ('before', 'after'):
                name = prefix + '-' + phase + '-' + label + '.json'
                assert not read(name)['mismatches']
                files.append(name)
        for suffix in ('.command.json', '.command.log'):
            name = 'blocks/' + label + suffix
            if (HERE / name).is_file():
                files.append(name)
    for label in ('full-general-remainder', 'full-general'):
        for suffix in ('.ids.jsonl', '.results.json', '.gate.json'):
            name = 'blocks/' + label + suffix
            if (HERE / name).is_file():
                files.append(name)
    seal = read('evaluation-seal.json')
    mismatches = [path for path, wanted in seal['files'].items()
        if not Path(path).is_file() or sha(Path(path)) != wanted]
    assert not mismatches
    monitor = read('monitor-frontend-test.json')
    assert all(row['host']['physical_available'] >= 2 * 2**30 and
        row['host']['disk_available'] >= 2**30 and abs(row['wall_minus_monotonic_seconds']) <= 1 and
        row['awake']['state'] == 'ACTIVE_CONFIRMED' for row in monitor)
    proof = {'state': 'PASS_COMPLETE_PREFIX_WITH_FRONTEND_TIMEOUT', 'candidate_tree': command['candidate_sha'],
        'backend': {'tests': 3331, 'PASS': 3319, 'SKIP': 12, 'gate': 'PASS'}, 'frontend_build': 'PASS',
        'frontend_cases': {'tests': 355, 'PASS': 354, 'TIMEOUT': 1}, 'failed_frontend_cases': failed,
        'timeout_evidence': {'path': 'blocks/frontend-test.command.log', 'exact_message': 'Test timed out in 5000ms'},
        'frontend_test_exit_code': 1, 'controller_exit_code': read('invocation-formal.json')['exit_code'],
        'invalidating_incident': None, 'current_seal_mismatches': mismatches, 'sealed_files': len(seal['files']),
        'monitor': {'samples': len(monitor),
            'RAM_min_GiB': min(row['host']['physical_available'] for row in monitor) / 2**30,
            'disk_min_GiB': min(row['host']['disk_available'] for row in monitor) / 2**30,
            'clock_max_seconds': max(abs(row['wall_minus_monotonic_seconds']) for row in monitor)},
        'no_product_assertion_failure_demonstrated': True, 'remaining_original_stages': 'NOT_EXECUTED',
        'historical_r6_limitation_unchanged': True, 'all_historical_backend_FAILED_attempts_preserved': 3,
        'runtime_preserved_for_possible_authorized_continuation': True,
        'files': {name: sha(HERE / name) for name in dict.fromkeys(files)}}
    save('diagnostics/backend-and-frontend-prefix-validation.json', proof)
    save('final-classification.json', {'decision': 'PENDING',
        'cause': 'One frontend test exhausted the Vitest default 5000ms runner budget; no product assertion failure is shown. Backend full3331 and frontend build passed; 354 frontend PASS retained. Guards and source/dependency/evaluator integrity clean. Security and five profiles not executed under original stop rule.',
        'date_local': '2026-10-20', 'timezone': 'America/Mexico_City',
        'accepted_historical_evidence_limitation': True,
        'evidence': 'diagnostics/backend-and-frontend-prefix-validation.json',
        'no_automatic_correction_or_rerun': True})
    print(json.dumps({'state': proof['state'], 'proof_sha256': sha(HERE / 'diagnostics/backend-and-frontend-prefix-validation.json'),
        'counts': proof['frontend_cases'], 'monitor': proof['monitor'], 'classification': 'PENDING'}))


if __name__ == '__main__':
    main()
