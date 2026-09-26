"""Per-ID durable acceptance evidence, including interrupted-run recovery."""
import json
import hashlib
import os
import time
import unittest
from pathlib import Path
from django.test.runner import DiscoverRunner
from .b8a_runner import test_ids

ROOT = Path(__file__).resolve().parents[4]


def baseline_ids():
    data = json.loads((ROOT/'docs/evals/b8d-acceptance-results.json').read_text(encoding='utf-8'))
    ids = {case for run in data['runs'].values() for case in run.get('test_ids', [])}
    ids.update(case for run in data['runs'].values() for case in run.get('passed_ids', []))
    if len(ids) != 1726:
        raise RuntimeError(f'Incomplete B0–B8D baseline: {len(ids)}')
    return ids


class B8EResult(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        with Path(os.environ['B8E_RESULTS_PATH']).with_suffix('.passed.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps({'test_id': test.id(), 'status': 'ok'})+'\n')

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.writeln(self._exc_info_to_string(err, test))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.writeln(self._exc_info_to_string(err, test))


class B8ERunner(DiscoverRunner):
    def get_resultclass(self):
        return B8EResult

    def build_suite(self, test_labels=None, **kwargs):
        self.started = time.monotonic()
        suite = super().build_suite(test_labels, **kwargs)
        self.ids = sorted(test_ids(suite))
        path = Path(os.environ['B8E_RESULTS_PATH'])
        path.with_suffix('.passed.jsonl').write_text('', encoding='utf-8')
        path.with_suffix('.inventory.json').write_text(json.dumps(self.ids, indent=2), encoding='utf-8')
        sources = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for app in ('agent', 'patients') for p in (ROOT/'backend/apps'/app).rglob('*.py')}
        path.with_suffix('.sources.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
        if not self.ids or len(self.ids) != len(set(self.ids)):
            raise RuntimeError('Invalid acceptance inventory')
        return suite

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        if result.testsRun != len(self.ids) or result.skipped or result.expectedFailures or result.unexpectedSuccesses:
            code = max(1, code)
        data = {'tests': result.testsRun, 'test_ids': self.ids, 'failures': len(result.failures),
            'errors': len(result.errors), 'skips': len(result.skipped), 'xfail': len(result.expectedFailures),
            'failed_ids': [t.id() for t, _ in result.failures+result.errors],
            'seconds': time.monotonic()-self.started, 'exit_code': code}
        Path(os.environ['B8E_RESULTS_PATH']).write_text(json.dumps(data, indent=2), encoding='utf-8')
        return code
