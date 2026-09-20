"""Fail-closed B7B acceptance inventory and machine-readable actual results."""
import json
import os
from collections import Counter
from pathlib import Path
from django.test.runner import DiscoverRunner
from .harness import CriticalB0Runner


class CriticalB7BRunner(CriticalB0Runner):
    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)
        def ids(items):
            for item in items:
                if hasattr(item, 'id'):
                    yield item.id()
                else:
                    yield from ids(item)
        self.test_ids = sorted(ids(suite))
        self._planned_count = suite.countTestCases()
        from .test_b7b_corpus import CORPUS
        required = {'apps.agent.tests.test_b7b_corpus.B7BCorpusTests.test_corpus_' + c['id']
                    for c in CORPUS['cases']}
        required.update('apps.agent.tests.' + suffix for suffix in (
            'test_operation_consent.OperationConsentTests.test_emit_06_verified_emission_then_exact_token_authorizes_once',
            'test_operation_consent.OperationConsentTests.test_int_01_authorized_does_not_open_any_business_write',
            'test_operation_consent.OperationConsentTests.test_mode_01_to_05_contextual_declaration_never_authorizes',
            'test_operation_consent.OperationConsentTests.test_webhook_verified_reconciliation_then_new_response_is_eligible',
            'test_b7b_processes.B7BProcessTests.test_fi04_crash_after_validation_before_authorization_commit',
            'test_b7b_processes.B7BProcessTests.test_fi06_correction_wins_against_concurrent_authorization',
            'test_b7b_processes.B7BProcessTests.test_fi07_takeover_wins_against_concurrent_authorization',
            'test_b7b_processes.B7BProcessTests.test_fi08_concurrent_duplicate_one_decision',
            'test_b7b_processes.B7BProcessTests.test_fi10_database_error_rolls_back_evidence_and_state',
            'test_b7b_migration.B7BMigrationTests.test_no_synthetic_legacy_consent_or_emission'))
        if any('.test_b7a_' in name for name in self.test_ids):
            baseline = json.loads((Path(__file__).resolve().parents[4] /
                'docs/evals/b7a-acceptance-results.json').read_text(encoding='utf-8'))
            required.update(baseline['runs']['b7a_combined_final']['test_ids'])
        missing = required - set(self.test_ids)
        if missing or len(self.test_ids) != len(set(self.test_ids)):
            raise RuntimeError('B7B missing/duplicate acceptance inventory: ' + repr(sorted(missing)))
        return suite

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        from .test_b7b_corpus import CORPUS_RESULTS
        path = os.environ.get('B7B_RESULTS_PATH')
        if path:
            data = {'tests': result.testsRun, 'test_ids': self.test_ids,
                'failures': len(result.failures), 'errors': len(result.errors),
                'skips': len(result.skipped), 'xfail': len(result.expectedFailures),
                'unexpected_successes': len(result.unexpectedSuccesses),
                'failed_ids': [test.id() for test, _ in result.failures + result.errors],
                'modules': dict(Counter(x.rsplit('.', 2)[0] for x in self.test_ids)),
                'corpus': CORPUS_RESULTS, 'false_authorizations': sum(x['false_authorization'] for x in CORPUS_RESULTS),
                'exit_code': code}
            Path(path).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return code
