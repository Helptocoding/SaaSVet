"""B9A runner: explicit local PostgreSQL, per-ID receipts, no production IO."""
import argparse
import json
import os
import runpy
import sys
from pathlib import Path


def baseline_ids():
    root = Path(__file__).resolve().parents[4]
    data = json.loads((root / 'docs/evals/b8e-acceptance-results.json').read_text(encoding='utf-8'))
    ids = {case for run in data['runs'].values() for field in ('test_ids', 'passed_ids')
           for case in run.get(field, [])}
    if len(ids) != 2097:
        raise RuntimeError(f'Expected exact 2097 B8E IDs, found {len(ids)}')
    return sorted(ids)


def main():
    # Set before Django imports settings/.env. Test evidence never goes to a
    # remote telemetry/cache service, including in inherited subprocesses.
    os.environ['DISABLE_SENTRY'] = 'True'
    os.environ['SENTRY_DSN'] = ''
    os.environ['REDIS_URL'] = ''
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('b9a', 'processes', 'historical', 'targeted', 'checks'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ids-file', type=Path)
    parser.add_argument('--database', default='test_b8b_b9a_acceptance')
    args = parser.parse_args()
    # Reuse B8E's safety checks, journal and recovery mechanism. Connection URL
    # is supplied by the operator and must pass its local PostgreSQL check.
    ids = (baseline_ids() if args.suite == 'historical' else
           json.loads(args.ids_file.read_text(encoding='utf-8')) if args.suite == 'targeted' else
           ['apps.agent.tests.test_b9a_processes'] if args.suite == 'processes' else
           ['apps.agent.tests.test_b9a_e2e', 'apps.agent.tests.test_b9a_commands'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    selected = args.output.with_suffix('.selected.json')
    selected.write_text(json.dumps(ids, indent=2), encoding='utf-8')
    sys.argv = ['run_b8e_acceptance', '--suite', 'checks' if args.suite == 'checks' else 'targeted',
        '--database', args.database, '--output', str(args.output), '--ids-file', str(selected)]
    runpy.run_module('apps.agent.tests.run_b8e_acceptance', run_name='__main__')


if __name__ == '__main__':
    main()
