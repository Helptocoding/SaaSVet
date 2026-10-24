"""Create post-stop disposition metadata from retained receipts, without tests."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]

def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))

def save(name, value):
    target = HERE / name
    assert not target.exists(), name
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

assert read('STOP.json')['state'] == 'PENDING_CLASSIFICATION'
assert read('incident-classification.json')['state'] == 'PENDING'
assert read('cleanup.json')['state'] == read('clock-restoration.json')['state'] == 'PASS'
jobs = {}
all_ids, passed, failed = set(), set(), set()
for kind in ('directed', 'b0', 'b3'):
    receipt = read('blocks/' + kind + '.results.json')
    expected = read(kind + '-selected.json')
    assert sorted(receipt['test_ids']) == expected and receipt['tests'] == len(expected)
    if kind == 'directed':
        rows = [json.loads(line) for line in (HERE / 'blocks/directed.results.passed.jsonl').read_text().splitlines()]
        good = {row['test_id'] for row in rows}
        assert len(rows) == 87 and all(row['status'] == 'ok' for row in rows)
        bad = set()
    else:
        rows = [json.loads(line) for line in (HERE / ('blocks/' + kind + '.ids.jsonl')).read_text().splitlines()]
        assert len(rows) == len(expected) and {row['id'] for row in rows} == set(expected)
        good = {row['id'] for row in rows if row['outcome'] == 'PASS'}
        bad = {row['id'] for row in rows if row['outcome'] == 'FAIL'}
    assert good | bad == set(expected) and not good & bad
    jobs[kind] = {'observations': len(rows), 'unique_ids': len(set(expected)), 'passed': len(good),
        'raw_failures': len(bad), 'errors': receipt['errors'], 'skips': receipt['skips'],
        'xfail': receipt['xfail'], 'passed_ids': sorted(good), 'raw_failed_ids': sorted(bad),
        'gate': 'PENDING_ENVIRONMENT' if bad else 'PASS'}
    all_ids.update(expected)
    passed.update(good)
    failed.update(bad)
assert (len(all_ids), len(passed), len(failed)) == (146, 143, 3)
scope = read('scope-manifest.json')
assert set(scope['historical_negative_ids_to_rerun']).issubset(set(jobs['directed']['passed_ids']))
candidate = read('assembly.json')['candidate_sha']
summary = {'schema': 'b9i-wsl-r3-execution-summary-v1', 'candidate_sha': candidate, 'jobs': jobs,
    'backend_id_observations': sum(job['observations'] for job in jobs.values()),
    'backend_unique_ids_observed': len(all_ids), 'backend_unique_ids_passed': len(passed),
    'backend_unique_ids_raw_failed_before_contract': len(failed),
    'cross_job_duplicate_observations': sum(job['observations'] for job in jobs.values()) - len(all_ids),
    'raw_failed_ids': sorted(failed),
    'raw_failures_classification': 'PENDING_ENVIRONMENT; all three B3 cases failed readiness before their contract operation',
    'required_negative_ids': {'selected': 41, 'passed': 41,
        'I04': 'DIRECTED_NEGATIVES_PASS', 'I07': 'DIRECTED_NEGATIVES_PASS'},
    'full_suite_discovered_ids': 3331, 'full_suite_executed': False,
    'frontend_tests_executed': False, 'profile_variants_executed': 0,
    'historical_metrics_transferred': False}
save('execution-summary.json', summary)

labels = ['directed', 'django-check', 'migration-drift', 'migrate', 'billing-schema', 'b0', 'b3',
    'b4', 'b5', 'full', 'frontend-build', 'frontend-test', 'frontend-lint', 'frontend-smoke-urls',
    'security', 'pip-audit', 'pnpm-audit']
states = {}
for label in labels:
    if not (HERE / ('blocks/' + label + '.command.json')).exists():
        states[label] = {'state': 'NOT_EXECUTED', 'formal_runs': 0}
        continue
    command = read('blocks/' + label + '.command.json')
    assert command['state'] == 'COMPLETED' and command['resources_before']['ready']
    assert command['invalidating_incident'] is None
    gate = read('blocks/' + label + '.gate.json')
    states[label] = {'state': 'PENDING_ENVIRONMENT' if label == 'b3' else gate['state'],
        'raw_gate_state': gate['state'], 'formal_runs': 1, 'command_exit_code': command['exit_code'],
        'seconds': command['seconds'], 'receipt': 'blocks/' + label + '.command.json'}
for scenario in ('base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation'):
    states['profile-' + scenario] = {'state': 'NOT_EXECUTED', 'formal_runs': 0,
                                    'original_gate_definitions_unchanged': True}
save('block-status.json', {'schema': 'b9i-wsl-r3-block-status-v1', 'candidate_sha': candidate,
    'decision': 'PENDING', 'blocks': states, 'raw_stop': 'STOP.json',
    'final_classification': 'incident-classification.json', 'formal_reruns': 0})

requirements = {
    'R01': 'PENDING_INTEGRAL; directed corpus PASS, B3 environment incompatibility and remaining gates incomplete',
    'R02': 'DIRECTED_E2E_PASS; public/personal READ, five WRITE and B9A processes; full regression not executed',
    'R03': 'DIRECTED_COST_PASS; shared operational budget and usage contracts in selected IDs; full regression not executed',
    'R04': 'DIRECTED_SCALE_PASS; N=1 and independent planners/sender; B3 process contract PENDING and temporal PROFILE not executed',
    'R05': 'DIRECTED_BUDGET_PASS; last slot, exhaustion and retry without refund; no full regression claim',
    'R06': 'PARTIAL_LOCAL_CI_CHECKS; directed, Django, schema and B0 PASS; B3 PENDING; B4/B5/full/frontend/security NOT_EXECUTED; remote CI not run',
    'R07': 'PENDING_NOT_EXECUTED; all five PROFILE variants',
    'R08': 'DECISION_AND_LIMITS_DOCUMENTED; technical PENDING separate from activation',
    'R09': 'PENDING_NOT_EXECUTED; no temporal PROFILE metrics; clock/resource monitor is not an application performance result',
    'R10': 'DIRECTED_CORPUS_PASS; 87 exact unique IDs including EVAL/COST/SCALE/FI and I04/I07 negatives; full regression incomplete',
    'R11': 'CURRENT_CHECKS_AND_DIRECTED_BUDGET_PASS; migrations and Billing schema PASS; no full regression claim',
    'R12': 'DIRECTED_CAPACITY_BOUNDARIES_PASS; N-minus-one/N/N-plus-one; no scheduler, billing or commercial capacity change',
    'R13': 'DIRECTED_ORGANIZATION_GATES_PASS; real operational READ/release approval remains pending',
    'R14': 'EXISTING_DOCUMENTATION_PRESERVED; directed harness PASS; legacy B3 subprocess dependency incompatibility recorded',
    'R15': 'DECISION_AND_EVIDENCE_CONSERVED; technical acceptance PENDING; real privacy/operational approvals remain separate',
}
invariants = {
    'I01': 'DIRECTED_PASS; five authorized WRITE effects; remaining integral gates incomplete',
    'I02': 'DIRECTED_PASS; scope/correction and stale authorization negatives; remaining integral gates incomplete',
    'I03': 'DIRECTED_PASS; issued proposal and causal reply boundary; remaining integral gates incomplete',
    'I04': 'DIRECTED_NEGATIVES_PASS; direct/indirect attendance questions and forced wrong tool do not mutate',
    'I05': 'DIRECTED_PASS; unapproved organization/permission gates and absence of prohibited effects',
    'I06': 'DIRECTED_PASS; typed outcome, receipt, rollback and outbound states remain distinct',
    'I07': 'DIRECTED_NEGATIVES_PASS; 39 B2 results/transport/effect cases distinguish errors, empty, partial and success',
    'I08': 'DIRECTED_SAFETY_PASS; temporal PROFILE safety gates NOT_EXECUTED',
    'I09': 'DIRECTED_TAKEOVER_PASS; B3 process/regression gate PENDING and full regression NOT_EXECUTED',
    'I10': 'PARTIAL_DIRECTED_RECOVERY_PASS; selected B9 FI PASS; B3 crash/restart subprocess contract not evaluated',
    'I11': 'DIRECTED_UNCERTAINTY_PASS; no blind retry; META_SLOW PROFILE NOT_EXECUTED',
    'I12': 'DIRECTED_PASS; verified owner/pet and conversation binding scope',
    'I13': 'DIRECTED_PASS; tenant isolation and independent planners; full regression NOT_EXECUTED',
    'I14': 'DIRECTED_PASS; correction retires old proposal before effect',
}
decision = {'schema': 'b9i-wsl-r3-candidate-decision-v1', 'date': '2026-10-11',
    'candidate_sha': candidate, 'decision': 'PENDING',
    'campaign_state': 'STOPPED_ENVIRONMENT_SUBPROCESS_DEPENDENCY_VISIBILITY',
    'cause': 'Three legacy B3 tests launch sys._base_executable, whose private installation cannot import Django from the campaign venv; all three ended before B3_READY.',
    'cause_evidence': ['incident-classification.json', 'base-interpreter-diagnostic.json',
                      'blocks/b3.results.json', 'blocks/b3.command.log', 'STOP.json'],
    'product_failure_attributed': False, 'raw_stop_state_preserved': 'PENDING_CLASSIFICATION',
    'raw_runner_failures': 3, 'raw_runner_failures_are_not_converted_to_pass': True,
    'formal_block_runs': 7, 'formal_reruns': 0, 'backend_id_observations': 146,
    'backend_unique_ids_passed': 143, 'backend_unique_ids_raw_failed_before_contract': 3,
    'directed_tests': {'tests': 87, 'state': 'PASS'}, 'b0_tests': {'tests': 17, 'state': 'PASS'},
    'b3_tests': {'tests': 42, 'passed': 39, 'raw_failures': 3, 'state': 'PENDING_ENVIRONMENT'},
    'full_ids_discovered_not_executed': 3331, 'profile_variants_executed': 0,
    'R01_R15': requirements, 'I01_I14': invariants,
    'coverage_definition': 'DIRECTED_PASS and partial dispositions refer only to exact current candidate IDs, not integral acceptance, universal behavior or remote CI. Historical evidence remains unchanged.',
    'operational_requirements': {'R06_real_promotion_eval': 'PENDING_SEPARATE',
        'R13_real_release_readiness': 'PENDING_SEPARATE', 'R15_P_A_P_B_privacy': 'PENDING_SEPARATE'},
    'activation': 'PENDING_ACTIVATION_REQUIREMENTS',
    'R1-04': 'PENDING_WITH_ACCEPTED_LIMITATION; zero new physical attempts',
    'E_P_UX': 'SEPARATE_UNCHANGED_SCOPES',
    'historical_profile_candidate': '08310461337a284386299ec47c54125f2139bf7f',
    'historical_profile_metrics_transferred_to_current_candidate': False,
    'clock_control': 'Approved temporary pause; restored active/running/enabled after cleanup; Windows W32Time unchanged',
    'clock_or_resource_incidents_during_blocks': False,
    'frontend_dependency_install': 'PASS_FROZEN_LOCKFILE_IN_LINUX; frontend CI checks NOT_EXECUTED',
    'candidate_sources': '3332 exact Git blobs; final integrity PASS',
    'evaluation_seal': '91 files; all completed post-block checks intact',
    'cleanup': 'PASS', 'clock_restoration': 'PASS',
    'new_campaign': 'Requires a new execution decision after resolving base-interpreter dependency visibility before the seal; no automatic retry',
    'commits_created': 0, 'pushes_performed': 0, 'production_activation_or_deployment': False}
save('candidate-decision.json', decision)
print(json.dumps({'decision': 'PENDING', 'formal_blocks': 7, 'observed_unique_ids': 146,
                  'passed': 143, 'raw_precontract_failures': 3, 'remaining_blocks': 'NOT_EXECUTED'}))
