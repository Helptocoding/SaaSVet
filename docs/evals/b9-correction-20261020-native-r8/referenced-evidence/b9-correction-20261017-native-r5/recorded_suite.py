"""Receipt-only subclass adapter; preserves the candidate's critical runners."""
import json
import os
from pathlib import Path
import sys
import time
import traceback
import unittest

EVIDENCE = Path(__file__).resolve().parent
assembly = json.loads((EVIDENCE / 'assembly.json').read_text(encoding='utf-8'))
TREE = Path(assembly['tree'])
sys.path.insert(0, str(TREE / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.test.runner import DiscoverRunner
from apps.agent.tests.harness import CriticalB0Runner, CriticalB3Runner, CriticalB4Runner, CriticalB5Runner


class RecordingMixin:
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        self.started = time.monotonic()
        def ids(items):
            for test in items:
                if isinstance(test, unittest.TestSuite):
                    yield from ids(test)
                else:
                    yield test.id()
        self.ids = sorted(ids(suite))
        expected = json.loads((EVIDENCE / (os.environ['B9I_SUITE'] + '-selected.json')).read_text(encoding='utf-8'))
        if self.ids != expected:
            raise RuntimeError('Discovery differs from frozen inventory')
        return suite

    def get_resultclass(self):
        base = super().get_resultclass() or unittest.TextTestResult
        class RecordedResult(base):
            def record(self, test, outcome, reason=None, err=None):
                with Path(os.environ['B9I_ID_JOURNAL']).open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(json.dumps({'id': test.id(), 'outcome': outcome, 'reason': reason,
                        'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'traceback': ''.join(traceback.format_exception(*err)) if err else None}) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            def addSuccess(self, test):
                super().addSuccess(test)
                self.record(test, 'PASS')
            def addFailure(self, test, err):
                super().addFailure(test, err)
                self.record(test, 'FAIL', err=err)
            def addError(self, test, err):
                super().addError(test, err)
                self.record(test, 'ERROR', err=err)
            def addSkip(self, test, reason):
                super().addSkip(test, reason)
                self.record(test, 'SKIP', reason)
            def addExpectedFailure(self, test, err):
                super().addExpectedFailure(test, err)
                self.record(test, 'XFAIL')
            def addUnexpectedSuccess(self, test):
                super().addUnexpectedSuccess(test)
                self.record(test, 'XPASS')
            def addSubTest(self, test, subtest, err):
                super().addSubTest(test, subtest, err)
                if err is not None:
                    self.record(test, 'FAIL' if issubclass(err[0], test.failureException) else 'ERROR', subtest.id(), err)
        return RecordedResult

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        receipt = {'candidate_sha': assembly['candidate_sha'], 'test_ids': self.ids,
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skips': [{'id': t.id(), 'reason': reason} for t, reason in result.skipped],
            'xfail': len(result.expectedFailures), 'xpass': len(result.unexpectedSuccesses),
            'failed_ids': [t.id() for t, _ in result.failures + result.errors],
            'exit_code': code, 'seconds': time.monotonic() - self.started,
            'orchestration': 'local sequential suite; independent process tests unchanged'}
        Path(os.environ['B9I_SUITE_RECEIPT']).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n')
        return code


class RecordedB0Runner(RecordingMixin, CriticalB0Runner):
    pass


class RecordedB3Runner(RecordingMixin, CriticalB3Runner):
    pass


class RecordedB4Runner(RecordingMixin, CriticalB4Runner):
    pass


class RecordedB5Runner(RecordingMixin, CriticalB5Runner):
    pass


class RecordedFullRunner(RecordingMixin, DiscoverRunner):
    pass


if __name__ == '__main__':
    from django.conf import settings
    from django.core.management import call_command
    label, database = sys.argv[1:3]
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = database
    Path(os.environ['B9I_ID_JOURNAL']).touch(exist_ok=False)
    labels = [] if label == 'full' else json.loads((EVIDENCE / (label + '-selected.json')).read_text(encoding='utf-8'))
    if label.startswith('full-'):
        from full_partition import validate_partition
        group = next(row for row in validate_partition()['groups'] if row['label'] == label)
        assert database == group['database']
        runner = RecordedFullRunner
    else:
        runner = {'b0': RecordedB0Runner, 'b3': RecordedB3Runner,
                  'b4': RecordedB4Runner, 'b5': RecordedB5Runner, 'full': RecordedFullRunner}[label]
    call_command('test', *labels, interactive=False, verbosity=2, parallel=1,
                 testrunner='recorded_suite.' + runner.__name__)
