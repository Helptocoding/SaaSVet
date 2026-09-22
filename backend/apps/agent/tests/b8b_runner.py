"""Exact B8B acceptance inventory and independently reproducible run evidence."""
import json
import os
import time
from collections import Counter
from pathlib import Path

from django.db import connection
from django.conf import settings
from django.test.runner import DiscoverRunner
from .b8a_runner import test_ids

ROOT = Path(__file__).resolve().parents[4]


def baseline_ids():
    previous = json.loads((ROOT / 'docs/evals/b8a-acceptance-results.json').read_text(encoding='utf-8'))
    ids = {case for run in previous['runs'].values() for case in run.get('test_ids', ())}
    if len(ids) != 1224:
        raise RuntimeError('B0-B8A inventory must contain 1224 unique tests')
    return ids


class CriticalB8BRunner(DiscoverRunner):
    def build_suite(self, test_labels=None, **kwargs):
        self.started = time.monotonic()
        suite = super().build_suite(test_labels, **kwargs)
        self.ids = sorted(test_ids(suite))
        if not self.ids or len(self.ids) != len(set(self.ids)):
            raise RuntimeError('Empty or duplicate acceptance inventory')
        if os.environ.get('B8B_SUITE') == 'baseline' and set(self.ids) != baseline_ids():
            raise RuntimeError('Incomplete B0-B8A inventory')
        return suite

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        if (result.testsRun != len(self.ids) or result.skipped or result.expectedFailures
                or result.unexpectedSuccesses):
            code = max(1, code)
        from .test_b8b_processes import PROCESS_RESULTS
        from .test_b8b_corpus import CORPUS_RESULTS
        data = {
            'tests': result.testsRun, 'test_ids': self.ids, 'failures': len(result.failures),
            'errors': len(result.errors), 'skips': len(result.skipped),
            'xfail': len(result.expectedFailures), 'unexpected_successes': len(result.unexpectedSuccesses),
            'failed_ids': [test.id() for test, _ in result.failures + result.errors],
            'seconds': time.monotonic() - self.started, 'exit_code': code,
            'modules': dict(Counter(x.rsplit('.', 2)[0] for x in self.ids)),
            'database_vendor': connection.vendor, 'processes': PROCESS_RESULTS,
            'fixture_password_hasher': settings.PASSWORD_HASHERS[0],
            'corpus': CORPUS_RESULTS,
            'effect_scope': 'real Appointment only in B8B suites; B8A retains fake adapter tests',
        }
        path = os.environ.get('B8B_RESULTS_PATH')
        if path:
            Path(path).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return code
