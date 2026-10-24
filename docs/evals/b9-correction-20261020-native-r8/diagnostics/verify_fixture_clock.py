"""One development check of the corrected fixture; never replace the full gate."""
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from native_support import EVIDENCE, TREE, SHA, GIB, environment, integrity, resources

TEST_ID = 'apps.notifications.tests.test_notifications.DerivedFeedTests.test_upcoming_window'


def ids(suite):
    for item in suite:
        if hasattr(item, 'id'):
            yield item.id()
        else:
            yield from ids(item)


def main():
    output = HERE / 'diagnostics/fixture-clock-focused-check.json'
    assert not output.exists() and not (HERE / 'evaluation-seal.json').exists()
    assert not (HERE / 'invocation-formal.json').exists()
    assert SHA == '68dffd746793700071f577a58528b0f9636930db'
    assert json.loads((HERE / 'launcher-validation.json').read_text())['state'] == 'PASS'
    before = resources()
    assert before['physical_available'] >= 2 * GIB and before['disk_available'] >= GIB
    integrity('before-development-fixture-check')
    os.environ.update(environment())
    sys.path.insert(0, str(TREE / 'backend'))
    import django
    django.setup()
    from django.conf import settings
    from django.test.runner import DiscoverRunner
    settings.DATABASES['default']['TEST'] = dict(settings.DATABASES['default'].get('TEST') or {},
                                               NAME='test_b9i_fixture_clock')

    class ObservedRunner(DiscoverRunner):
        def run_suite(self, suite, **kwargs):
            self.observed_ids = list(ids(suite))
            self.observed_result = super().run_suite(suite, **kwargs)
            return self.observed_result

    runner = ObservedRunner(verbosity=2, interactive=False)
    started = time.monotonic()
    code = runner.run_tests([TEST_ID])
    result = runner.observed_result
    assert runner.observed_ids == [TEST_ID] and result.testsRun == 1
    integrity('after-development-fixture-check')
    passed = code == 0 and result.wasSuccessful() and not result.skipped
    data = {'state': 'PASS' if passed else 'NONPASS', 'candidate_tree': SHA,
        'test_ids': runner.observed_ids, 'tests': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'skips': result.skipped, 'exit_code': code, 'seconds': time.monotonic() - started,
        'development_verification_only': True, 'formal_gate_credit': False,
        'complete_general_gate_still_required': 3213,
        'frozen_clock_from_authorized_source': '2026-10-17T12:00:00+00:00',
        'test_assertions_and_constraint_changed': False,
        'resources_before': before, 'resources_after': resources()}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps(data), flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
