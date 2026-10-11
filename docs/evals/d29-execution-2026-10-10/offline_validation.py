"""Run each existing negative control once plus launch-order controls."""
import json
import sys
import unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(HERE), str(ROOT / 'docs/evals/d29-offline-preparation-2026-10-09')]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(['offline_checks', 'preparation_checks', 'test_launch_bridge', 'test_verifier_bridge', 'test_forecast_observer','test_native_ancestry','test_sealed_census','test_native_cleanup'])
    unique = {t.id(): t for t in flatten(suite)}
    number = 1
    while (HERE / f'offline-validation-{number:02}.json').exists():
        number += 1
    with (HERE / f'offline-validation-{number:02}.log').open('x',encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.TestSuite(unique.values()))
    receipt = dict(source_kind='INFRASTRUCTURE_CONTROLS_NOT_PHYSICAL_ACCREDITATION',
        tests=result.testsRun, unique_test_ids=list(unique),
        failures=[t.id() for t,e in result.failures], errors=[t.id() for t,e in result.errors],
        successful=result.wasSuccessful())
    (HERE / f'offline-validation-{number:02}.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='unique_test_ids'}))
    raise SystemExit(not result.wasSuccessful())
