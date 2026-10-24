"""Preflight all sealed reporter paths in RAM, then complete metadata reporting.

No application test, gate, sealed source or prior reporting attempt is changed.
The RAM preflight executes the entire original reporter with all writes overlaid.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
REPORTER = HERE / 'diagnostics/close_acceptance.py'
ACTA = REPO / 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
BACKUP1 = HERE / 'diagnostics/reporting-attempt-1'
BACKUP2 = HERE / 'diagnostics/reporting-attempt-2'
REPORTER_SHA256 = '69761d8092bbc03a929cc827c3cc48b0b5775bfb7213d77b8cbc46aa35c495af'
DRAFTS = ('preservation-of-prior-work.json', 'integrity-summary.json')
CURRENT_UNDERSCORE = frozenset(('profile-blocked_llm', 'profile-meta_slow',
                              'profile-blocked_llm-migrate', 'profile-meta_slow-migrate'))
OPTIONAL_PROBES = {('directed', '.ids.jsonl')} | {
    (label, '.results.json') for label in
    ('django-check', 'migration-drift', 'migrate', 'billing-schema')}
SUFFIXES = frozenset(('.command.json', '.gate.json', '.results.json', '.ids.jsonl',
                      '.results.passed.jsonl', '.json'))


def require(condition, message):
    if not condition:
        raise RuntimeError('r5 reporting completion v2: ' + message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(path.read_bytes())


def key(path):
    return str(Path(str(path)).resolve()).casefold()


def save_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def preconditions():
    require(sha(REPORTER) == REPORTER_SHA256, 'sealed reporter changed')
    sealed = [value for name, value in read(HERE / 'evaluation-seal.json')['files'].items()
              if Path(name).resolve() == REPORTER.resolve()]
    require(sealed == [REPORTER_SHA256], 'unexpected reporter seal')
    require(not (HERE / 'closure-reporting.json').exists(), 'reporting already completed')
    classification = read(HERE / 'final-classification.json')
    require(classification['decision'] == 'PENDING' and classification['classification'] ==
            'HARNESS_FIXTURE_TIME_DEPENDENCE_AND_ENVIRONMENT_AWAKE_INTERRUPTION' and
            classification['accepted_complete_gate_count'] == 13, 'joint classification differs')
    for name in ('cleanup.json', 'native-closure.json', 'resource-observer-closure.json'):
        require(read(HERE / name)['state'] == 'PASS', 'closure prerequisite incomplete: ' + name)
    awake = read(HERE / 'awake-request/closure.json')
    require(awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and
            awake['matches_original_thread_state'] is True, 'awake restoration incomplete')
    preservation = read(BACKUP1 / 'preservation.json')
    require(preservation['state'] == 'PASS', 'first reporting drafts not preserved')
    expected = {row['name']: row['sha256_before'] for row in preservation['files']}
    require(set(expected) == set(DRAFTS), 'unexpected preserved draft inventory')
    for name in DRAFTS:
        require(sha(BACKUP1 / name) == sha(HERE / name) == expected[name],
                'current metadata draft does not equal the first preserved attempt: ' + name)
    require(not BACKUP2.exists(), 'second reporting preservation already exists')
    return classification, expected


def raw_current(label, suffix):
    require(label in CURRENT_UNDERSCORE and suffix in SUFFIXES, 'unknown current profile probe')
    path = HERE / 'blocks' / (label + suffix)
    require(path.resolve().is_relative_to(HERE.resolve()) and
            not path.parent.is_symlink() and not path.parent.is_junction() and
            not path.is_symlink() and not path.is_junction(), 'unsafe current profile path')
    require(not path.exists(), 'r5 current profile artifact unexpectedly exists')
    return path


def compatible_namespace():
    namespace = runpy.run_path(str(REPORTER), run_name='r5_original_reporting_without_main')
    scope = namespace['main'].__globals__
    strict_source = scope['source_for']
    strict_block = scope['block_path']
    strict_provenance = scope['provenance']
    strict_reused = scope['is_reused']
    manifest = read(HERE / 'reuse-manifest.json')
    require(not (CURRENT_UNDERSCORE & set(manifest['blocks'])), 'current profile appears inherited')
    for label in CURRENT_UNDERSCORE:
        for suffix in SUFFIXES:
            raw_current(label, suffix)
        require(not (HERE / ('monitor-' + label + '.json')).exists(),
                'current profile monitor unexpectedly exists')

    def source_for(label):
        if label in CURRENT_UNDERSCORE:
            raw_current(label, '.command.json')
            return HERE
        return strict_source(label)

    def provenance(label):
        if label in CURRENT_UNDERSCORE:
            raw_current(label, '.command.json')
            return {'origin': 'CURRENT', 'campaign': HERE.name, 'artifactdir': str(HERE / 'blocks')}
        return strict_provenance(label)

    def is_reused(label):
        if label in CURRENT_UNDERSCORE:
            raw_current(label, '.command.json')
            return False
        return strict_reused(label)

    def candidate(label, suffix):
        source = Path(source_for(label))
        path = source / 'blocks' / (label + suffix)
        require(path.resolve().is_relative_to(source.resolve()) and
                not path.parent.is_symlink() and not path.parent.is_junction() and
                not path.is_symlink() and not path.is_junction(), 'unsafe optional artifact')
        return path

    def block_path(label, suffix):
        if label in CURRENT_UNDERSCORE:
            return raw_current(label, suffix)
        if (label, suffix) in OPTIONAL_PROBES:
            path = candidate(label, suffix)
            if not path.exists():
                return path
        return strict_block(label, suffix)

    def journal_path(label):
        path = candidate(label, '.ids.jsonl')
        if path.exists():
            return Path(strict_block(label, '.ids.jsonl'))
        if label == 'directed':
            passed = candidate(label, '.results.passed.jsonl')
            return Path(strict_block(label, '.results.passed.jsonl')) if passed.exists() else passed
        return path

    scope.update(source_for=source_for, provenance=provenance, is_reused=is_reused,
                 block_path=block_path, journal_path=journal_path)
    return namespace['main'], scope


def dry_report(expected):
    """Run original main with real read-only inputs and a RAM write overlay."""
    overlay = {}
    hidden = {key(HERE / name) for name in DRAFTS}

    class MemoryPath(type(HERE)):
        def exists(self):
            item = key(self)
            if item in overlay:
                return True
            return False if item in hidden else Path(str(self)).exists()

        def is_file(self):
            item = key(self)
            if item in overlay:
                return True
            return False if item in hidden else Path(str(self)).is_file()

        def glob(self, pattern, *args, **kwargs):
            for path in super().glob(pattern, *args, **kwargs):
                if key(path) not in hidden:
                    yield path

        def read_bytes(self):
            item = key(self)
            return overlay[item] if item in overlay else Path(str(self)).read_bytes()

        def read_text(self, encoding=None, errors=None):
            return self.read_bytes().decode(encoding or 'utf-8', errors or 'strict')

        def write_bytes(self, data):
            actual = Path(str(self)).resolve()
            require(actual.is_relative_to(HERE.resolve()) or actual == ACTA.resolve(),
                    'dry reporter attempted a write outside its metadata outputs')
            overlay[key(self)] = bytes(data)
            return len(data)

        def write_text(self, data, encoding=None, errors=None, newline=None):
            require(newline in (None, '\n'), 'unexpected newline conversion')
            rendered = data.replace('\n', os.linesep) if newline is None else data
            self.write_bytes(rendered.encode(encoding or 'utf-8', errors or 'strict'))
            return len(data)

    main_function, scope = compatible_namespace()
    scope['HERE'] = MemoryPath(HERE)
    scope['REPO'] = MemoryPath(REPO)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        main_function()
    statuses = json.loads(overlay[key(HERE / 'block-status.json')])
    classification = read(HERE / 'final-classification.json')
    require(all(statuses[label]['state'] == 'PASS'
                for label in classification['accepted_complete_pass_gates']), 'dry run lost a complete PASS')
    require(statuses['full-general']['state'] == 'PENDING_ENVIRONMENT_INTERRUPTION' and
            statuses['full']['state'] == 'INCOMPLETE', 'dry run incorrectly accepted partial full')
    for name in DRAFTS:
        require(digest(overlay[key(HERE / name)]) == expected[name],
                'dry regenerated metadata differs from preserved attempts: ' + name)
    require(all(sha(HERE / name) == expected[name] for name in DRAFTS), 'dry run wrote a real metadata file')
    return overlay, {'state': 'PASS_RAM_ONLY', 'all_reporter_labels_and_probes_exercised': True,
                     'captured_metadata_outputs': len(overlay), 'accepted_complete_gates': 13,
                     'general_and_full_accepted_as_pass': False,
                     'application_tests_or_services_started': False}


def main(dry_only=False):
    classification, expected = preconditions()
    overlay, dry_receipt = dry_report(expected)
    if dry_only:
        print(json.dumps(dry_receipt))
        return
    audit = HERE / 'diagnostics/reporting-resolution-adaptation-v2.json'
    require(not audit.exists(), 'v2 adaptation already started; no silent rerun')
    moves = []
    for name in DRAFTS:
        source, target = HERE / name, BACKUP2 / name
        require(source.resolve().is_relative_to(HERE.resolve()) and
                target.resolve().is_relative_to(HERE.resolve()) and not target.exists() and
                not source.is_symlink() and not source.is_junction(), 'unsafe metadata preservation move')
        moves.append({'name': name, 'source_absolute': str(source.resolve()),
                      'destination_absolute': str(target.resolve()), 'sha256_before': expected[name]})
    require(not BACKUP2.parent.is_symlink() and not BACKUP2.parent.is_junction(), 'linked diagnostics path')
    save_new(audit, {'state': 'AUTHORIZED_POST_DRY_RUN_METADATA_ADAPTATION',
                    'utc': datetime.now(timezone.utc).isoformat(), 'sealed_reporter_sha256': REPORTER_SHA256,
                    'dry_run': dry_receipt, 'globals_overridden':
                    ['source_for', 'provenance', 'is_reused', 'block_path', 'journal_path'],
                    'current_only_underscore_labels': sorted(CURRENT_UNDERSCORE),
                    'existing_references_always_use_original_sha_verification': True,
                    'metadata_preservation_moves': moves,
                    'save_and_path_implementations_unchanged_in_real_main': True,
                    'application_tests_or_gates_modified': False})
    BACKUP2.mkdir()
    for row in moves:
        source, target = Path(row['source_absolute']), Path(row['destination_absolute'])
        require(sha(source) == row['sha256_before'] and not target.exists(), 'draft changed before move')
        source.rename(target)
        require(not source.exists() and sha(target) == row['sha256_before'], 'draft move changed bytes')
        row['sha256_after_move'] = sha(target)
    save_new(BACKUP2 / 'preservation.json', {'state': 'PASS', 'files': moves,
                                          'recursive_move_performed': False})
    main_function, _ = compatible_namespace()
    main_function()
    for name in DRAFTS:
        require(sha(HERE / name) == sha(BACKUP1 / name) == sha(BACKUP2 / name) == expected[name],
                'real metadata does not equal both retained attempts')
    for absolute, data in overlay.items():
        require(Path(absolute).read_bytes() == data, 'real report differs from successful RAM preflight: ' + absolute)
    require(sha(REPORTER) == REPORTER_SHA256, 'sealed reporter changed')
    statuses = read(HERE / 'block-status.json')
    require(all(statuses[label]['state'] == 'PASS'
                for label in classification['accepted_complete_pass_gates']), 'accepted PASS lost')
    save_new(HERE / 'diagnostics/invalid-fixture-closure.json', {
        'state': 'PASS', 'technical_acceptance_decision': 'PENDING',
        'classification': classification['classification'], 'accepted_complete_gate_count': 13,
        'product_failure_established': False, 'sealed_candidate_modified': False,
        'reporter_source_sha256': sha(REPORTER), 'adapter_sha256': sha(Path(__file__)),
        'dry_run': dry_receipt, 'real_outputs_equal_ram_preflight': True,
        'both_failed_metadata_attempts_preserved': True,
        'application_tests_executed_by_this_helper': False})
    print('R5_REPORTING_COMPLETION_V2_PASS technical_acceptance=PENDING retained_complete_gates=13')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    main(dry_only=parser.parse_args().dry_run)
