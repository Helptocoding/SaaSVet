"""Local disposable test runner; avoids Windows PowerShell launcher stalls."""
import argparse
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--suite', choices=('checks', 'targeted', 'regression', 'diagnostic', 'profile'), required=True)
parser.add_argument('--receipt', required=True)
parser.add_argument('--database')
parser.add_argument('--labels', default='targeted-labels.json')
parser.add_argument('--scenario', default='base')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
database = args.database or ('test_b8b_w1_mono_template' if args.suite == 'checks' else 'test_b8b_w1_mono_' + args.suite)
if not database.startswith('test_b8b_w1_mono_'):
    raise RuntimeError('Dedicated test database only')
env = dict(os.environ, SECRET_KEY='w1-mono-local-disposable-key-at-least-32-chars',
    DEBUG='False', ENVIRONMENT='dev', DISABLE_SENTRY='True', SENTRY_DSN='',
    REDIS_URL='', DISCORD_WEBHOOK_URL='',
    DATABASE_URL='postgresql://w1mono@127.0.0.1:35442/' + database)
for key in list(env):
    if key.startswith('E4_'):
        env.pop(key)  # No historical selector/latency/rate ablation overrides.
python = 'C:/Users/LAP/AppData/Local/Temp/vet-b8b-locked/Scripts/python.exe'
cmd = [python, '-X', 'utf8', '-m']
if args.suite in ('diagnostic', 'profile'):
    cmd += ['apps.agent.tests.w1_mono_diagnostic' if args.suite == 'diagnostic' else 'apps.agent.tests.b9e_profile',
        '--scenario', args.scenario, '--output', '../docs/evals/w1-mono/' + args.receipt + '.json']
else:
    cmd += ['apps.agent.tests.run_b9a_acceptance', '--suite', 'checks' if args.suite == 'checks' else 'targeted',
        '--database', database, '--ids-file', '../docs/evals/w1-mono/' + args.labels,
        '--output', '../docs/evals/w1-mono/' + args.receipt]
if args.suite in ('diagnostic', 'profile'):
    log = root/'docs/evals/w1-mono'/(args.receipt + '.log')
    with log.open('x', encoding='utf-8') as stream:
        code = subprocess.run(cmd, cwd=root/'backend', env=env,
            stdout=stream, stderr=subprocess.STDOUT).returncode
    print(args.receipt, 'exit_code', code)
else:
    code = subprocess.run(cmd, cwd=root/'backend', env=env).returncode
raise SystemExit(code)
