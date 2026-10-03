"""Discard raw functional output after retaining structured, verified receipts."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def write(name, value):
    path = OUT / name
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def main():
    assert read('verification-summary.json')['status'] == 'OPTIMIZATION_VERIFIED'
    assert read('cleanup.json')['data_directory_absent']
    assert OUT.name == 'e4-sql-redesign-2026-10-01' and OUT.parent.name == 'evals'
    check_log = (OUT / 'checks.log').read_text(encoding='utf-8')
    assert 'System check identified no issues' in check_log
    assert 'No changes detected' in check_log
    write('checks-summary.json', dict(exit_code=read('checks.exit.json')['exit_code'],
        commands=['migrate --noinput', 'check', 'makemigrations --check --dry-run', 'migrate --check'],
        system_check='PASS', new_migrations=0, pending_migrations=0))
    failed = read('new-final.results.json')
    diagnostic = (OUT / 'new-final.log').read_text(encoding='utf-8')
    assert "unexpected keyword argument 'now'" in diagnostic
    write('incidents.json', dict(final_gate_failures=0, final_gate_errors=0,
        incidents=[
            dict(stage='full-initial', kind='host_process_interruption',
                 completed_matrix_points=0, action='Recovered the verified isolated migrated template'),
            dict(stage='new', kind='duplicate_discovery_from_imported_testcase_classes',
                 selected=len(read('new.results.inventory.json')),
                 partial_passed=len((OUT/'new.results.passed.jsonl').read_text().splitlines()),
                 action='Stopped only the verified own Python tree; used module aliases; excluded partial run from final gate'),
            dict(stage='new-final', kind='new_process_harness_API_error',
                 failures=failed['failures'], errors=failed['errors'], failed_ids=failed['failed_ids'],
                 error="TypeError: claim_turn() got an unexpected keyword argument 'now'",
                 action='Corrected only new process harness to eligible_at; all five process tests rerun successfully'),
            dict(stage='post-first-point', kind='Windows_case_insensitive_artifact_filename_collision',
                 completed_samples=0, action='Used sql-post-old/new; recloned only the incomplete point; preserved all successful receipts'),
            dict(stage='regression', kind='host_process_interruption',
                 retained_source_verified_successes=659, resumed_pending_ids=116,
                 action='Retained successful per-ID journals; verified every source hash; reran only pending IDs on fresh isolated clones')]))
    journal = OUT / 'repair-processes.results.b9c-processes.jsonl'
    allowed = {'test_id','event','pid','backend_pid','ids','org_ids','admissions',
               'active','claimed','members','outcome','held'}
    for line in journal.read_text().splitlines():
        assert set(json.loads(line)) <= allowed
    discarded = []
    for path in sorted(OUT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        raw = path.suffix == '.log' or (path.suffix == '.jsonl'
            and not path.name.endswith('.passed.jsonl') and path != journal)
        if not raw:
            continue
        resolved = path.resolve()
        assert resolved.is_relative_to(OUT.resolve())
        discarded.append(dict(path=path.relative_to(OUT).as_posix(), bytes=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        path.unlink()
    write('privacy.json', dict(real_customer_data_used=False, productive_instrumentation_added=False,
        retained_payloads=False, retained_prompts_responses=False, retained_customer_phones_names=False,
        fixture='Synthetic local test domain; benchmark Message bodies empty',
        retained='SQL with structural parameters, plans, timings, counts, synthetic numeric IDs, test IDs and source hashes',
        discarded_raw_artifacts=discarded,
        historical_or_partial_failures_preserved_as_structured_incidents=True,
        process_journal_fields_validated=sorted(allowed)))
    print('RAW_LOGS_DISCARDED_AND_PRIVACY_RECEIPT_WRITTEN')


if __name__ == '__main__':
    main()
