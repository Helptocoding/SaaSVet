"""Require complete per-ID coverage, final equivalence and isolated DB cleanup."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'backend'))
from apps.agent.tests.test_claim_diagnostic_reporting import ClaimDiagnosticReportingTests


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def passed(tag):
    return {json.loads(line)['test_id'] for line in
            (OUT/(tag+'.results.passed.jsonl')).read_text().splitlines()}


def complete(tag):
    receipt = load(tag+'.results.json')
    assert load(tag+'.exit.json')['exit_code'] == 0
    assert all(receipt[key] == 0 for key in ('failures','errors','skips','xfail'))
    expected = set(receipt['test_ids'])
    assert expected == passed(tag)
    return expected


def main():
    integrity = load('source-integrity.json')
    assert not integrity['mismatches'] and integrity['selector_ast_identical']
    assert all(integrity['functional_ast_after_removing_named_hooks'].values())
    regression_tags = ['regression-e4','regression-durable','regression-b9']
    expected, successful, contributions = set(), set(), {}
    for tag in regression_tags:
        inventory = set(load(tag+'.results.inventory.json'))
        successes = passed(tag)
        assert successes <= inventory
        expected.update(inventory)
        successful.update(successes)
        contributions[tag] = dict(selected=len(inventory), successful_before_interruption=len(successes),
                                  complete_run=False)
    recovered = complete('recovery-regression')
    successful.update(recovered)
    assert expected == successful and len(expected) == 195
    contributions['recovery-regression'] = dict(selected=len(recovered), successful=len(recovered),
                                                complete_run=True)
    diagnostic_tags = ['targeted-3','equivalence-2','equivalence-final','savepoint-final']
    diagnostic_ids = set().union(*(complete(tag) for tag in diagnostic_tags))
    offline_ids = {ClaimDiagnosticReportingTests.__module__+'.ClaimDiagnosticReportingTests.'+name
                   for name in unittest.defaultTestLoader.getTestCaseNames(ClaimDiagnosticReportingTests)}
    diagnostic_ids.update(offline_ids)
    assert len(diagnostic_ids) == 21
    evidence = load('evidence-validation.json')
    assert evidence['offline_reconstruction'] == 'PASS'
    assert evidence['reporting_unit_tests'] == 5
    assert evidence['privacy_forbidden_patterns_found'] == 0
    assert all(row['failed_writes'] == 0 for row in evidence['evidence'])
    equivalence = {}
    for name in ('concurrency','lock-wait','blocked-llm','rollback'):
        path = OUT/'artifacts/equivalence-final'/(name+'-equivalence.json')
        record = json.loads(path.read_text())
        assert record['on_off_equal'] and record['on'] == record['off']
        equivalence[str(path.relative_to(OUT)).replace('\\','/')] = True
    cleanup = load('cleanup.json')
    assert cleanup['status'] == 'STOPPED' and cleanup['port_closed']
    assert cleanup['clients'] == cleanup['waiting_locks'] == 0
    assert load('checks-1.exit.json')['exit_code'] == 0
    runtime = sorted([*integrity['modified_existing_runtime'],
        'backend/apps/agent/claim_diagnostics.py',
        'backend/apps/agent/claim_diagnostic_report.py',
        'backend/apps/agent/claim_diagnostic_waits.py'])
    hashes = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in runtime}
    final_test_sources = load('savepoint-final.results.sources.json')
    assert all(final_test_sources[name] == digest for name,digest in hashes.items())
    branch = subprocess.check_output(['rtk','proxy','git','branch','--show-current'], cwd=ROOT).decode().strip()
    assert branch == 'codex/e4-capacity-scheduling'
    receipt = dict(status='INSTRUMENTATION_READY / ROOT_CAUSE_INVESTIGATION_READY',
        baseline=integrity['baseline'], branch=branch, classification='DIAGNOSTIC_ONLY',
        profile_executed=False, historical_turnwork_86_causality='NOT_INFERRED',
        historical_B9E='FAIL', historical_PROFILE_BETA_1='FAIL', B9='IN_PROGRESS',
        later_2026_10_02_evaluation='PRESERVED_WITHOUT_RECLASSIFICATION', threshold_seconds=10,
        regression_unique_tests=195, diagnostic_unique_tests=21, total_unique_tests=216,
        regression_contributions=contributions, successful_test_ids=sorted(successful|diagnostic_ids),
        completed_diagnostic_runs=diagnostic_tags, final_runtime_test_source='savepoint-final.results.sources.json',
        verification_method='Composite per-ID evidence; no claim of one final 216-test execution.',
        on_off_process_and_rollback_receipts=equivalence,
        protected_source_count=integrity['protected_files'], selector_ast_identical=True,
        functional_ast_after_removing_named_hooks=integrity['functional_ast_after_removing_named_hooks'],
        runtime_sha256=hashes, cleanup=cleanup,
        valid_journal_groups_in_passed_runs=sum(r['verification_run_passed'] for r in evidence['evidence']),
        valid_events_in_passed_runs=sum(r['events'] for r in evidence['evidence'] if r['verification_run_passed']),
        limitations=['Optional capture perturbs timing; equivalence is functional, not temporal.',
                    'Waits are discrete observations, not exact durations or proof of absence.',
                    'DB-to-monotonic bounds assume no clock step; created_at is not ingress commit.',
                    'No fsync per event; interrupted or failed journals must not establish causality.'])
    (OUT/'closure.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:receipt[key] for key in ('status','baseline','regression_unique_tests',
        'diagnostic_unique_tests','total_unique_tests','valid_journal_groups_in_passed_runs',
        'valid_events_in_passed_runs')}))


if __name__ == '__main__':
    main()
