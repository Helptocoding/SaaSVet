"""Close the preflight-blocked campaign; never executes application tests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from prepare_campaign import EVIDENCE, REPO, TREE, WORK, PYTHON, PG, SHA, save, sha256, resources, run
from stage_environment import integrity, DATA, PORT


def main():
    incident = json.loads((EVIDENCE / 'environment-incident.json').read_text())
    assert incident['message'] == 'frontend-install failed during preparation; see log'
    assert not (EVIDENCE / 'blocks').exists() or not any((EVIDENCE / 'blocks').iterdir())
    failure = json.loads((EVIDENCE / 'frontend-install.exit.json').read_text())
    assert failure['exit_code'] == 1 and failure['preparation_only']
    assert 'ERR_PNPM_EPERM' in (EVIDENCE / 'frontend-install.log').read_text(encoding='utf-8')
    integrity('after-failed-install')
    save('STOP.json', {'state': 'PENDING', 'phase': 'preflight', 'candidate_sha': SHA,
        'cause': 'ERR_PNPM_EPERM while creating the locked frontend dependency symlink',
        'command_receipt': 'frontend-install.exit.json', 'log': 'frontend-install.log',
        'product_failure_attributed': False, 'application_tests_executed': 0,
        'formal_block_runs': 0, 'profile_runs': 0, 'new_campaign_requires_new_decision': True})
    sources = ['backend/apps/agent/tests/b9e_profile.py', 'backend/apps/agent/tests/b9a_harness.py',
               'backend/apps/agent/tests/test_b9a_e2e.py']
    unchanged = not run('git', 'diff', '--exit-code', '08310461337a284386299ec47c54125f2139bf7f', SHA, '--', *sources)
    save('profile-compatibility.json', {'candidate_sha': SHA, 'sources_unchanged_against_historical_candidate': unchanged,
        'historical_candidate': '08310461337a284386299ec47c54125f2139bf7f', 'sources': sources,
        'compatibility_basis': 'Identical Git blobs for runner, controlled providers and existing domain fixture',
        'executed': False, 'warmup_seconds': 30, 'measurement_seconds': 300, 'drain_seconds': 20,
        'read_actual_llm_calls': 2, 'scenario_or_gate_adaptation': False,
        'saturation_gates': ['safety_admitted_under_saturation', 'bounded_concurrency', 'saturation_observed']})
    seal_paths = [*EVIDENCE.glob('*.py'), EVIDENCE / 'PLAN.md', EVIDENCE / 'scope-manifest.json',
        EVIDENCE / 'toolchain.json', EVIDENCE / 'python-environment.json',
        EVIDENCE / 'effective-configuration.json', *EVIDENCE.glob('*-selected.json'),
        DATA / 'postgresql.conf', DATA / 'pg_hba.conf', PYTHON, PG / 'postgres.exe']
    save('evaluation-seal-at-stop.json', {'state': 'PREFLIGHT_INCOMPLETE_NO_FORMAL_EXECUTION',
        'files': {str(p): sha256(p.read_bytes()) for p in seal_paths},
        'candidate_manifest_sha256': sha256((EVIDENCE / 'candidate-sources.json').read_bytes()),
        'sources_unmodified': True, 'receipts_adapter_used': False})
    save('preflight.json', {'state': 'PENDING', 'candidate_sha': SHA, 'exact_git_files_verified': 3332,
        'directed_ids_resolved': 87, 'full_regression_ids_discovered': 3331,
        'python_locked_environment': 'PASS', 'postgresql_private_durable': 'PASS',
        'node_20_and_pnpm_9': 'PASS', 'gitleaks_binary_8_18_4_prepared': True,
        'frontend_frozen_install': 'BLOCKED_ERR_PNPM_EPERM', 'resources': resources(),
        'source_integrity_after_failed_install': 'PASS', 'formal_execution_started': False,
        'version_changes_to_locks_or_product': False, 'clock_configuration_changed': False,
        'three_unrelated_checkout_changes_preserved': True})
    save('block-status.json', {'candidate_sha': SHA, 'decision': 'PENDING', 'preflight': 'PENDING',
        'directed_87_ids': 'NOT_EXECUTED', 'backend_checks': 'NOT_EXECUTED',
        'critical_runners_b0_b3_b4_b5': 'NOT_EXECUTED', 'backend_full_3331_ids': 'NOT_EXECUTED',
        'frontend_build_test_smoke': 'NOT_EXECUTED', 'security_full_history_scan': 'NOT_EXECUTED',
        'advisory_lint_dependency_audits': 'NOT_EXECUTED',
        'profile': {s: 'NOT_EXECUTED' for s in ('base', 'blocked_llm', 'meta_slow', 'duplicate', 'saturation')}})
    # SQL here is confined to the freshly created private cluster; no app is imported.
    import psycopg
    cleanup = {'owned_workspace': str(WORK), 'owned_data_directory': str(DATA), 'port': PORT,
               'postgres_bin_reused_not_removed': str(PG), 'python_env_reused_not_removed': str(PYTHON.parent.parent)}
    with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='postgres', autocommit=True) as conn:
        actual = conn.execute("SELECT current_setting('data_directory'), current_setting('port')").fetchone()
        assert Path(actual[0]).resolve() == DATA.resolve() and actual[1] == str(PORT)
        databases = [row[0] for row in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'")]
        assert databases == ['test_b9i_control']
        cleanup['databases_before'] = databases
        cleanup['connections_before'] = conn.execute("SELECT pid, datname, state, backend_type FROM pg_stat_activity WHERE pid <> pg_backend_pid() ORDER BY pid").fetchall()
        cleanup['prepared_transactions_before'] = conn.execute('SELECT gid, database FROM pg_prepared_xacts').fetchall()
        cleanup['locks_before'] = conn.execute('SELECT locktype, mode, granted, count(*) FROM pg_locks GROUP BY locktype, mode, granted ORDER BY 1,2,3').fetchall()
        assert not cleanup['prepared_transactions_before']
        assert not any(row[1] == 'test_b9i_control' for row in cleanup['connections_before'])
        with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e', dbname='test_b9i_control') as empty:
            cleanup['application_public_tables'] = empty.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
            assert not cleanup['application_public_tables']
        conn.execute('DROP DATABASE test_b9i_control')
        cleanup['owned_databases_dropped'] = ['test_b9i_control']
    config_copy = EVIDENCE / 'private-postgresql'
    config_copy.mkdir(exist_ok=False)
    for name in ('postgresql.conf', 'pg_hba.conf'):
        shutil.copyfile(DATA / name, config_copy / name)
    with (EVIDENCE / 'pg-stop.log').open('wb') as stream:
        result = subprocess.run(['rtk', 'proxy', str(PG / 'pg_ctl.exe'), '-D', str(DATA),
            '-m', 'fast', '-w', '-t', '60', 'stop'], stdin=subprocess.DEVNULL,
            stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    cleanup['pg_stop_exit_code'] = result.returncode
    cleanup['postmaster_pid_file_absent'] = not (DATA / 'postmaster.pid').exists()
    assert result.returncode == 0 and cleanup['postmaster_pid_file_absent']
    integrity('final-before-cleanup')
    # Recursive removal is restricted to the exact workspace created by this campaign.
    absolute = WORK.resolve()
    expected = (Path(os.environ['TEMP']) / 'b9i-1947726').resolve()
    assembly = json.loads((EVIDENCE / 'assembly.json').read_text())
    assert absolute == expected == Path(assembly['workspace']).resolve()
    assert absolute.parent == Path(os.environ['TEMP']).resolve() and absolute != REPO.resolve()
    cleanup['resolved_recursive_removal_target_verified'] = str(absolute)
    shutil.rmtree(absolute)
    cleanup['workspace_removed'] = not absolute.exists()
    cleanup['resources_after'] = resources()
    save('cleanup.json', cleanup | {'state': 'PASS'})
    initial = json.loads((EVIDENCE / 'checkout-before.json').read_text())
    final = {'head': run('git', 'rev-parse', 'HEAD').decode().strip(),
        'branch': run('git', 'branch', '--show-current').decode().strip(),
        'unrelated': {p: {'exists': (REPO / p).exists(), 'sha256': sha256((REPO / p).read_bytes()) if (REPO / p).exists() else None}
                      for p in initial['unrelated']}}
    final['unrelated_unchanged'] = final['unrelated'] == initial['unrelated']
    assert final['unrelated_unchanged'] and final['head'] == initial['head'] and final['branch'] == initial['branch']
    save('checkout-final.json', final)
    print('PENDING; no formal tests; private database and workspace removed.', flush=True)


if __name__ == '__main__':
    main()
