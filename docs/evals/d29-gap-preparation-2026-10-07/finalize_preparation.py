"""Seal this preparation only; never executes a scenario or changes its status."""
import ast
import hashlib
import json
from pathlib import Path
from check_integrity import audit

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    with (HERE/name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    sources = {}
    for path in HERE.glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        sources[path.name] = sha(path)
    write('python-syntax.json', dict(scope='STATIC_PARSE_ONLY', passed=True, source_sha256=sources))
    tests = read(HERE/'offline-tests-02/receipt.json')
    for name, expected in tests['source_sha256'].items():
        if sha(HERE/name) != expected:
            raise ValueError('Tested infrastructure changed: ' + name)
    integrity = audit()
    write('final-integrity.json', integrity)
    if not integrity['intact'] or not tests['passed'] or not read(HERE/'powershell-syntax.json')['passed']:
        raise ValueError('Preparation validation failed')
    write('preparation-receipt.json', dict(schema='d29-five-gap-preparation-v1',
        global_status='CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY',
        base_status='CONFIRMED_BASE_ESTABLISHED', base_sha256=integrity['base_sha256'],
        baseline=integrity['baseline'], physical_runs=0, full_matrix_runs=0, commits=0,
        production_runtime_changes=False, contract_changes=False, base_changes=False,
        host_configuration_changes=False, power_guard_activated=False,
        scenarios=dict(R103='CLOCK_GUARD_PREPARED_PHYSICAL_CONTINUITY_NOT_YET_DEMONSTRATED',
            R104='CAUSAL_SPECIFICATION_PREPARED_COMPATIBILITY_DECISION_PENDING',
            R106='POPULATION_OPTIONS_NOT_SELECTED', R202='DEMAND_OPTIONS_NOT_SELECTED',
            R204='FIXTURE_COMPONENT_PREPARED_PHASE_LAYOUT_AND_CONDUCTOR_INTEGRATION_PENDING',
            R209='EVALUATION_PROVIDER_FIXED_OFFLINE_PHYSICAL_META_AND_QUEUE_EVIDENCE_PENDING'),
        physical_frontier_observed_this_phase=[], load_condition_accredited_this_phase=[],
        prerequisites_pending=['USER_REVIEW', 'R104_CAUSAL_PATTERN', 'R106_POPULATION', 'R202_DEMAND_SEMANTICS',
            'R204_PHASE_LAYOUT', 'AUTHORIZATION_FOR_INDIVIDUAL_REPETITIONS'],
        synthetic_evidence=['offline-tests-01', 'offline-tests-02'],
        historical_physical_evidence='REFERENCED_UNCHANGED_NOT_REEXECUTED_OR_RECLASSIFIED',
        new_host_evidence='host-power-events.json (read-only historical events, not a new probe)',
        verification=dict(offline_tests=tests, protected_sources=integrity['protected_source_count'],
            historical_artifacts=sum(v['count'] for v in integrity['historical_indexes'].values()),
            prior_failed_attempts_preserved=True, application_regression_rerun=False, d29_physical_regression_rerun=False),
        physical_cleanup_needed=False, reason='NO_DATABASE_WORKERS_OR_LIVE_PROVIDER_STARTED',
        modified_scope=str(HERE), continue_automatically=False))
    index = {p.relative_to(HERE).as_posix():dict(bytes=p.stat().st_size, sha256=sha(p))
             for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'artifact-index.json'}
    write('artifact-index.json', index)
    for name, item in read(HERE/'artifact-index.json').items():
        if sha(HERE/name) != item['sha256']:
            raise ValueError('New evidence changed: ' + name)
    print(json.dumps(dict(sealed_artifacts=len(index), source_integrity=int(integrity['intact']),
        historical_artifacts=sum(v['count'] for v in integrity['historical_indexes'].values()),
        offline_tests=tests['tests'], physical_runs=0, commits=0)))


if __name__ == '__main__':
    main()
