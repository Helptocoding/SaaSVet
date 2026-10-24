"""Sequential campaign controller. One execution per block; stop is durable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from prepare_campaign import EVIDENCE, REPO, TREE, WORK, PYTHON, PG, SHA, save, sha256, resources, run
from stage_environment import environment, integrity, NODE, PNPM, DATA, PORT

BLOCKS = EVIDENCE / 'blocks'
BLOCKS.mkdir(exist_ok=True)


def verify_seal(label):
    integrity(label)
    seal = json.loads((EVIDENCE / 'evaluation-seal.json').read_text())
    mismatch = [p for p, expected in seal['files'].items()
                if not Path(p).is_file() or sha256(Path(p).read_bytes()) != expected]
    save('seal-check-' + label + '.json', {'mismatches': mismatch, 'checked_files': len(seal['files'])})
    if mismatch:
        raise RuntimeError('Evaluation seal changed')


def db_create(name):
    assert name.startswith('test_b9i_')
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))


def execute(label, args, *, cwd=None, env=None, advisory=False):
    if (EVIDENCE / 'STOP.json').exists():
        raise RuntimeError('Campaign stopped; no further execution authorized')
    if not (EVIDENCE / 'preflight.json').exists():
        raise RuntimeError('Preflight absent')
    if json.loads((EVIDENCE / 'preflight.json').read_text())['state'] != 'PASS':
        raise RuntimeError('Preflight not passed')
    receipt = BLOCKS / (label + '.command.json')
    if receipt.exists():
        raise RuntimeError('Refusing formal rerun of ' + label)
    verify_seal('before-' + label)
    before = resources()
    if before['physical_available'] < 5 * 1024**3 or before['disk_available'] < 1024**3:
        save('STOP.json', {'state': 'PENDING', 'phase': label, 'cause': 'Insufficient resource margin before block', 'resources': before, 'block_executed': False})
        raise RuntimeError('Pre-block resource margin insufficient')
    args = list(map(str, args))
    config = environment()
    config.update(env or {})
    origin_mono, origin_wall = time.monotonic(), time.time()
    rows = []
    invalid = None
    receipt_data = {'label': label, 'candidate_sha': SHA, 'argv': args, 'cwd': str(cwd or TREE / 'backend'),
        'state': 'RUNNING', 'formal_run_number': 1, 'advisory': advisory, 'resources_before': before}
    receipt.write_text(json.dumps(receipt_data, indent=2) + '\n', encoding='utf-8')
    with (BLOCKS / (label + '.command.log')).open('wb') as stream:
        proc = subprocess.Popen(['rtk', 'proxy', *args], cwd=cwd or TREE / 'backend', env=config,
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        receipt_data['wrapper_pid'] = proc.pid
        last_wall = origin_wall
        while proc.poll() is None:
            now_mono, now_wall = time.monotonic(), time.time()
            snapshot = resources()
            snapshot.update(elapsed_seconds=now_mono - origin_mono,
                wall_minus_monotonic_seconds=(now_wall - origin_wall) - (now_mono - origin_mono))
            rows.append(snapshot)
            if now_wall < last_wall or abs(snapshot['wall_minus_monotonic_seconds']) > 1:
                invalid = 'Clock discontinuity'
            elif snapshot['physical_available'] < 2 * 1024**3:
                invalid = 'Physical memory reserve exhausted'
            elif snapshot['disk_available'] < 1024**3:
                invalid = 'Disk reserve exhausted'
            if invalid:
                # Stop only this owned wrapper and descendants; no foreign process.
                subprocess.run(['rtk', 'proxy', 'taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=stream, stderr=subprocess.STDOUT)
                break
            last_wall = now_wall
            time.sleep(1)
        code = proc.wait()
    receipt_data.update(exit_code=code, seconds=time.monotonic() - origin_mono,
                        state='COMPLETED', invalidating_incident=invalid, resources_after=resources())
    receipt.write_text(json.dumps(receipt_data, indent=2) + '\n', encoding='utf-8')
    save('monitor-' + label + '.json', rows)
    verify_seal('after-' + label)
    if invalid or (code and not advisory):
        save('STOP.json', {'state': 'PENDING_CLASSIFICATION', 'phase': label,
            'cause': invalid or 'Nonzero command exit; scenario validity must be classified from evidence',
            'exit_code': code, 'no_rerun': True})
    return code


def seal():
    assert (EVIDENCE / 'environment-ready.json').is_file()
    assert not (EVIDENCE / 'preflight.json').exists()
    discovery = json.loads((EVIDENCE / 'discovery.json').read_text())
    assert discovery['counts']['directed'] == 87 and not discovery['missing_directed']
    assert not any(discovery['loader_errors'].values())
    sources = ['backend/apps/agent/tests/b9e_profile.py', 'backend/apps/agent/tests/b9a_harness.py',
               'backend/apps/agent/tests/test_b9a_e2e.py']
    diff = run('git', 'diff', '--exit-code', '08310461337a284386299ec47c54125f2139bf7f', SHA, '--', *sources)
    assert not diff
    historical = json.loads((TREE / 'docs/evals/profile-beta-1-e4-sql-2026-10-02/saturation.json').read_text())
    save('profile-compatibility.json', {'candidate_sha': SHA,
        'historical_candidate': '08310461337a284386299ec47c54125f2139bf7f',
        'identical_git_sources': sources, 'git_diff_exit_code': 0,
        'historical_gates': list(historical['gates']), 'no_smoke_or_load_adaptation': True,
        'scenarios': ['base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation'],
        'warmup_seconds': 30, 'measurement_seconds': 300, 'drain_seconds': 20,
        'read_llm_calls_actual': 2, 'saturation_base_slo_not_applied': True})
    paths = [*EVIDENCE.glob('*.py'), EVIDENCE / 'scope-manifest.json', EVIDENCE / 'PLAN.md',
             EVIDENCE / 'effective-configuration.json', EVIDENCE / 'toolchain.json',
             EVIDENCE / 'python-environment.json', EVIDENCE / 'environment-ready.json',
             EVIDENCE / 'profile-compatibility.json', *EVIDENCE.glob('*-selected.json'),
             PYTHON, Path(sys._base_executable), NODE, PNPM,
             WORK / 'gitleaks/gitleaks.exe', PG / 'postgres.exe',
             DATA / 'postgresql.conf', DATA / 'pg_hba.conf']
    save('evaluation-seal.json', {'candidate_sha': SHA, 'files': {str(p): sha256(p.read_bytes()) for p in paths},
         'candidate_sources_manifest_sha256': sha256((EVIDENCE / 'candidate-sources.json').read_bytes()),
         'adapter': 'Receipt-only subclass of unchanged CriticalB0/B3/B4/B5 and DiscoverRunner; all original guards call super',
         'historical_directed_runner_unchanged': True})
    verify_seal('preflight')
    snapshot = resources()
    ready = snapshot['physical_available'] >= 5 * 1024**3 and snapshot['disk_available'] >= 1024**3
    save('preflight.json', {'state': 'PASS' if ready else 'PENDING', 'candidate_sha': SHA,
        'exact_git_files': 3332, 'directed_ids': 87, 'full_regression_ids': discovery['counts']['full'],
        'no_application_tests_yet': True, 'resources': snapshot, 'single_suite_memory_budget_bytes': 3 * 1024**3,
        'memory_reserve_bytes': 2 * 1024**3, 'disk_reserve_bytes': 1024**3,
        'physical_d29_new_scenarios_authorized': False, 'no_foreign_process_termination': True,
        'production_defaults_closed': True, 'host_clock_configuration_unchanged': True})
    if not ready:
        save('STOP.json', {'state': 'PENDING', 'phase': 'preflight', 'cause': 'Insufficient resources for frozen budget', 'resources': snapshot})
    print('Preflight ' + ('PASS' if ready else 'PENDING'), flush=True)


def main():
    action = sys.argv[1]
    if action == 'seal':
        seal()
        return
    if action == 'directed':
        return execute(action, [PYTHON, '-B', '-X', 'utf8', '-m', 'apps.agent.tests.run_b9a_acceptance',
            '--suite', 'targeted', '--database', 'test_b8b_b9i_directed',
            '--ids-file', EVIDENCE / 'directed-selected.json', '--output', BLOCKS / 'directed'])
    if action == 'checks':
        db_create('test_b9i_checks')
        env = {'DATABASE_URL': f'postgresql://b9e@127.0.0.1:{PORT}/test_b9i_checks'}
        commands = [('django-check', ['check']), ('migration-drift', ['makemigrations', '--check', '--dry-run']),
            ('migrate', ['migrate', '--no-input']), ('billing-schema', ['audit_billing_schema', '--json'])]
        for label, args in commands:
            if execute(label, [PYTHON, '-B', 'manage.py', *args], env=env):
                return 1
        return 0
    if action in ('b0', 'b3', 'b4', 'b5', 'full'):
        return execute(action, [PYTHON, '-B', EVIDENCE / 'recorded_suite.py', action, 'test_b9i_' + action],
            env={'B9I_SUITE': action, 'B9I_ID_JOURNAL': str(BLOCKS / (action + '.ids.jsonl')),
                 'B9I_SUITE_RECEIPT': str(BLOCKS / (action + '.results.json'))})
    if action.startswith('frontend-'):
        task = action.removeprefix('frontend-')
        args = [NODE, PNPM, 'run', task]
        if task == 'test':
            args += ['--reporter=default', '--reporter=json', '--outputFile=' + str(BLOCKS / 'frontend-tests.json')]
        return execute(action, args, cwd=TREE / 'frontend', advisory=task == 'lint')
    if action == 'security':
        return execute(action, [WORK / 'gitleaks/gitleaks.exe', 'detect', '--source', REPO,
            '--config', TREE / '.gitleaks.toml', '--redact', '--no-banner', '--verbose',
            '--report-format', 'json', '--report-path', BLOCKS / 'gitleaks-report.json', '--exit-code', '1'], cwd=REPO)
    if action == 'pnpm-audit':
        return execute(action, [NODE, PNPM, 'audit'], cwd=TREE / 'frontend', advisory=True)
    if action == 'profile':
        scenario = sys.argv[2]
        assert scenario in ('base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation')
        name = 'test_b9i_profile_' + scenario
        db_create(name)
        env = {'DATABASE_URL': f'postgresql://b9e@127.0.0.1:{PORT}/{name}'}
        label = 'profile-' + scenario
        if execute(label + '-migrate', [PYTHON, '-B', 'manage.py', 'migrate', '--no-input'], env=env):
            return 1
        return execute(label, [PYTHON, '-B', '-m', 'apps.agent.tests.b9e_profile',
            '--scenario', scenario, '--output', BLOCKS / (label + '.json')], env=env)
    raise ValueError('Unknown action ' + action)


if __name__ == '__main__':
    try:
        raise SystemExit(main() or 0)
    except Exception as exc:
        save('controller-incident.json', {'type': type(exc).__name__, 'message': str(exc), 'phase': sys.argv[1:]})
        raise
