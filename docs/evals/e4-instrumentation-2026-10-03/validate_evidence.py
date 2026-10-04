"""Reconstruct stored synthetic journals using the final offline reader."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'backend'))

from apps.agent.claim_diagnostic_report import read_journal, reconstruct, attach_waits
from apps.agent.tests.test_claim_diagnostic_reporting import ClaimDiagnosticReportingTests


def main():
    records = []
    for original in sorted((OUT/'artifacts').rglob('*-report.json')):
        prefix = original.name.removesuffix('-report.json')
        inputs = sorted(original.parent.glob(prefix+'-[0-9].jsonl'))
        journals = [read_journal(path) for path in inputs]
        result = reconstruct(journals)
        reverse = reconstruct(list(reversed(journals)))
        assert {(c['turn_work_id'],c['status']) for c in result['claims']} == {
            (c['turn_work_id'],c['status']) for c in reverse['claims']}
        waits = original.with_name(prefix+'-waits.jsonl')
        if waits.exists():
            samples = [json.loads(line) for line in waits.read_text().splitlines()]
            result = attach_waits(result, samples)
            assert result['waits']['lock_queries']
            assert result['waits']['exact_lock_wait_seconds'] is None
        assert result['classification'] == 'DIAGNOSTIC_ONLY' and not result['acceptance_run']
        text = '\n'.join(path.read_text() for path in inputs)
        for forbidden in ('TRACE_PRIVATE_PAYLOAD', '5512345678', 'SELECT ', 'INSERT INTO',
                          'TRACE_PRIVATE_ERROR', 'PRIVATE_COMMIT_ERROR', '"params":', '"sql":'):
            assert forbidden not in text
        output = original.with_name(prefix+'-reconstructed.json')
        output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        execution = OUT/(original.parent.name+'.exit.json')
        run_passed = execution.exists() and json.loads(execution.read_text())['exit_code'] == 0
        records.append(dict(input_report=str(original.relative_to(OUT)),
            verification_run_passed=run_passed,
            journals=len(journals), events=sum(map(len,journals)), claims=len(result['claims']),
            query_count=sum(j[-1]['query_count'] for j in journals),
            failed_writes=sum(j[-1]['failed_writes'] for j in journals),
            input_sha256={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
            lock_queries=len(result.get('waits',{}).get('lock_queries',[]))))
    assert records
    with (OUT/'reporting-unit.log').open('w', encoding='utf-8') as stream:
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(ClaimDiagnosticReportingTests)
        test_result = unittest.TextTestRunner(stream=stream, verbosity=2).run(tests)
    assert test_result.wasSuccessful()
    result = dict(classification='DIAGNOSTIC_ONLY', offline_reconstruction='PASS',
        reporting_unit_tests=test_result.testsRun, evidence=records,
        historical_causality='NOT_INFERRED', privacy_forbidden_patterns_found=0)
    (OUT/'evidence-validation.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(evidence_groups=len(records), total_events=sum(r['events'] for r in records),
        passed_run_groups=sum(r['verification_run_passed'] for r in records),
        passed_run_events=sum(r['events'] for r in records if r['verification_run_passed']),
        failed_writes=sum(r['failed_writes'] for r in records), reporting_tests=test_result.testsRun)))


if __name__ == '__main__':
    main()
