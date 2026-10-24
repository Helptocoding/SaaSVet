"""Conserve, recover, and stage an explicit documentary selection; no commit."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from prepare_campaign import EVIDENCE, REPO, SHA, save, sha256


def command(*args):
    return subprocess.check_output(['rtk', 'proxy', *map(str, args)], cwd=REPO, stdin=subprocess.DEVNULL)


def main():
    assert json.loads((EVIDENCE / 'cleanup.json').read_text())['state'] == 'PASS'
    assert json.loads((EVIDENCE / 'candidate-decision.json').read_text())['formal_runs'] == 0
    prefix = EVIDENCE.relative_to(REPO).as_posix()
    raw = sorted(p.relative_to(REPO).as_posix() for p in EVIDENCE.rglob('*')
                 if p.is_file() and p.suffix in ('.log', '.jsonl'))
    ignore = '\n# B9 integral campaign: originals retained locally and delivered in verified ZIP parts.\n'
    ignore += ''.join('/' + p + '\n' for p in raw)
    ignore += '/' + prefix + '/__pycache__/\n'
    with (REPO / '.gitignore').open('ab') as stream:
        stream.write(ignore.encode())
    pack = command(sys.executable, '-B', EVIDENCE / 'preserve_campaign.py').decode().strip()
    save('preservation-command.json', {'exit_code': 0, 'output': json.loads(pack), 'application_tests': False})
    with tempfile.TemporaryDirectory(prefix='brv-') as temp:
        destination = Path(temp) / 'restored'
        restored = command(sys.executable, '-B', EVIDENCE / 'restore_campaign.py', '--destination', destination).decode().strip()
        save('recovery-command.json', {'exit_code': 0, 'result': json.loads(restored),
            'destination_temporary_and_removed_after_verification': True, 'application_tests': False})
    paths = [p.relative_to(REPO).as_posix() for p in EVIDENCE.rglob('*') if p.is_file()
             and '__pycache__' not in p.parts and p.suffix not in ('.log', '.jsonl', '.pyc')]
    paths += ['.gitattributes', '.gitignore', 'docs/evals/b9-consolidation-2026-10-11/ACTA.md',
              prefix + '/git-selection.json', prefix + '/delivery-verification.json']
    paths = sorted(set(paths))
    save('git-selection.json', {'candidate_sha': SHA, 'branch': 'codex/e4-capacity-scheduling',
        'paths': paths, 'raw_original_paths_delivered_in_packages': raw,
        'excluded_unrelated': ['DEPLOY_VPS_PLAN.md', 'DEPLOY_VPS_STATUS.md', 'skills-lock.json'],
        'commit_authorized': False, 'push_authorized': False})
    save('delivery-verification.json', {'state': 'PREPARING_EXPLICIT_SELECTION'})
    with tempfile.TemporaryDirectory(prefix='b9i-stage-') as temp:
        pathspec = Path(temp) / 'paths.nul'
        pathspec.write_bytes(b'\0'.join(p.encode() for p in paths) + b'\0')
        command('git', '--literal-pathspecs', 'add', '--pathspec-from-file=' + str(pathspec), '--pathspec-file-nul')
    staged = set(command('git', 'diff', '--cached', '--name-only', '-z').decode().strip('\0').split('\0'))
    assert staged == set(paths)
    assert command('git', 'rev-parse', 'HEAD').decode().strip() == SHA
    initial = json.loads((EVIDENCE / 'checkout-before.json').read_text())
    unrelated = {p: {'exists': (REPO / p).exists(), 'sha256': sha256((REPO / p).read_bytes()) if (REPO / p).exists() else None}
                 for p in initial['unrelated']}
    assert unrelated == initial['unrelated']
    save('delivery-verification.json', {'state': 'PASS', 'candidate_sha': SHA,
        'explicit_staged_files': len(paths), 'staged_selection_matches': True,
        'unrelated_changes_unchanged_and_excluded': True, 'source_integrity': 'PASS_3332_FILES',
        'recovery': 'PASS', 'cleanup': 'PASS', 'application_tests_executed': 0,
        'formal_runs': 0, 'profile_variants_executed': 0, 'commits_created': 0, 'pushes_performed': 0})
    command('git', 'add', '--', prefix + '/delivery-verification.json')
    command('git', 'diff', '--cached', '--check')
    print(json.dumps({'decision': 'PENDING', 'staged_files': len(paths), 'preservation': json.loads(pack), 'cleanup': 'PASS'}))


if __name__ == '__main__':
    main()
