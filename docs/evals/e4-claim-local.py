"""Own disposable PG16 cluster, guarded names; never uses production config."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import shutil

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/evals/e4-claim'
TEMP = Path(os.environ['TEMP']).resolve()
DATA = TEMP / 'vet-e4-claim-pg16-data'
PG = TEMP / 'vet-b8b-pg16-bin/pgsql/bin'
PYTHON = TEMP / 'vet-b8b-locked/Scripts/python.exe'
PORT = 35443
PREFIX = 'test_b8b_e4claim_'
ENV = dict(os.environ, SECRET_KEY='e4-claim-disposable-local-test-key-32-chars',
    DEBUG='False', ENVIRONMENT='dev', DISABLE_SENTRY='True', SENTRY_DSN='',
    REDIS_URL='', DISCORD_WEBHOOK_URL='', HEALTHCHECK_AGENT_WORKER_URL='',
    HEALTHCHECK_AGENT_SENDER_URL='')
for key in list(ENV):
    if key.startswith('E4_'):
        ENV.pop(key)


def uri(database):
    return f'postgresql://e4claim@127.0.0.1:{PORT}/{database}'


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def initialize():
    assert DATA.resolve().parent == TEMP and DATA.name == 'vet-e4-claim-pg16-data'
    assert not DATA.exists(), 'Refuse existing cluster'
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', PORT)) != 0, 'Port already occupied'
    OUT.mkdir(exist_ok=True)
    run([str(PG/'initdb.exe'), '-D', str(DATA), '-U', 'e4claim', '-A', 'trust',
         '--encoding=UTF8', '--locale=C'], stdout=subprocess.DEVNULL)
    run([str(PG/'pg_ctl.exe'), '-D', str(DATA), '-l', str(TEMP/'vet-e4-claim-pg16.log'),
         '-o', f'-p {PORT} -h 127.0.0.1', '-w', 'start'])
    with psycopg.connect(uri('postgres'), autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(PREFIX+'template')))
    run([str(PYTHON), '-X', 'utf8', 'manage.py', 'migrate', '--noinput'], cwd=ROOT/'backend',
        env=dict(ENV, DATABASE_URL=uri(PREFIX+'template')), stdout=subprocess.DEVNULL)
    print('INITIALIZED isolated PG16', PORT, flush=True)


def diagnostic(label, scenario, ablation=None):
    database = PREFIX + label.replace('-', '_')
    with psycopg.connect(uri('postgres'), autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(database), sql.Identifier(PREFIX+'template')))
    env = dict(ENV, DATABASE_URL=uri(database))
    if ablation:
        env.update(E4_MEASURE_SECONDS='120')
        env.update({'no-noisy': dict(E4_NO_NOISY='1'),
                    'no-pause': dict(E4_POLL_SECONDS='0'),
                    'batch-three': dict(E4_BATCH='3'),
                    'fast-provider': dict(E4_LLM_SECONDS='.001'),
                    'bounded-yield': dict(E4_CLAIM_CANDIDATE='bounded-yield')}[ablation])
    with (OUT/(label+'.log')).open('x', encoding='utf-8') as log:
        result = subprocess.run([str(PYTHON), '-X', 'utf8', '-m', 'apps.agent.tests.e4_claim_diagnostic',
            '--scenario', scenario, '--output', str(OUT/(label+'.json'))], cwd=ROOT/'backend', env=env,
            stdout=log, stderr=subprocess.STDOUT)
    print(label, 'exit', result.returncode, flush=True)
    return result.returncode


def matrix():
    for ablation in ('no-noisy', 'no-pause', 'batch-three', 'fast-provider'):
        label = 'ablation-' + ablation
        code = diagnostic(label, 'base', ablation)
        if code:
            raise SystemExit(code)
        run([str(PYTHON), '-X', 'utf8', str(ROOT/'docs/evals/e4-claim-analyze.py'), str(OUT/(label+'.json'))],
            stdout=subprocess.DEVNULL)


def prepare_tests():
    os.environ.update(ENV, DJANGO_SETTINGS_MODULE='config.settings', DATABASE_URL=uri(PREFIX+'template'))
    sys.path.insert(0, str(ROOT/'backend'))
    import django
    django.setup()
    ids = set(json.loads((ROOT/'docs/evals/w1-mono/regression.results.inventory.json').read_text()))
    labels = ['apps.agent.tests.test_e4_selection', 'apps.agent.tests.test_e4_processes',
        'apps.agent.tests.test_e4_claim_yield', 'apps.agent.tests.test_e4_yield_processes',
        'apps.agent.tests.test_w1_monotonic', 'apps.agent.tests.test_w1_mono_processes',
        'apps.agent.tests.test_w1_mono_causal', 'apps.agent.tests.test_planner',
        'apps.agent.tests.test_b4_sender', 'apps.agent.tests.test_b4_processes',
        'apps.agent.tests.test_b9a_commands', 'apps.agent.tests.test_b9a_processes']
    def collect(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                collect(test)
            else:
                if isinstance(test, unittest.loader._FailedTest):
                    raise RuntimeError(test.id())
                ids.add(test.id())
    for label in labels:
        collect(unittest.defaultTestLoader.loadTestsFromName(label))
    groups = {}
    for identifier in sorted(ids):
        groups.setdefault(identifier.rsplit('.', 2)[0], []).append(identifier)
    shards = [[], [], []]
    for tests in sorted(groups.values(), key=len, reverse=True):
        min(shards, key=len).extend(tests)
    (OUT/'regression-inventory.json').write_text(json.dumps(sorted(ids), indent=2)+'\n')
    for index, shard in enumerate(shards):
        (OUT/f'regression-{index}-selected.json').write_text(json.dumps(sorted(shard), indent=2)+'\n')
    print('REGRESSION IDS', len(ids), 'SHARDS', list(map(len, shards)), flush=True)


def tests(index):
    database = PREFIX + 'regression_' + str(index)
    with psycopg.connect(uri('postgres'), autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(database), sql.Identifier(PREFIX+'template')))
    run([str(PYTHON), '-X', 'utf8', '-m', 'apps.agent.tests.run_b9a_acceptance',
         '--suite', 'targeted', '--database', database, '--ids-file', str(OUT/f'regression-{index}-selected.json'),
         '--output', str(OUT/f'regression-{index}')], cwd=ROOT/'backend',
        env=dict(ENV, DATABASE_URL=uri(PREFIX+'template')))


def checks():
    run([str(PYTHON), '-X', 'utf8', '-m', 'apps.agent.tests.run_b9a_acceptance',
        '--suite', 'checks', '--database', PREFIX+'template', '--output', str(OUT/'checks')],
        cwd=ROOT/'backend', env=dict(ENV, DATABASE_URL=uri(PREFIX+'template')))


def targeted(label, ids_file):
    assert label and all(c.isalnum() or c=='-' for c in label)
    database=PREFIX+label.replace('-','_')
    with psycopg.connect(uri('postgres'),autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(
            sql.Identifier(database),sql.Identifier(PREFIX+'template')))
    run([str(PYTHON),'-X','utf8','-m','apps.agent.tests.run_b9a_acceptance','--suite','targeted',
         '--database',database,'--ids-file',str(Path(ids_file).resolve()),'--output',str(OUT/label)],
        cwd=ROOT/'backend',env=dict(ENV,DATABASE_URL=uri(PREFIX+'template')))


def prepare_final_tests():
    # Preserve the first inventory/receipts, including its one fixture failure.
    inventory = set(json.loads((OUT/'regression-inventory.json').read_text()))
    inventory.add('apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.'
                  'test_e4_yield_09_pending_safety_after_live_worker_is_not_withheld')
    affected_modules = ('test_b5_safety', 'test_e4_claim_yield', 'test_e4_yield_processes',
        'test_e4_selection', 'test_e4_processes', 'test_worker', 'test_planner',
        'test_w1_monotonic', 'test_w1_mono_causal', 'test_b9c_concurrency', 'test_b9c_processes')
    affected = sorted(t for t in inventory if t.rsplit('.', 2)[0].rsplit('.', 1)[1] in affected_modules)
    groups = {}
    for identifier in affected:
        groups.setdefault(identifier.rsplit('.', 2)[0], []).append(identifier)
    shards = [[], [], []]
    for tests in sorted(groups.values(), key=len, reverse=True):
        min(shards, key=len).extend(tests)
    (OUT/'regression-final-inventory.json').write_text(json.dumps(sorted(inventory), indent=2)+'\n')
    for index, shard in enumerate(shards):
        (OUT/f'regression-final-{index}-selected.json').write_text(json.dumps(sorted(shard), indent=2)+'\n')
    import hashlib
    from datetime import datetime, timezone
    source_paths = ['backend/apps/agent/worker.py', 'backend/apps/agent/tests/test_e4_claim_yield.py',
        'backend/apps/agent/tests/e4_yield_process.py', 'backend/apps/agent/tests/test_e4_yield_processes.py']
    prototype = subprocess.check_output(['rtk','proxy','git','show',':backend/apps/agent/worker.py'],cwd=ROOT)
    reconstructed = []; skip_safety_definition = False
    for line in (ROOT/source_paths[0]).read_text(encoding='utf-8').splitlines(keepends=True):
        if line.startswith('    pending_safety ='):
            skip_safety_definition = True
            continue
        if skip_safety_definition:
            assert line.strip().startswith('semantic_type=Message.SEMANTIC_SAFETY_SIGNAL)')
            skip_safety_definition = False
            continue
        reconstructed.append(line.replace('Q(pk__in=pending_safety) | ', ''))
    assert ''.join(reconstructed).encode('utf-8')==prototype
    refinement = dict(classification='SAME_E4_POLICY_NARROWED_FOR_B5', improvement_count=1,
        recorded_utc=datetime.now(timezone.utc).isoformat(),
        initial_regression=dict(selected=774, passed=773, fixture_failures=1,
            failed_id='apps.agent.tests.test_e4_claim_yield.E4ClaimYieldTests.test_e4_yield_08_safety_bypasses_forecast_and_occupied_org',
            reason='TransactionTestCase reuses setUp but does not inherit B9A class override_settings; safety automation was disabled'),
        probes=[dict(label='safety-edge-before', classification='FIXTURE_SETUP_FAILURE'),
                dict(label='safety-edge-before-v2', classification='CONFIRMED_PROTOTYPE_SAFETY_WITHHELD',
                    observation='After W1 deferred_to_new_input, selector returned [] with unbound pending safety instead of its conversation'),
                dict(label='safety-edge-after', classification='PASS_WITH_PENDING_SAFETY_EXEMPTION')],
        correction='Current pending safety is exempt from the same advisory forecast yield; no B3/B5 contract, claim or eligibility changes',
        prototype_worker_sha256=hashlib.sha256(prototype).hexdigest(),
        prototype_worker_hash_projection='LF-normalized Git index snapshot staged before refinement; exactly equals final source with only pending-safety exemption removed. Original receipts do not embed source hashes.',
        final_source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},
        revalidation=dict(selected=len(affected), modules=affected_modules, ids=affected,
            rationale='Rerun all selector/yield/safety/worker/planner, monotonic unit/causal and B9C unit/process cases affected by the additional advisory predicate. Other required historical families already executed against the prototype; protected runtime sources unchanged.',
            full_inventory=len(inventory), all_ids_on_final_source=False),
        post_refinement_measurements=['postfix-final-base','postfix-final-blocked'],
        prototype_measurements=['postfix-base','postfix-blocked'], formal_profile_rerun=False)
    (OUT/'refinement.json').write_text(json.dumps(refinement, indent=2)+'\n', encoding='utf-8')
    print('FINAL INVENTORY',len(inventory),'AFFECTED',len(affected),'SHARDS',list(map(len,shards)),flush=True)


def cleanup():
    assert DATA.resolve() == TEMP/'vet-e4-claim-pg16-data'
    log = TEMP/'vet-e4-claim-pg16.log'
    with psycopg.connect(uri('postgres'), autocommit=True) as conn:
        row = conn.execute("SELECT current_setting('data_directory'), current_setting('fsync'), current_setting('synchronous_commit')").fetchone()
        assert Path(row[0]).resolve() == DATA.resolve() and row[1:] == ('on', 'on')
        clients = conn.execute("SELECT pid,datname FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()").fetchall()
        assert not clients, clients
        waiting = conn.execute('SELECT count(*) FROM pg_locks WHERE NOT granted').fetchone()[0]
        prepared = conn.execute('SELECT count(*) FROM pg_prepared_xacts').fetchone()[0]
        assert waiting == prepared == 0
        names = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'test_b8b_e4claim_%'")]
        for database in names:
            assert database.startswith(PREFIX)
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
    run([str(PG/'pg_ctl.exe'), '-D', str(DATA), '-m', 'fast', '-w', 'stop'])
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', PORT)) != 0
    import hashlib
    receipt = dict(status='CLEANED', cluster=str(DATA), port=PORT, databases=names,
        other_clients=clients, waiting_locks=waiting, prepared_transactions=prepared, port_closed=True,
        fsync=row[1], synchronous_commit=row[2], server_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
    assert DATA.resolve() == TEMP/'vet-e4-claim-pg16-data' and DATA.resolve().parent == TEMP
    shutil.rmtree(DATA)
    log.unlink()
    receipt.update(data_directory_absent=not DATA.exists(), log_absent=not log.exists())
    (OUT/'cleanup.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('CLEANED own isolated cluster', flush=True)


parser = argparse.ArgumentParser()
parser.add_argument('action', choices=('init', 'diagnostic', 'matrix', 'prepare-tests', 'prepare-final-tests', 'tests', 'targeted', 'checks', 'cleanup'))
parser.add_argument('--shard', type=int, choices=(0,1,2))
parser.add_argument('--label')
parser.add_argument('--ids-file')
parser.add_argument('--scenario', default='base')
parser.add_argument('--ablation', choices=('no-noisy', 'no-pause', 'batch-three', 'fast-provider', 'bounded-yield'))
args = parser.parse_args()
if args.action == 'init':
    initialize()
elif args.action == 'diagnostic':
    assert args.label and all(c.isalnum() or c == '-' for c in args.label)
    raise SystemExit(diagnostic(args.label, args.scenario, args.ablation))
elif args.action == 'matrix':
    matrix()
elif args.action == 'prepare-tests':
    prepare_tests()
elif args.action == 'prepare-final-tests':
    prepare_final_tests()
elif args.action == 'tests':
    assert args.shard is not None
    tests(args.shard)
elif args.action == 'checks':
    checks()
elif args.action == 'targeted':
    assert args.ids_file
    targeted(args.label,args.ids_file)
else:
    cleanup()
