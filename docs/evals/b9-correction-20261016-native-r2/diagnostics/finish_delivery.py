"""Finish evidence staging while preserving the verified native campaign archive."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from deliver_native import REPO, SHARED, digest, run, save, staged_blobs


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def main():
    assert read('delivery-verification.json')['state'] == 'VERIFYING'
    assert read('native-closure.json')['state'] == 'PASS'
    manifest = read('preservation-manifest.json')
    recovery = read('preservation-verification.json')
    assert recovery['internal_restore']['state'] == recovery['actual_cli_restore']['state'] == 'PASS'
    assert recovery['package_sha256'] == manifest['archive_sha256']
    for part in manifest['parts']:
        assert digest((HERE / part['path']).read_bytes()) == part['sha256']
    name = 'native-adaptation-diffs/cleanup_native.py.diff'
    source = (HERE / name).read_bytes()
    assert digest(source) == manifest['files'][name]['sha256']
    assert len(source.splitlines()) == 20 and source.splitlines()[-2:] == [b' ', b' ']
    evaluator = HERE / 'cleanup_native.py'
    evaluator_bytes = evaluator.read_bytes()
    sealed = read('evaluation-seal.json')['files']
    matches = [h for p, h in sealed.items() if Path(p).resolve() == evaluator.resolve()]
    assert matches == [digest(evaluator_bytes)]
    attributes = REPO / '.gitattributes'
    before = attributes.read_bytes()
    rule = ('docs/evals/' + HERE.name + '/' + name + ' '
            'whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol\n')
    assert rule.encode() not in before
    with attributes.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(rule)
    assert attributes.read_bytes().startswith(before)
    supplements = ['delivery-incident.json', 'diagnostics/finish_delivery.py']
    save('delivery-incident.json', {
        'state': 'RESOLVED_EVIDENCE_FORMAT_ONLY',
        'initial_command': ['git', 'diff', '--cached', '--check'],
        'initial_delivery_process_exit_code': 1,
        'raw_git_exit_code_not_retained': True,
        'cause': 'Literal new blank line at EOF in cleanup_native.py.diff, line 19',
        'preserved_diff_sha256': digest(source),
        'preserved_sealed_cleanup_source_sha256': digest(evaluator_bytes),
        'original_archive_sha256': manifest['archive_sha256'],
        'frozen_evaluator_source_modified': False,
        'original_package_rewritten': False,
        'format_exception_exact_path': 'docs/evals/' + HERE.name + '/' + name,
        'format_exception_rule': rule.strip(),
        'application_tests_guards_assertions_or_gates_changed': False,
        'formal_campaign_restarted': False,
        'supplemental_delivery_metadata_outside_original_archive': supplements})
    selection = sorted(set(read('git-selection.json')['paths']) | {
        (HERE / name).relative_to(REPO).as_posix() for name in supplements})
    save('git-selection.json', {
        'paths': selection, 'explicit': True, 'raw_logs_excluded_from_git': True,
        'delivery_metadata_supplement': 'delivery-incident.json'})
    baseline = read('index-before-delivery.json')
    run('git', 'add', '--pathspec-from-file=-', '--pathspec-file-nul',
        stdin=('\0'.join(selection) + '\0').encode())
    run('git', 'diff', '--cached', '--check')
    staged = staged_blobs(set(selection) | set(baseline))
    prior_drift = [name for name, h in baseline.items()
                   if name not in SHARED and digest(staged[name]) != h]
    mismatches, normalized = [], []
    for name in selection:
        local = (REPO / name).read_bytes()
        if local != staged[name]:
            if name in ('.gitattributes', '.gitignore') and local.replace(b'\r\n', b'\n') == staged[name].replace(b'\r\n', b'\n'):
                normalized.append(name)
            else:
                mismatches.append(name)
    drift = [name for name, row in manifest['files'].items()
             if digest((HERE / name).read_bytes()) != row['sha256']]
    assert not prior_drift and not mismatches and not drift, (prior_drift, mismatches, drift)
    save('delivery-verification.json', {
        'state': 'PASS', 'selected_paths': len(selection),
        'evidence_git_blobs_equal_local_bytes': True,
        'root_text_normalized_paths': normalized,
        'prior_staged_paths_checked': len(baseline),
        'prior_staged_drift_outside_three_delivery_files': prior_drift,
        'evidence_drift': drift, 'cached_diff_check_exit_code': 0,
        'recovered_members': recovery['internal_restore']['recovered_members'],
        'delivery_incident': 'delivery-incident.json',
        'original_archive_sha256': manifest['archive_sha256'],
        'supplemental_delivery_metadata_outside_original_archive': {
            name: digest((HERE / name).read_bytes()) for name in supplements},
        'commits_created': 0, 'pushes_performed': 0})
    relative = (HERE / 'delivery-verification.json').relative_to(REPO).as_posix()
    run('git', 'add', '--', relative)
    assert run('git', 'show', ':' + relative) == (HERE / 'delivery-verification.json').read_bytes()
    run('git', 'diff', '--cached', '--check')
    print(json.dumps({'delivery': 'PASS', 'selected_paths': len(selection),
                      'recovered_members': recovery['internal_restore']['recovered_members']}))


if __name__ == '__main__':
    main()
