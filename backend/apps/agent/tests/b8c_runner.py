"""Exact baseline inventory and per-test evidence for B8C acceptance."""
import json
import os
import time
import unittest
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.test.runner import DiscoverRunner
from .b8a_runner import test_ids

ROOT = Path(__file__).resolve().parents[4]


class B8CResult(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        with Path(os.environ['B8C_RESULTS_PATH']).with_suffix('.passed.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps({'test_id': test.id(), 'status': 'ok'}) + '\n')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.writeln(self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.writeln(self._exc_info_to_string(err, test))


def baseline_ids():
    previous = json.loads((ROOT / 'docs/evals/b8b-acceptance-resultsjson').read_text(encoding='utf-8'))
    ids = {case for run in previous['runs'].values() for case in run['test_ids']}
    if len(ids) != 1462:
        raise RuntimeError('B0-B8B / Agenda / Dashboard baseline must have 1462 unique IDs')
    return ids


class B8CRunner(DiscoverRunner):
    def get_resultclass(self):
        return B8CResult

    def build_suite(self, test_labels=None, **kwargs):
        self.started = time.monotonic()
        suite = super().build_suite(test_labels, **kwargs)
        self.ids = sorted(test_ids(suite))
        Path(os.environ['B8C_RESULTS_PATH']).with_suffix('.passed.jsonl').write_text('', encoding='utf-8')
        Path(os.environ['B8C_RESULTS_PATH']).with_suffix('.processes.jsonl').write_text('', encoding='utf-8')
        if not self.ids or len(self.ids) != len(set(self.ids)):
            raise RuntimeError('Invalid acceptance inventory')
        if os.environ.get('B8C_SUITE') == 'baseline' and set(self.ids) != baseline_ids():
            raise RuntimeError('Incomplete baseline inventory')
        return suite

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        if result.testsRun != len(self.ids) or result.skipped or result.expectedFailures or result.unexpectedSuccesses:
            code = max(1, code)
        from .test_b8c_processes import PROCESS_RESULTS
        from .test_b8c_corpus import CORPUS_RESULTS
        data = {'tests': result.testsRun, 'test_ids': self.ids,
            'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
            'xfail': len(result.expectedFailures), 'unexpected_successes': len(result.unexpectedSuccesses),
            'failed_ids': [t.id() for t, _ in result.failures + result.errors],
            'seconds': time.monotonic() - self.started, 'exit_code': code,
            'database_vendor': connection.vendor, 'processes': PROCESS_RESULTS, 'corpus': CORPUS_RESULTS,
            'fixture_password_hasher': settings.PASSWORD_HASHERS[0]}
        Path(os.environ['B8C_RESULTS_PATH']).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        return code
