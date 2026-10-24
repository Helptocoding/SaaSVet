"""Receipt-only Django runner; persist assertion tracebacks as failures occur."""
import json
import os
from pathlib import Path
import sys
import time
import traceback
import unittest

HERE = Path(__file__).resolve().parent
assembly = json.loads((HERE/'assembly.json').read_text())
sys.path.insert(0, str(Path(assembly['tree'])/'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.test.runner import DiscoverRunner


def selected():
    return json.loads((HERE/'diagnostic-selected.json').read_text())


def ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from ids(test)
        else:
            yield test.id()


class DiagnosticRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        self.selected_ids = sorted(ids(suite))
        assert self.selected_ids == sorted(selected())
        self.started = time.monotonic()
        return suite

    def get_resultclass(self):
        base = super().get_resultclass() or unittest.TextTestResult
        class Result(base):
            def record(self, test, outcome, err=None, reason=None):
                row = {'id': test.id(), 'outcome': outcome, 'reason': reason,
                       'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'traceback': ''.join(traceback.format_exception(*err)) if err else None}
                with (HERE/'diagnostic.ids.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            def addSuccess(self, test):
                super().addSuccess(test); self.record(test, 'PASS')
            def addFailure(self, test, err):
                super().addFailure(test, err); self.record(test, 'FAIL', err)
            def addError(self, test, err):
                super().addError(test, err); self.record(test, 'ERROR', err)
            def addSkip(self, test, reason):
                super().addSkip(test, reason); self.record(test, 'SKIP', reason=reason)
            def addExpectedFailure(self, test, err):
                super().addExpectedFailure(test, err); self.record(test, 'XFAIL', err)
            def addUnexpectedSuccess(self, test):
                super().addUnexpectedSuccess(test); self.record(test, 'XPASS')
            def addSubTest(self, test, subtest, err):
                super().addSubTest(test, subtest, err)
                if err:
                    self.record(test, 'FAIL' if issubclass(err[0], test.failureException) else 'ERROR', err, subtest.id())
        return Result

    def suite_result(self, suite, result, **kwargs):
        code = super().suite_result(suite, result, **kwargs)
        (HERE/'diagnostic.results.json').write_text(json.dumps({
            'candidate_sha': assembly['candidate_sha'], 'test_ids': self.selected_ids,
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skips': len(result.skipped), 'xfail': len(result.expectedFailures),
            'xpass': len(result.unexpectedSuccesses), 'exit_code': code,
            'seconds': time.monotonic() - self.started, 'test_invocations': 1,
            'acceptance_gate': False}, indent=2) + '\n', encoding='utf-8')
        return code


if __name__ == '__main__':
    from django.conf import settings
    if '--discover' in sys.argv:
        runner = DiscoverRunner(verbosity=0, interactive=False, parallel=1)
        found = sorted(ids(runner.build_suite(selected())))
        assert found == sorted(selected()) and len(found) == 11 and len(set(found)) == 11
        (HERE/'discovery.json').write_text(json.dumps({'state': 'PASS', 'test_ids': found,
             'tests_executed': False}, indent=2) + '\n', encoding='utf-8')
        print('EXACT_11_IDS_DISCOVERED')
    else:
        (HERE/'diagnostic.ids.jsonl').touch(exist_ok=False)
        settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_b9i_diagnostic_11'
        from django.core.management import call_command
        call_command('test', *selected(), interactive=False, verbosity=2, parallel=1,
                     testrunner='diagnostic_suite.DiagnosticRunner')
