"""Fail-closed B8A evidence: exact inventory, no skips/xfail/duplicate counts."""
import json
import os
import time
import unittest
from collections import Counter
from pathlib import Path
from django.test.runner import DiscoverRunner

ROOT = Path(__file__).resolve().parents[4]


def baseline_ids():
    previous = json.loads((ROOT / 'docs/evals/b7b-acceptance-results.json').read_text(encoding='utf-8'))
    ids = {case for run in previous['runs'].values() for case in run.get('test_ids', ())}
    if len(ids) != 1135:
        raise RuntimeError('B7B baseline inventory must contain exactly 1135 unique tests')
    return ids


def test_ids(suite):
    for item in suite:
        if hasattr(item, 'id'):
            yield item.id()
        else:
            yield from test_ids(item)


class CriticalB8ARunner(DiscoverRunner):
    def build_suite(self, test_labels=None, **kwargs):
        self.started = time.monotonic()
        suite = super().build_suite(test_labels, **kwargs)
        self.ids = sorted(test_ids(suite))
        if os.environ.get('B8A_SUITE') == 'baseline':
            required = baseline_ids()
        else:
            required = set(test_ids(unittest.defaultTestLoader.loadTestsFromNames([
                'apps.agent.tests.test_operation_execution', 'apps.agent.tests.test_b8a_processes',
                'apps.agent.tests.test_b8a_corpus'])))
        if set(self.ids) != required or len(self.ids) != len(set(self.ids)):
            raise RuntimeError('Incomplete/duplicate/unexpected B8A inventory: ' +
                               repr(sorted(required.symmetric_difference(self.ids))))
        return suite

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        if (result.testsRun != len(self.ids) or not self.ids or result.skipped
                or result.expectedFailures or result.unexpectedSuccesses):
            code = max(1, code)
        from .test_b8a_corpus import CORPUS_RESULTS
        data = {'tests': result.testsRun, 'test_ids': self.ids,
            'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
            'xfail': len(result.expectedFailures), 'unexpected_successes': len(result.unexpectedSuccesses),
            'failed_ids': [test.id() for test, _ in result.failures + result.errors],
            'seconds': time.monotonic() - self.started, 'exit_code': code,
            'modules': dict(Counter(x.rsplit('.', 2)[0] for x in self.ids)),
            'corpus': CORPUS_RESULTS,
            'unauthorized_business_effects': sum(x['unauthorized_business_effects'] for x in CORPUS_RESULTS),
            'effect_scope': 'isolated fake SQL domain only; no real B8B-B8E adapter'}
        path = os.environ.get('B8A_RESULTS_PATH')
        if path:
            Path(path).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return code
