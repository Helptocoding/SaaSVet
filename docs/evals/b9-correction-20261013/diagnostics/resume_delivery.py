"""Finish staging verification after a diff-context whitespace rejection.

Never invoke the campaign or rebuild the preserved archive.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from deliver_wsl import REPO, SHARED, digest, run, save, staged_blobs


def main():
    before = json.loads((HERE / 'delivery-verification.json').read_text())
    assert before['state'] == 'VERIFYING'
    manifest = json.loads((HERE / 'preservation-manifest.json').read_text())
    proof = json.loads((HERE / 'preservation-verification.json').read_text())
    assert proof['internal_restore']['state'] == proof['actual_cli_restore']['state'] == 'PASS'
    assert proof['package_sha256'] == manifest['archive_sha256']
    package = b''.join((HERE / part['path']).read_bytes() for part in manifest['parts'])
    assert digest(package) == manifest['archive_sha256']
    assert all(digest((HERE / part['path']).read_bytes()) == part['sha256'] for part in manifest['parts'])
    original = json.loads((HERE / 'checkout-before.json').read_text())
    assert run('git', 'rev-parse', 'HEAD').decode().strip() == original['head']
    assert run('git', 'branch', '--show-current').decode().strip() == original['branch']
    baseline = json.loads((HERE / 'index-before-delivery.json').read_text())
    save('delivery-resumption.json', {
        'cause': 'git diff --cached --check reported whitespace in empty context lines of two preserved correction.diff artifacts',
        'initial_packager_exit_code': 1,
        'affected_paths': ['correction.diff', 'focused/attempt1/correction.diff'],
        'remediation': 'Only path-specific .gitattributes blank-at-eol handling; original diff bytes preserved',
        'archive_rebuilt': False, 'formal_campaign_rerun': False,
        'sealed_evaluator_changed': False, 'archive_sha256': manifest['archive_sha256'],
        'supplemental_completion_paths_outside_archive': ['diagnostics/resume_delivery.py', 'delivery-resumption.json'],
    })
    selection = json.loads((HERE / 'git-selection.json').read_text())
    selection['paths'] = sorted(set(selection['paths']) | {
        (HERE / n).relative_to(REPO).as_posix() for n in ['diagnostics/resume_delivery.py', 'delivery-resumption.json']
    })
    selection['completion_resumed_after_diff_context_attribute_fix'] = True
    save('git-selection.json', selection)
    run('git', 'add', '--pathspec-from-file=-', '--pathspec-file-nul', stdin=('\0'.join(selection['paths']) + '\0').encode())
    run('git', 'diff', '--cached', '--check')
    staged = staged_blobs(set(selection['paths']) | set(baseline))
    prior_drift = [n for n, h in baseline.items() if n not in SHARED and digest(staged[n]) != h]
    mismatches, normalized = [], []
    for n in selection['paths']:
        local = (REPO / n).read_bytes()
        if local == staged[n]:
            continue
        if n in ('.gitattributes', '.gitignore') and local.replace(b'\r\n', b'\n') == staged[n].replace(b'\r\n', b'\n'):
            normalized.append(n)
        else:
            mismatches.append(n)
    evidence_drift = [n for n, row in manifest['files'].items() if digest((HERE / n).read_bytes()) != row['sha256']]
    assert not prior_drift and not mismatches and not evidence_drift, (prior_drift, mismatches, evidence_drift)
    code = json.loads((HERE / 'code-selection.json').read_text())
    assert all(digest(staged[n]) == code['staged_sha256'][n] for n in code['explicit_paths'])
    save('delivery-verification.json', {
        'state': 'PASS', 'selected_paths': len(selection['paths']),
        'evidence_git_blobs_equal_local_bytes': True, 'root_text_normalized_paths': normalized,
        'prior_staged_paths_checked': len(baseline),
        'prior_staged_drift_outside_three_delivery_files': prior_drift,
        'evidence_drift': evidence_drift, 'cached_diff_check_exit_code': 0,
        'recovered_members': proof['internal_restore']['recovered_members'],
        'archive_sha256': manifest['archive_sha256'], 'archive_rebuilt': False,
        'staged_code_equals_frozen_candidate_tree': True,
        'completion_resumed_after_diff_context_attribute_fix': True,
        'commits_created': 0, 'pushes_performed': 0,
    })
    relative = (HERE / 'delivery-verification.json').relative_to(REPO).as_posix()
    run('git', 'add', '--', relative)
    assert run('git', 'show', ':' + relative) == (HERE / 'delivery-verification.json').read_bytes()
    run('git', 'diff', '--cached', '--check')
    print(json.dumps({'delivery': 'PASS', 'selected_paths': len(selection['paths']), 'recovered_members': proof['internal_restore']['recovered_members']}))


if __name__ == '__main__':
    main()
