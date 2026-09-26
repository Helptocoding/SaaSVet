"""Run the application harness in a separate, isolated test database.

These commands reuse Django's test lifecycle because B3/B4 require committed
fixtures. A rollback around planner calls cannot exercise that lifecycle.
Commercial-model promotion/evaluation remains a separate B9 acceptance gate.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.core.management.base import CommandError
from django.db import connection


def add_arguments(parser):
    parser.add_argument('--application-e2e', action='store_true',
        help='Run deterministic HTTP/worker/sender scripts on isolated PostgreSQL')
    parser.add_argument('--e2e-database', help='Explicit test_b8b_b9a_* database')
    parser.add_argument('--e2e-output', type=Path, help='Acceptance artifact prefix')


def run(command, options, *, conversations=False):
    """Return True only if the E2E mode was selected; never silently skip."""
    if not options.get('application_e2e'):
        return False
    database, output = options.get('e2e_database'), options.get('e2e_output')
    if not database or not database.startswith('test_b8b_b9a_') or output is None:
        raise CommandError('E2E requires --e2e-database test_b8b_b9a_* and --e2e-output')
    if (connection.vendor != 'postgresql' or connection.in_atomic_block or
            connection.settings_dict['HOST'] not in ('127.0.0.1', 'localhost')):
        raise CommandError('E2E requires local PostgreSQL outside a transaction')
    if not os.environ.get('DATABASE_URL'):
        raise CommandError('E2E requires an explicit local DATABASE_URL')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if any(output.with_suffix(suffix).exists() for suffix in ('.results.json', '.log', '.exit.json')):
        raise CommandError('Use a fresh output prefix; prior acceptance evidence must be preserved')
    labels = ['apps.agent.tests.test_b9a_e2e.B9AE2ETests'] if conversations else [
        'apps.agent.tests.test_b9a_e2e.B9AE2ETests.test_e2e_01_public_read_queued_accepted_delivered_read_are_distinct',
        'apps.agent.tests.test_b9a_e2e.B9AE2ETests.test_e2e_02_personal_read_uses_authenticated_domain_http',
        'apps.agent.tests.test_b9a_e2e.B9AE2ETests.test_e2e_03_duplicate_signed_http_is_one_message_and_work',
    ]
    selected = output.with_suffix('.command-selection.json')
    selected.write_text(json.dumps(labels, indent=2), encoding='utf-8')
    env = dict(os.environ, DISABLE_SENTRY='True', SENTRY_DSN='', REDIS_URL='', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m',
        'apps.agent.tests.run_b9a_acceptance', '--suite', 'targeted',
        '--ids-file', str(selected), '--database', database, '--output', str(output)],
        cwd=Path(__file__).resolve().parents[3], env=env, check=False)
    receipt_path = output.with_suffix('.results.json')
    if result.returncode or not receipt_path.is_file():
        raise CommandError('E2E failed or interrupted; inspect ' + str(output.with_suffix('.log')))
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if (receipt['exit_code'] or not receipt['tests'] or receipt['skips'] or
            receipt['errors'] or receipt['failures'] or receipt['xfail']):
        raise CommandError('E2E incomplete or failed; no acceptance')
    report = {'scope': 'application_e2e', 'external_boundaries': 'deterministic',
        'meta_delivery': 'simulated_signal_only', 'beta_acceptance': 'PENDING',
        'tests': receipt['tests'], 'receipt': str(receipt_path)}
    command.stdout.write(json.dumps(report, ensure_ascii=False))
    return True
