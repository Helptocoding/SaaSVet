"""Record native evaluator adaptations before the immutable campaign seal."""
import ast
import difflib
import json
from pathlib import Path
import sys
from native_support import EVIDENCE, SHA, save, sha256, integrity, command, RTK


def main():
    assert not (EVIDENCE / 'evaluation-seal.json').exists()
    assert not (EVIDENCE / 'STOP.json').exists()
    assert json.loads((EVIDENCE / 'native-preflight.json').read_text())['state'] == 'PASS'
    prior = EVIDENCE.with_name('b9-correction-20261015-native-r1')
    changes = []
    for path in sorted(EVIDENCE.glob('*.py')):
        source = path.read_text(encoding='utf-8')
        ast.parse(source, filename=str(path))
        compile(source, str(path), 'exec')
        assert not any(line.rstrip() != line for line in source.splitlines()), path.name
        previous = prior / path.name
        baseline = previous.read_text(encoding='utf-8') if previous.exists() else ''
        diff = ''.join(difflib.unified_diff(baseline.splitlines(True), source.splitlines(True),
            fromfile='native-r1/' + path.name, tofile='native/' + path.name))
        if diff:
            target = EVIDENCE / 'native-adaptation-diffs' / (path.name + '.diff')
            target.parent.mkdir(exist_ok=True)
            target.write_text(diff, encoding='utf-8', newline='\n')
        changes.append({'path': path.name, 'sha256': sha256(path.read_bytes()),
            'prior_sha256': sha256(previous.read_bytes()) if previous.exists() else None,
            'changed': bool(diff)})
    contract = json.loads((EVIDENCE / 'full-partition.json').read_text())
    integrity('native-final-preflight')
    command('rtk-gain-verification', [RTK, 'gain'])
    save('campaign-adaptation.json', {
        'state': 'PREPARED_BEFORE_FORMAL_SEAL', 'candidate_tree': SHA,
        'application_tests_executed': False, 'wsl_invoked': False,
        'candidate_sources_changed_by_adaptation': False,
        'fixed_contract': 'PLAN.md and full-partition-contract.json',
        'full_inventory': 3331, 'full_groups': [
            {'label': row['label'], 'database': row['database'], 'count': row['count']}
            for row in contract['groups']],
        'preserved': ['All test IDs, assertions, guards and internal concurrency',
            'Sequential block order and original native test runners',
            'PROFILE workload, 30/300/20 timings and applicable gates',
            'Durable PostgreSQL settings and two-planner/one-sender architecture',
            'One formal invocation per block and variant; no adaptive reruns',
            '2 GiB host RAM, 1 GiB backing disk and 1 second clock limits'],
        'native_adaptations': [
            'Private verified CPython 3.13.2 copy, with only locked third-party packages',
            'Private PostgreSQL 16.15 cluster on loopback port 35486',
            'Private Node 20.20.2, pnpm 9.15.9 and Windows Gitleaks 8.18.4',
            'Frozen frontend lockfile, hoisted layout, package copy import mode',
            'Windows process ownership, resource API and local wall/monotonic observation',
            'Owned bounded Windows sleep request; global power and clock policy unchanged',
            'Native imports and UTF-8/LF receipts in evaluator helpers',
            'Read-only original Git history plus separate corrected-test scope for security'],
        'resumption_reference': 'resumption.json',
        'previous_native_preparation': '../b9-correction-20261015-native-r1/native-preflight.json',
        'source_diffs': 'native-adaptation-diffs', 'helper_sources': changes})
    assembly = json.loads((EVIDENCE / 'assembly.json').read_text())
    assembly['phase'] = 'ASSEMBLED_NOT_EXECUTED'
    save('assembly.json', assembly)
    print('NATIVE_ADAPTATION_RECORDED', flush=True)


if __name__ == '__main__':
    main()
