"""Complete r5 reporting with a narrow, audited optional-artifact adapter.

The original reporter and its sealed sources remain byte-identical.  The two
metadata drafts from the failed reporting attempt are retained byte for byte in
diagnostics before the original main regenerates and compares them.
"""
import hashlib
import json
from pathlib import Path
import runpy
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
REPORTER = HERE / 'diagnostics/close_acceptance.py'
BACKUP = HERE / 'diagnostics/reporting-attempt-1'
EXPECTED_REPORTER_SHA256 = '69761d8092bbc03a929cc827c3cc48b0b5775bfb7213d77b8cbc46aa35c495af'
DRAFTS = ('preservation-of-prior-work.json', 'integrity-summary.json')
OPTIONAL_PROBES = {('directed', '.ids.jsonl')} | {
    (label, '.results.json') for label in
    ('django-check', 'migration-drift', 'migrate', 'billing-schema')}


def require(condition, message):
    if not condition:
        raise RuntimeError('r5 reporting completion: ' + message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def main():
    require(sha(REPORTER) == EXPECTED_REPORTER_SHA256, 'sealed reporter bytes changed')
    seal = read(HERE / 'evaluation-seal.json')
    sealed_hashes = [digest for path, digest in seal['files'].items()
                     if Path(path).resolve() == REPORTER.resolve()]
    require(sealed_hashes == [EXPECTED_REPORTER_SHA256], 'reporter is not the expected sealed input')
    require(not BACKUP.exists(), 'reporting draft preservation directory already exists')
    require(not (HERE / 'closure-reporting.json').exists(), 'reporting already completed')
    classification = read(HERE / 'final-classification.json')
    require(classification['decision'] == 'PENDING' and classification['classification'] ==
            'HARNESS_FIXTURE_TIME_DEPENDENCE_AND_ENVIRONMENT_AWAKE_INTERRUPTION' and
            classification['accepted_complete_gate_count'] == 13,
            'joint classification is absent or differs')
    require((HERE / 'diagnostics/fixture-and-awake-observation.json').is_file(),
            'the retained joint observation is absent')
    for name in ('cleanup.json', 'native-closure.json', 'resource-observer-closure.json'):
        require(read(HERE / name)['state'] == 'PASS', 'closure prerequisite is incomplete: ' + name)
    awake = read(HERE / 'awake-request/closure.json')
    require(awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and
            awake['matches_original_thread_state'] is True, 'awake restoration incomplete')

    root = HERE.resolve()
    require(BACKUP.resolve().is_relative_to(root), 'draft destination escaped campaign')
    require(not BACKUP.parent.is_symlink() and not BACKUP.parent.is_junction(),
            'linked diagnostics directory')
    draft_rows = []
    for name in DRAFTS:
        source = HERE / name
        target = BACKUP / name
        require(source.resolve().is_relative_to(root) and target.resolve().is_relative_to(root),
                'metadata move escaped the checked absolute campaign path')
        require(source.is_file() and not source.is_symlink() and not source.is_junction() and
                not target.exists(), 'unexpected metadata draft or preservation destination')
        draft_rows.append({'name': name, 'source_absolute': str(source.resolve()),
                           'destination_absolute': str(target.resolve()),
                           'sha256_before': sha(source), 'bytes': source.stat().st_size})
    untouched = [HERE / name for name in (
        'evaluation-seal.json', 'final-classification.json', 'STOP.json', 'invocation-formal.json',
        'run_campaign.py', 'full_partition.py', 'composite_evidence.py',
        'blocks/full-general.command.json', 'blocks/full-general.ids.jsonl',
        'diagnostics/close_acceptance.py', 'diagnostics/close_invalid_fixture.py',
        'diagnostics/fixture-and-awake-observation.json')]
    source_hashes = {path.relative_to(HERE).as_posix(): sha(path) for path in untouched}
    audit = HERE / 'diagnostics/reporting-resolution-adaptation.json'
    require(not audit.exists(), 'reporting adaptation already recorded; no silent rerun')
    save_new(audit, {
        'state': 'AUTHORIZED_METADATA_REPORTING_ADAPTATION',
        'utc': datetime.now(timezone.utc).isoformat(),
        'sealed_reporter_sha256': EXPECTED_REPORTER_SHA256,
        'reporter_source_modified': False, 'application_tests_or_gates_modified': False,
        'globals_overridden': ['journal_path', 'block_path'],
        'optional_block_path_probes': [list(row) for row in sorted(OPTIONAL_PROBES)],
        'existing_artifact_policy': 'Always call the original SHA-verifying block_path',
        'missing_optional_policy': 'Return only the checked absent path; do not invent an artifact',
        'draft_preservation_moves': draft_rows,
        'draft_regeneration_policy': 'Original save remains unchanged; regenerated bytes must equal preserved drafts',
        'source_receipts_and_helpers_sha256': source_hashes})
    BACKUP.mkdir()
    for row in draft_rows:
        source = Path(row['source_absolute'])
        target = Path(row['destination_absolute'])
        require(sha(source) == row['sha256_before'] and not target.exists(),
                'draft changed before preservation move')
        source.rename(target)
        require(not source.exists() and sha(target) == row['sha256_before'],
                'draft preservation move did not retain its bytes')
        row['sha256_after_move'] = sha(target)
    save_new(BACKUP / 'preservation.json', {
        'state': 'PASS', 'recursive_move_performed': False,
        'moved_only_failed_reporting_metadata_drafts': True, 'files': draft_rows})

    namespace = runpy.run_path(str(REPORTER), run_name='r5_sealed_reporter_without_main')
    original_main = namespace['main']
    scope = original_main.__globals__
    strict_block_path = scope['block_path']
    strict_source_for = scope['source_for']

    def checked_candidate(label, suffix):
        source = Path(strict_source_for(label))
        candidate = source / 'blocks' / (label + suffix)
        require(candidate.resolve().is_relative_to(source.resolve()), 'optional probe escaped source')
        require(not candidate.parent.is_symlink() and not candidate.parent.is_junction() and
                not candidate.is_symlink() and not candidate.is_junction(),
                'linked optional reporting artifact')
        return candidate

    def optional_block_path(label, suffix):
        if (label, suffix) in OPTIONAL_PROBES:
            candidate = checked_candidate(label, suffix)
            if not candidate.exists():
                return candidate
        return strict_block_path(label, suffix)

    def optional_journal_path(label):
        candidate = checked_candidate(label, '.ids.jsonl')
        if candidate.exists():
            return Path(strict_block_path(label, '.ids.jsonl'))
        if label == 'directed':
            passed = checked_candidate(label, '.results.passed.jsonl')
            if passed.exists():
                return Path(strict_block_path(label, '.results.passed.jsonl'))
            return passed
        return candidate

    scope['journal_path'] = optional_journal_path
    scope['block_path'] = optional_block_path
    original_main()

    for row in draft_rows:
        original = HERE / row['name']
        retained = BACKUP / row['name']
        require(sha(original) == sha(retained) == row['sha256_before'],
                'regenerated reporting metadata differs from preserved draft: ' + row['name'])
    require(all(sha(HERE / name) == digest for name, digest in source_hashes.items()),
            'a sealed source or retained receipt changed')
    statuses = read(HERE / 'block-status.json')
    accepted = classification['accepted_complete_pass_gates']
    require(len(accepted) == 13 and all(statuses[label]['state'] == 'PASS' for label in accepted),
            'a valid complete PASS was lost')
    require(statuses['full-general']['state'] == 'PENDING_ENVIRONMENT_INTERRUPTION' and
            statuses['full']['state'] == 'INCOMPLETE', 'partial general/full was incorrectly accepted')
    cause = classification['cause']
    require(cause in (HERE / 'REPORT.md').read_text(encoding='utf-8') and
            cause in (REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md').read_text(encoding='utf-8'),
            'joint classification was not retained in report/ACTA')
    save_new(HERE / 'diagnostics/invalid-fixture-closure.json', {
        'state': 'PASS', 'technical_acceptance_decision': 'PENDING',
        'classification': classification['classification'], 'accepted_complete_gate_count': 13,
        'product_failure_established': False, 'sealed_candidate_modified': False,
        'reporter_executed': 'diagnostics/close_acceptance.py',
        'reporter_source_sha256': sha(REPORTER),
        'metadata_adapter': 'diagnostics/complete_invalid_fixture_report.py',
        'metadata_adapter_sha256': sha(Path(__file__)),
        'drafts_preserved_and_regenerated_identically': True,
        'source_receipts_and_helpers_unchanged': True,
        'report_sha256': sha(HERE / 'REPORT.md'),
        'application_tests_executed_by_this_helper': False})
    print('R5_REPORTING_COMPLETED_PASS technical_acceptance=PENDING retained_complete_gates=13')


if __name__ == '__main__':
    main()
