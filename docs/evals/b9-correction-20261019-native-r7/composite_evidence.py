"""Retain strict block references and expose the authorized r7 case aggregate.

Historical receipts retain their campaign identity.  Nothing is installed under
the current blocks directory, and this module never starts application code.
"""
import ast
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import time


HERE = Path(__file__).resolve().parent
SOURCE_TREE_SHA = '196aceb4f5f234c086b96d8e8af93787613f3c25'
TREE_SHA = '68dffd746793700071f577a58528b0f9636930db'
FIXTURE_PATH = 'backend/apps/notifications/tests/test_notifications.py'
FIXTURE_TEST = 'apps.notifications.tests.test_notifications.DerivedFeedTests.test_upcoming_window'
OLD_FIXTURE_SHA = '1c1bbded0782ac4cbfc671cefdfee27365571c05c6172a67b5804002b681838f'
NEW_FIXTURE_SHA = 'b386adb26db5ee4ee5e6cffa1367ad13dbbed891e5e4f14d7ffd21bd3f23b118'
CLOCK_PATCH_SHA = 'e17f24b962a1f5ce288c8932a1b5eed8a9e81efa4da6f7dd7b91ea8a476c36b8'
R3 = 'b9-correction-20261016-native-r3'
R4 = 'b9-correction-20261016-native-r4'
R5 = 'b9-correction-20261017-native-r5'
REUSED = {label: R4 for label in
          ('directed', 'django-check', 'migration-drift', 'migrate', 'billing-schema')}
REUSED.update({label: R3 for label in
               ('b0', 'b3', 'b4', 'b5', 'full-b8b', 'full-b8c')})
REUSED.update({label: R5 for label in ('full-b8d', 'full-b8e')})
COUNTS = {'directed': 87, 'b0': 17, 'b3': 42, 'b4': 68, 'b5': 37,
          'full-b8b': 21, 'full-b8c': 41, 'full-b8d': 27, 'full-b8e': 29}
SEAL_HASHES = {
    R3: '6dd7e7ca061a9b0029a876b1635842eb2eae9bbd5b8a647ac1ca26de4fa9b470',
    R4: 'bfc7c427efed89d93e3134f4d0e3c83e30c4f9c3e012d8f18597b8ab45a0f4cf',
    R5: '0b5df35ddbf9c963d67b1811e7eccd609131c5d6dc644031294fe21d41976963',
}
GIB = 1024 ** 3
SCHEMA = 'b9-composite-referenced-pass-v2-fixture-clock'
_MANIFEST_CACHE = None


def _require(condition, message):
    if not condition:
        raise RuntimeError('Composite evidence: ' + message)


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _safe(root, relative):
    _require(isinstance(relative, str) and '\\' not in relative and ':' not in relative,
             'invalid relative artifact path')
    parts = PurePosixPath(relative).parts
    _require(parts and not relative.startswith('/') and
             all(part not in ('.', '..', '') for part in parts) and
             '/'.join(parts) == relative, 'artifact path escapes whitelist')
    path = root
    for part in parts:
        path = path / part
        _require(not path.is_symlink() and not path.is_junction(),
                 'symlink/junction in artifact path: ' + relative)
    _require(path.resolve().is_relative_to(root.resolve()), 'artifact escaped root')
    return path


def _read(root, relative):
    return json.loads(_safe(root, relative).read_text(encoding='utf-8'))


def _original(campaign):
    _require(campaign in SEAL_HASHES, 'campaign outside fixed whitelist')
    path = HERE.parent / campaign
    _require(not path.is_symlink() and not path.is_junction(), 'linked source campaign')
    _require(path.resolve() == HERE.parent.resolve() / campaign, 'source campaign escaped parent')
    return path


def _bundle(campaign):
    _require(campaign in SEAL_HASHES, 'unknown bundle campaign')
    return _safe(HERE, 'referenced-evidence/' + campaign)


def _seal(root, campaign):
    _require(_sha(_safe(root, 'evaluation-seal.json')) == SEAL_HASHES[campaign],
             'historical seal changed: ' + campaign)
    seal = _read(root, 'evaluation-seal.json')
    _require(seal['candidate_sha'] == SOURCE_TREE_SHA, 'historical candidate changed')
    return seal


def _retained_seal(root, campaign):
    marker = '/docs/evals/' + campaign + '/'
    retained = {}
    for path, digest in _seal(root, campaign)['files'].items():
        normalized = path.replace('\\', '/')
        if marker in normalized:
            relative = normalized.split(marker, 1)[1]
            _safe(root, relative)
            retained[relative] = digest
    _require(len(retained) == {R3: 69, R4: 75, R5: 76}[campaign], 'incomplete retained seal')
    return retained


def _absence(campaign):
    if campaign == R5:
        return ['blocks/full-general.results.json', 'blocks/full-general.gate.json']
    label = 'full-b8d' if campaign == R3 else 'b0'
    names = ['blocks/' + label + '.results.json', 'blocks/' + label + '.gate.json']
    if campaign == R3:
        names.append('blocks/full-b8d.ids.jsonl')
    return names


def _whitelist(root, campaign):
    files = set(_retained_seal(root, campaign))
    files.update(('evaluation-seal.json', 'preflight.json', 'postgresql-start.json',
                  'private-postgresql/postgresql.conf', 'private-postgresql/pg_hba.conf',
                  'STOP.json', 'final-classification.json', 'cleanup.json'))
    if campaign == R5:
        files.update(('native-closure.json', 'resource-observer-closure.json',
                      'awake-request/closure.json', 'delivery-verification.json'))
    for label, source in REUSED.items():
        if source != campaign:
            continue
        files.update('blocks/' + label + suffix for suffix in
                     ('.command.json', '.command.log', '.gate.json'))
        files.add('monitor-' + label + '.json')
        files.update(kind + '-' + when + '-' + label + '.json'
                     for kind in ('integrity', 'dependency-check', 'seal-check')
                     for when in ('before', 'after'))
        if label in COUNTS:
            files.update((label + '-selected.json', 'blocks/' + label + '.results.json'))
            files.add('blocks/' + (label + '.ids.jsonl' if label != 'directed'
                                  else 'directed.results.passed.jsonl'))
        if label == 'directed':
            files.update('blocks/directed' + suffix for suffix in
                         ('.exit.json', '.selected.json', '.results.inventory.json',
                          '.results.sources.json', '.results.b9a-pipeline.jsonl',
                          '.results.b9a-processes.jsonl', '.results.b9b-corpus.jsonl',
                          '.results.b9c-corpus.jsonl', '.results.b9c-processes.jsonl'))
    interrupted = {R3: 'full-b8d', R4: 'b0', R5: 'full-general'}[campaign]
    files.update(('blocks/' + interrupted + '.command.json',
                  'blocks/' + interrupted + '.command.log', 'monitor-' + interrupted + '.json'))
    if campaign == R4:
        files.add('blocks/b0.ids.jsonl')
        recovery = _read(root, 'preparation-recovery.json')
        files.update(recovery['prior_receipts_sha256'])
        files.update(row['preserved_before_source'] for row in recovery['source_changes'].values()
                     if row.get('preserved_before_source'))
        files.add('clock-recovery-observation.json')
    if campaign == R5:
        files.update(('blocks/full-general.ids.jsonl',
                      'diagnostics/notification-clock-proposal.patch',
                      'diagnostics/notification-clock-classification.json'))
    for relative in files:
        _safe(root, relative)
    return files


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _resources(snapshot):
    _require(snapshot['physical_available'] >= 2 * GIB and snapshot['disk_available'] >= GIB,
             'historical command crossed a resource reserve')


def _audit_block(root, label):
    command = _read(root, 'blocks/' + label + '.command.json')
    gate = _read(root, 'blocks/' + label + '.gate.json')
    _require(command['state'] == 'COMPLETED' and command['exit_code'] == 0 and
             command.get('invalidating_incident') is None and
             command['candidate_sha'] == SOURCE_TREE_SHA and command['formal_run_number'] == 1,
             'command is not an eligible completed PASS: ' + label)
    _require(gate['state'] == 'PASS' and gate['label'] == label, 'gate not PASS: ' + label)
    rows = _read(root, 'monitor-' + label + '.json')
    _require(bool(rows), 'missing monitor samples: ' + label)
    previous = None
    for row in rows:
        _resources(row['host'])
        skew = row['wall_minus_monotonic_seconds']
        _require(_number(skew) and abs(skew) <= 1, 'clock incident: ' + label)
        awake = row['awake']
        _require(awake['state'] == 'ACTIVE_CONFIRMED' and
                 _number(awake['sample_age_seconds']) and 0 <= awake['sample_age_seconds'] <= 10,
                 'awake confirmation invalid: ' + label)
        stamp = row['host']['utc_epoch_seconds']
        _require(previous is None or 0 <= stamp - previous <= 10,
                 'monitor discontinuity within reused block: ' + label)
        previous = stamp
    _resources(command['resources_before']['host'])
    _resources(command['resources_after']['host'])
    _require(command['resources_after']['awake']['state'] == 'ACTIVE_CONFIRMED',
             'awake unavailable after reused command')
    seal = _read(root, 'evaluation-seal.json')
    expected = {'integrity': 3332, 'dependency-check': len(_read(root, 'dependency-files.json')['files']),
                'seal-check': len(seal['files'])}
    for kind, count in expected.items():
        for when in ('before', 'after'):
            check = _read(root, kind + '-' + when + '-' + label + '.json')
            _require(check.get('checked_files', check.get('checked')) == count and
                     check.get('mismatches') == [], 'incomplete integrity witness: ' + label)
    argv = command['argv']
    checks = {'django-check': ['check'], 'migration-drift': ['makemigrations', '--check', '--dry-run'],
              'migrate': ['migrate', '--no-input'], 'billing-schema': ['audit_billing_schema', '--json']}
    if label in checks:
        _require(argv[3:] == ['-B', 'manage.py', *checks[label]], 'check command changed')
    elif label == 'directed':
        _require(argv[3:11] == ['-B', '-m', 'apps.agent.tests.run_b9a_acceptance', '--suite',
                               'targeted', '--database', 'test_b8b_b9i_directed', '--ids-file'] and
                 len(argv) == 14 and PureWindowsPath(argv[11]).name == 'directed-selected.json' and
                 argv[12] == '--output', 'directed command changed')
    else:
        databases = {'full-b8b': 'test_b8b_b9i_full', 'full-b8c': 'test_b8c_b9i_full',
                     'full-b8d': 'test_b8d_b9i_full', 'full-b8e': 'test_b8e_b9i_full'}
        _require(len(argv) == 7 and argv[3] == '-B' and
                 PureWindowsPath(argv[4]).name == 'recorded_suite.py' and
                 argv[5:] == [label, databases.get(label, 'test_b9i_' + label)],
                 'suite command changed: ' + label)
    if label in COUNTS:
        selected = _read(root, label + '-selected.json')
        result = _read(root, 'blocks/' + label + '.results.json')
        count = COUNTS[label]
        _require(len(selected) == count == len(set(selected)) and result['tests'] == count and
                 len(result['test_ids']) == count and set(result['test_ids']) == set(selected) and
                 result['exit_code'] == 0 and gate['tests'] == count,
                 'incomplete result inventory: ' + label)
        _require(all(not result.get(key, 0) for key in
                     ('failures', 'errors', 'skips', 'xfail', 'xpass', 'failed_ids')) and
                 not gate.get('skips'), 'non-PASS outcomes present: ' + label)
        journal = 'blocks/' + (label + '.ids.jsonl' if label != 'directed'
                               else 'directed.results.passed.jsonl')
        outcomes = [json.loads(line) for line in _safe(root, journal).read_text(encoding='utf-8').splitlines()
                    if line.strip()]
        ids = [row.get('test_id', row.get('id')) for row in outcomes]
        _require(len(ids) == count and set(ids) == set(selected) and
                 all(row.get('status', row.get('outcome')) in ('ok', 'PASS') for row in outcomes),
                 'journal does not prove exact PASS inventory: ' + label)
        if label == 'directed':
            sources = _read(root, 'blocks/directed.results.sources.json')
            candidate = {row['path']: row['sha256'] for row in _read(root, 'candidate-sources.json')['files']}
            _require(all(candidate.get(path) == digest for path, digest in sources.items()) and
                     _read(root, 'blocks/directed.results.inventory.json') == selected and
                     _read(root, 'blocks/directed.selected.json') == selected,
                     'directed source/inventory mismatch')
        else:
            _require(result['candidate_sha'] == SOURCE_TREE_SHA, 'suite result candidate differs')
    return {'state': 'PASS', 'tests': COUNTS.get(label, 0), 'monitor_samples': len(rows),
            'minimum_ram_bytes': min(row['host']['physical_available'] for row in rows),
            'minimum_disk_bytes': min(row['host']['disk_available'] for row in rows),
            'maximum_clock_skew_seconds': max(abs(row['wall_minus_monotonic_seconds']) for row in rows)}


def _audit_source(root, campaign):
    retained = _retained_seal(root, campaign)
    _require(all(_sha(_safe(root, path)) == digest for path, digest in retained.items()),
             'historical sealed input drift: ' + campaign)
    _require(_read(root, 'preflight.json')['state'] == 'PASS', 'historical preflight not PASS')
    stopped = _read(root, 'STOP.json')
    label = {R3: 'full-b8d', R4: 'b0', R5: 'full-general'}[campaign]
    reason = {R3: 'Memory reserve exhausted', R4: 'Backing disk reserve exhausted',
              R5: 'Owned awake request unavailable: RuntimeError: Awake heartbeat stale or clock mismatch'}[campaign]
    _require(stopped['state'] == 'PENDING' and stopped['phase'] == label and stopped['cause'] == reason,
             'historical interruption classification changed')
    command = _read(root, 'blocks/' + label + '.command.json')
    _require(command['invalidating_incident'] == reason, 'interrupted command evidence changed')
    for name in _absence(campaign):
        _require(not _safe(root, name).exists(), 'unexpected later gate/result must not be hidden: ' + name)
    if campaign == R4:
        _require(not _safe(root, 'blocks/b0.ids.jsonl').read_text(encoding='utf-8').strip(),
                 'later B0 outcomes require explicit classification')
    if campaign == R5:
        for name in ('cleanup.json', 'native-closure.json', 'resource-observer-closure.json',
                     'delivery-verification.json'):
            _require(_read(root, name)['state'] == 'PASS', 'r5 closure incomplete: ' + name)
        _require(_read(root, 'native-closure.json')['host_clock_configuration_changed'] is False,
                 'r5 native clock configuration restoration not proven')
        awake = _read(root, 'awake-request/closure.json')
        _require(awake['state'] == 'PASS_API_REQUEST_AND_RESTORATION' and
                 awake['matches_original_thread_state'] is True, 'r5 awake restoration incomplete')
        final = _read(root, 'final-classification.json')
        _require(final.get('decision') == 'PENDING' and final.get('product_failure_established') is False,
                 'r5 final classification not preserved')
        outcomes = [json.loads(line) for line in _safe(root, 'blocks/full-general.ids.jsonl').read_text(
            encoding='utf-8').splitlines() if line.strip()]
        errors = [row for row in outcomes if row.get('outcome') in ('ERROR', 'FAIL')]
        _require(len(errors) == 1 and errors[0]['id'] == FIXTURE_TEST and
                 errors[0]['outcome'] == 'ERROR' and
                 'appointment_end_after_start' in errors[0].get('traceback', ''),
                 'r5 general contains an additional unclassified failure')
    return {name: _audit_block(root, name) for name, source in REUSED.items() if source == campaign}


def validate_references():
    """Rehash every bundled reference and every original that is still present."""
    global _MANIFEST_CACHE
    _MANIFEST_CACHE = None
    manifest = _read(HERE, 'reuse-manifest.json')
    _require(manifest.get('schema') == SCHEMA and manifest.get('candidate_tree') == TREE_SHA and
             manifest.get('source_candidate_tree') == SOURCE_TREE_SHA and
             manifest.get('backend_only') is True and manifest.get('continuous_campaign') is False,
             'invalid reuse manifest contract')
    _require(manifest.get('blocks') == {label: {'campaign': campaign, 'origin': 'REFERENCED_PASS'}
                                      for label, campaign in REUSED.items()} and
             set(manifest.get('sources', {})) == set(SEAL_HASHES), 'reuse mapping changed')
    _require(_sha(_safe(HERE, 'reuse-validation.json')) == manifest['validation_sha256'] and
             _read(HERE, 'reuse-validation.json')['state'] == 'PASS', 'reuse validation drift')
    proof = manifest.get('fixture_clock_equivalence', {})
    _require(proof == _read(HERE, 'reuse-validation.json')['inputs']['fixture_clock_equivalence'] and
             proof.get('state') == 'PASS' and proof.get('allowed_path') == FIXTURE_PATH and
             proof.get('source_candidate_tree') == SOURCE_TREE_SHA and
             proof.get('accepted_candidate_tree') == TREE_SHA and
             proof.get('original_sha256') == OLD_FIXTURE_SHA and
             proof.get('corrected_sha256') == NEW_FIXTURE_SHA and
             proof.get('body_AST_identical') is True and
             proof.get('other_git_blobs_identical') == 3331,
             'cross-candidate fixture proof changed')
    _authorization()
    _require(_sha(_safe(HERE, 'fixture-clock-authorization.json')) == proof['authorization_sha256'] and
             _sha(_safe(HERE, 'candidate-input.json')) == proof['candidate_input_sha256'],
             'fixture authorization or candidate declaration drift')
    for campaign, source in manifest['sources'].items():
        _require(source['original_relative'] == '../' + campaign and
                 source['bundle_relative'] == 'referenced-evidence/' + campaign and
                 source['expected_absent'] == _absence(campaign), 'source path outside whitelist')
        bundle = _bundle(campaign)
        original = _original(campaign)
        _require(set(source['files']) == _whitelist(bundle, campaign), 'artifact whitelist changed')
        for relative, digest in source['files'].items():
            _require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) is not None,
                     'invalid artifact digest')
            _require(_sha(_safe(bundle, relative)) == digest, 'bundled reference changed: ' + relative)
            if original.exists():
                _require(_sha(_safe(original, relative)) == digest, 'original reference changed: ' + relative)
        for relative in source['expected_absent']:
            _require(not _safe(bundle, relative).exists() and
                     (not original.exists() or not _safe(original, relative).exists()),
                     'a later result/gate would be hidden')
    raw = _safe(HERE, 'reuse-manifest.json').read_bytes()
    _require(json.loads(raw) == manifest, 'manifest changed while validating references')
    _MANIFEST_CACHE = (hashlib.sha256(raw).hexdigest(), raw)
    return manifest


def _resolved_manifest():
    """Resolve from a phase-validated manifest; never rehash the bundle per lookup."""
    if _MANIFEST_CACHE is None:
        validate_references()
    raw = _safe(HERE, 'reuse-manifest.json').read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == _MANIFEST_CACHE[0],
             'manifest changed since phase validation')
    return json.loads(_MANIFEST_CACHE[1])


def source_for(label):
    """Return the current campaign or the verified historical evidence bundle."""
    _require(isinstance(label, str) and re.fullmatch('[a-z0-9][a-z0-9_-]*', label) is not None,
             'invalid block label')
    if not (HERE / 'reuse-manifest.json').exists():
        return HERE
    _resolved_manifest()
    return _bundle(REUSED[label]) if label in REUSED else HERE


def block_path(label, suffix):
    _require(isinstance(suffix, str) and re.fullmatch(r'\.[a-zA-Z0-9_.-]+', suffix) is not None and
             '..' not in suffix, 'invalid block suffix')
    source = source_for(label)
    if label == 'full-general' and suffix == '.command.json':
        _require(source == HERE, 'case assembler must be a current invocation')
        relative = 'blocks/full-general-assemble.command.json'
    else:
        relative = 'blocks/' + label + suffix
    path = _safe(source, relative)
    if source != HERE:
        files = _resolved_manifest()['sources'][REUSED[label]]['files']
        _require(relative in files, 'block artifact outside referenced whitelist')
        _require(_sha(path) == files[relative], 'referenced block artifact changed')
    return path


def read_block(label, suffix='.gate.json'):
    return json.loads(block_path(label, suffix).read_text(encoding='utf-8'))


def is_reused(label):
    return label in REUSED and source_for(label) != HERE


def provenance(label):
    source = source_for(label)
    reused = source != HERE
    if label == 'full-general':
        _require(not reused, 'case aggregate cannot masquerade as a reused complete block')
        from case_resumption import provenance as case_provenance
        details = case_provenance()
        _require(details.get('origin') == 'COMPOSITE_CASE_EVIDENCE',
                 'case aggregate provenance is absent or inconsistent')
        return {**details, 'origin': 'COMPOSITE_CASE_EVIDENCE',
                'command_origin': 'CURRENT_ASSEMBLER', 'campaign': HERE.name,
                'artifactdir': str(HERE / 'blocks'),
                'command_receipt': 'blocks/full-general-assemble.command.json',
                'case_manifest': 'case-resumption-manifest.json',
                'accepted_historical_evidence_limitation': True}
    return {'origin': 'REFERENCED_PASS' if reused else 'CURRENT',
            'campaign': REUSED[label] if reused else HERE.name,
            'artifactdir': str(source / 'blocks'),
            'tested_candidate_tree': SOURCE_TREE_SHA if reused else TREE_SHA,
            'accepted_candidate_tree': TREE_SHA,
            'fixture_clock_equivalence': ('reuse-validation.json#inputs.fixture_clock_equivalence'
                                          if reused else None)}


def candidate_compatible(label, receipt_sha):
    """Accept an old SHA only for the thirteen validated referenced PASS blocks."""
    source = source_for(label)
    expected = TREE_SHA
    if source != HERE:
        _require(label in REUSED, 'old candidate not authorized for this block')
        proof = _resolved_manifest()['fixture_clock_equivalence']
        _require(proof['state'] == 'PASS' and proof['source_candidate_tree'] == SOURCE_TREE_SHA and
                 proof['accepted_candidate_tree'] == TREE_SHA and
                 proof['allowed_path'] == FIXTURE_PATH and proof['body_AST_identical'] is True,
                 'cross-candidate equivalence unavailable')
        expected = SOURCE_TREE_SHA
    _require(receipt_sha == expected, 'receipt candidate incompatible with block provenance: ' + label)
    return True


def _authorization():
    authorization = _read(HERE, 'fixture-clock-authorization.json')
    expected = {'state': 'USER_AUTHORIZED_APPLIED_AND_STAGED',
                'source_candidate_tree': SOURCE_TREE_SHA, 'current_candidate_tree': TREE_SHA,
                'allowed_path': FIXTURE_PATH, 'original_sha256': OLD_FIXTURE_SHA,
                'corrected_sha256': NEW_FIXTURE_SHA, 'patch_sha256': CLOCK_PATCH_SHA,
                'body_AST_identical': True, 'all_other_3331_blobs_identical': True,
                'product_runtime_locks_assertions_changed': False,
                'no_previous_error_discarded': True, 'complete_general_rerun_required': True}
    _require(all(authorization.get(key) == value for key, value in expected.items()) and
             bool(authorization.get('user')), 'fixture authorization changed or incomplete')
    candidate = _read(HERE, 'candidate-input.json')
    _require(candidate['candidate_tree'] == TREE_SHA and
             candidate['previous_candidate_tree'] == SOURCE_TREE_SHA and
             candidate['only_new_change'] == FIXTURE_PATH, 'candidate authorization scope changed')
    return authorization


def _fixture_transform(corrected):
    """Invert only the approved imports/decorator, proving the entire old source."""
    _require(hashlib.sha256(corrected).hexdigest() == NEW_FIXTURE_SHA,
             'corrected fixture bytes are not the authorized proposal')
    text = corrected.decode('utf-8')
    original = text
    changes = (
        ('from datetime import datetime, timedelta, timezone as dt_timezone\n',
         'from datetime import timedelta\n'),
        ('from unittest.mock import patch\n', ''),
        ("    @patch(\n        'django.utils.timezone.now',\n"
         '        return_value=datetime(2026, 10, 17, 12, 0, tzinfo=dt_timezone.utc),\n'
         '    )\n    def test_upcoming_window(self, _now):\n',
         '    def test_upcoming_window(self):\n'),
    )
    for after, before in changes:
        _require(original.count(after) == 1, 'fixture contains an unapproved import/decorator change')
        original = original.replace(after, before, 1)
    raw = original.encode('utf-8')
    _require(hashlib.sha256(raw).hexdigest() == OLD_FIXTURE_SHA,
             'fixture inverse differs from the entire original source')
    old_ast, new_ast = ast.parse(original), ast.parse(text)

    def method(module):
        cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and
                   node.name == 'DerivedFeedTests')
        return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and
                    node.name == 'test_upcoming_window')

    def ids(module):
        return sorted((cls.name, node.name) for cls in module.body if isinstance(cls, ast.ClassDef)
                      for node in cls.body if isinstance(node, ast.FunctionDef) and
                      node.name.startswith('test_'))

    _require([ast.dump(node, include_attributes=False) for node in method(old_ast).body] ==
             [ast.dump(node, include_attributes=False) for node in method(new_ast).body] and
             ids(old_ast) == ids(new_ast), 'fixture body/assertions/test IDs changed')
    git_blob = lambda data: hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return {'original_sha256': OLD_FIXTURE_SHA, 'corrected_sha256': NEW_FIXTURE_SHA,
            'source_git_blob': git_blob(raw), 'accepted_git_blob': git_blob(corrected),
            'source_bytes': len(raw), 'accepted_bytes': len(corrected),
            'body_AST_identical': True, 'all_test_ids_identical': True}


def _candidate(root, *, current=False):
    record = _read(root, 'candidate-sources.json')
    rows = record['files']
    files = {row['path']: row['sha256'] for row in rows}
    normalized = dict(files)
    if current:
        _require(files.get(FIXTURE_PATH) == NEW_FIXTURE_SHA, 'current fixture SHA differs')
        normalized[FIXTURE_PATH] = OLD_FIXTURE_SHA
    _require(record['candidate_sha'] == (TREE_SHA if current else SOURCE_TREE_SHA) and not record['mismatches'] and
             len(rows) == len(files) == 3332 and
             _digest(normalized) == '8aac2863cc2c12aa7da30dab33fcb429c5e3ed8c667c6b8f9c1001b5e75c4ba7',
             'candidate file map differs')
    return files


def _candidate_blobs(source, proof):
    old = {row['path']: row for row in _read(source, 'candidate-sources.json')['files']}
    new = {row['path']: row for row in _read(HERE, 'candidate-sources.json')['files']}
    _require(set(old) == set(new) and len(old) == 3332, 'candidate blob inventory changed')
    _require(all(old[path] == new[path] for path in old if path != FIXTURE_PATH),
             'one of the other 3331 Git blobs/modes/bytes changed')
    before, after = old[FIXTURE_PATH], new[FIXTURE_PATH]
    _require(set(before) == set(after) and before['mode'] == after['mode'] and
             before['sha256'] == OLD_FIXTURE_SHA and after['sha256'] == NEW_FIXTURE_SHA and
             before['git_blob'] == proof['source_git_blob'] and
             after['git_blob'] == proof['accepted_git_blob'] and
             before['bytes'] == proof['source_bytes'] and after['bytes'] == proof['accepted_bytes'],
             'authorized fixture blob metadata differs')


def _partition(root, name, *, current=False):
    data = _read(root, name)
    _require(data.pop('candidate_tree') == (TREE_SHA if current else SOURCE_TREE_SHA),
             'partition candidate differs')
    return data


def _fixture_equivalence(tree, source):
    _authorization()
    proof = _fixture_transform(_safe(tree, FIXTURE_PATH).read_bytes())
    _require(_sha(_safe(source, 'diagnostics/notification-clock-proposal.patch')) == CLOCK_PATCH_SHA,
             'authorized proposal patch changed')
    classification_path = _safe(source, 'diagnostics/notification-clock-classification.json')
    _require(_sha(classification_path) ==
             '366d5ccf9b88e9aff58f440f6eb6fa42e42f879ebfeaf01a406bffa122231f26',
             'historical fixture diagnosis changed')
    selected_counts = {}
    for label in REUSED:
        if label in COUNTS:
            ids = _read(HERE, label + '-selected.json')
            _require(len(ids) == COUNTS[label] and
                     not any(value.startswith('apps.notifications.tests.test_notifications.') for value in ids),
                     'referenced selection can execute the changed fixture: ' + label)
            selected_counts[label] = len(ids)
    proof.update(state='PASS', source_candidate_tree=SOURCE_TREE_SHA, accepted_candidate_tree=TREE_SHA,
                 allowed_path=FIXTURE_PATH, patch_sha256=CLOCK_PATCH_SHA,
                 authorization_sha256=_sha(_safe(HERE, 'fixture-clock-authorization.json')),
                 candidate_input_sha256=_sha(_safe(HERE, 'candidate-input.json')),
                 authorization='fixture-clock-authorization.json',
                 unaffected_selected_test_counts=selected_counts,
                 other_git_blobs_identical=3331,
                 mechanism='Only the unselected method receives a scoped clock mock; imports do not activate it',
                 original_error_preserved=True, complete_general_rerun_required=True)
    return proof


def _python_files(root):
    assembly = _read(root, 'assembly.json')
    python = PureWindowsPath(assembly['python']).parent
    result = {}
    for path, digest in _read(root, 'dependency-files.json')['files'].items():
        item = PureWindowsPath(path)
        if item.is_relative_to(python):
            relative = item.relative_to(python).as_posix()
            _require(relative not in result, 'duplicate Python dependency path')
            result[relative] = digest
    _require(len(result) == 10083, 'private Python file inventory changed')
    return result


def _configuration(root):
    config = _read(root, 'effective-configuration.json')
    port = config['DATABASES']['default']['PORT']
    _require(str(port) == str(_read(root, 'assembly.json')['port']), 'configuration port mismatch')
    config['DATABASES']['default']['PORT'] = 'PRIVATE_PORT'
    return config


def _package_versions(environment):
    return {re.sub('[-_.]+', '-', row['name']).lower(): row['version']
            for row in environment['packages']}


def _pg_files(root):
    base = PureWindowsPath(_read(root, 'assembly.json')['pg_bin'])
    files = {PureWindowsPath(path).name: digest
             for path, digest in _read(root, 'evaluation-seal.json')['files'].items()
             if PureWindowsPath(path).parent == base and
             PureWindowsPath(path).suffix.lower() in ('.exe', '.dll')}
    _require(files and all(name in files for name in ('postgres.exe', 'pg_ctl.exe', 'initdb.exe', 'psql.exe')),
             'PostgreSQL toolchain proof missing')
    return files


def _pg_configuration(root):
    config = _safe(root, 'private-postgresql/postgresql.conf').read_bytes()
    normalized, count = re.subn(rb'(?m)^(port[ \t]*=[ \t]*)[0-9]+([ \t]*\r?)$',
                                rb'\1PRIVATE_PORT\2', config)
    _require(count == 1, 'private PostgreSQL port configuration is ambiguous')
    return {'postgresql.conf': hashlib.sha256(normalized).hexdigest(),
            'pg_hba.conf': _sha(_safe(root, 'private-postgresql/pg_hba.conf'))}


def validate_current_inputs():
    """Verify the live prepared backend against both historical backend inputs."""
    if (HERE / 'reuse-manifest.json').exists():
        validate_references()
        sources = {campaign: _bundle(campaign) for campaign in SEAL_HASHES}
    else:
        sources = {campaign: _original(campaign) for campaign in SEAL_HASHES}
        for campaign, source in sources.items():
            _audit_source(source, campaign)
    assembly = _read(HERE, 'assembly.json')
    work = Path(assembly['workspace']).resolve()
    tree = Path(assembly['tree']).resolve()
    python = Path(assembly['python']).resolve().parent
    _require(assembly['candidate_sha'] == TREE_SHA and assembly['platform'] == 'Windows native' and
             assembly['wsl_invoked'] is False and tree == work / 'src' and python == work / 'python',
             'current private backend layout differs')
    candidate = _candidate(HERE, current=True)
    _require(all(_sha(_safe(tree, path)) == digest for path, digest in candidate.items()),
             'live candidate source drift')
    fixture = _fixture_equivalence(tree, sources[R5])
    pyfiles = _python_files(HERE)
    _require(all(_sha(_safe(python, path)) == digest for path, digest in pyfiles.items()),
             'live private Python dependency drift')
    environment = _read(HERE, 'python-environment.json')
    lock = _safe(tree, 'backend/requirements.lock')
    lock_hash = _sha(lock)
    pins = {}
    for line in lock.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s]+)', line)
        if match:
            pins[re.sub('[-_.]+', '-', match[1]).lower()] = match[2]
    _require(len(pins) == 34 and pins == environment['required_lock_versions'] and
             all(_package_versions(environment).get(name) == version for name, version in pins.items()) and
             environment['state'] == 'PASS' and environment['private_prefix_verified'] is True and
             not environment['lock_differences'] and environment['requirements_sha256'] == lock_hash and
             Path(environment['executable']).resolve() == python / 'python.exe' and
             Path(environment['base_executable']).resolve() == python / 'python.exe',
             'current pinned/private Python environment invalid')
    for name in ('interpreter-preflight.json', 'native-preflight.json'):
        _require(_read(HERE, name)['state'] == 'PASS', 'current preparation incomplete: ' + name)
    config = _configuration(HERE)
    toolchain = _read(HERE, 'toolchain.json')
    pg = Path(assembly['pg_bin'])
    pg_config = _pg_configuration(HERE)
    pg_receipt = _read(HERE, 'postgresql-preflight.json')
    _require(pg_receipt['state'] == 'PASS' and pg_receipt['private_cluster'] is True and
             str(pg_receipt['port']) == str(assembly['port']) and
             pg_receipt['values'][0].startswith('PostgreSQL 16.15,') and
             Path(pg_receipt['values'][1]).resolve() == work / 'pgdata' and
             pg_receipt['values'][2:] == ['on', 'on', 'on'],
             'current private PostgreSQL durability preflight invalid')
    for name in ('postgresql.conf', 'pg_hba.conf'):
        _require(_sha(work / 'pgdata' / name) == _sha(_safe(HERE, 'private-postgresql/' + name)),
                 'live PostgreSQL configuration drift: ' + name)
    metadata = {}
    for campaign, source in sources.items():
        oldenv = _read(source, 'python-environment.json')
        historical = _candidate(source)
        _candidate_blobs(source, fixture)
        _require({path: digest for path, digest in candidate.items() if path != FIXTURE_PATH} ==
                 {path: digest for path, digest in historical.items() if path != FIXTURE_PATH} and
                 historical[FIXTURE_PATH] == OLD_FIXTURE_SHA and pyfiles == _python_files(source) and
                 config == _configuration(source) and pins == oldenv['required_lock_versions'] and
                 pg_config == _pg_configuration(source) and
                 environment['python_version'] == oldenv['python_version'] and
                 _package_versions(environment) == _package_versions(oldenv),
                 'backend source/dependency/configuration equivalence failed: ' + campaign)
        for key in ('node', 'pnpm', 'python', 'postgres', 'node_archive_sha256', 'pnpm_integrity'):
            _require(toolchain[key] == _read(source, 'toolchain.json')[key], 'toolchain version differs: ' + key)
        binaries = _pg_files(source)
        _require({path.name for path in pg.iterdir() if path.suffix.lower() in ('.exe', '.dll')} == set(binaries) and
                 all(_sha(pg / name) == digest for name, digest in binaries.items()),
                 'live PostgreSQL toolchain drift')
        _require(_sha(HERE / 'recorded_suite.py') == _sha(source / 'recorded_suite.py') and
                 _partition(HERE, 'full-partition-contract.json', current=True) ==
                 _partition(source, 'full-partition-contract.json') and
                 _partition(HERE, 'full-partition.json', current=True) ==
                 _partition(source, 'full-partition.json'),
                 'runner or full partition contract changed')
        for name in _retained_seal(source, campaign):
            if name.endswith('-selected.json'):
                _require(_sha(_safe(HERE, name)) == _sha(_safe(source, name)), 'selection changed: ' + name)
        metadata[campaign] = {path: digest for path, digest in _read(source, 'dependency-files.json')['files'].items()
                              if path.replace('\\', '/').endswith('/node_modules/.modules.yaml')}
    return {'state': 'PASS', 'candidate_tree': TREE_SHA, 'candidate_files': 3332,
            'source_candidate_tree': SOURCE_TREE_SHA, 'fixture_clock_equivalence': fixture,
            'candidate_files_sha256': _digest(candidate), 'python_files': len(pyfiles),
            'python_files_sha256': _digest(pyfiles), 'required_pins': 34,
            'requirements_sha256': lock_hash, 'configuration_port_normalized_sha256': _digest(config),
            'postgresql_configuration_port_normalized': pg_config,
            'allowed_equivalences': ['Private workspace relocation', 'Private loopback PostgreSQL port'],
            'platform': 'Windows native', 'backend_only': True, 'frontend_dependencies_reused': False,
            'frontend_dependencies_reused_scope': 'Legacy field refers only to historical frontend results',
            'frontend_results_reused': False, 'prepared_frontend_installation_reused': True,
            'runtime_reference': 'prepared-runtime-references.json',
            'frontend_metadata_equivalence_proven': False,
            'historical_frontend_modules_metadata_hashes': metadata,
            'frontend_policy': 'All frontend result blocks run newly using the verified r6 prepared installation'}


def build_manifest():
    """Validate, copy the fixed whitelist, and record provenance before the seal."""
    for name in ('evaluation-seal.json', 'invocation-formal.json', 'STOP.json',
                 'reuse-manifest.json', 'reuse-validation.json'):
        _require(not (HERE / name).exists(), 'cannot rebuild reuse evidence: ' + name)
    inputs = validate_current_inputs()
    audits = {}
    sources = {}
    for campaign in SEAL_HASHES:
        original = _original(campaign)
        audits.update(_audit_source(original, campaign))
        bundle = _bundle(campaign)
        files = {}
        for relative in sorted(_whitelist(original, campaign)):
            source = _safe(original, relative)
            digest = _sha(source)
            target = _safe(bundle, relative)
            _require(not target.exists(), 'refusing to overwrite referenced artifact: ' + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as stream, target.open('xb') as copied:
                shutil.copyfileobj(stream, copied)
            _require(_sha(source) == digest == _sha(target), 'reference changed during copy')
            files[relative] = digest
        sources[campaign] = {'original_relative': '../' + campaign,
                             'bundle_relative': 'referenced-evidence/' + campaign,
                             'files': files, 'expected_absent': _absence(campaign)}
    validation = {'state': 'PASS', 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  'inputs': inputs, 'blocks': audits, 'reused_gate_count': 13,
                  'reused_unique_ids': 369, 'reused_full_ids': 118,
                  'continuous_campaign': False, 'application_tests_executed_by_validation': False,
                  'history_preserved': 'r3 full-b8d/r4 B0 interruptions and the r5 general fixture ERROR plus awake interruption remain visible; no FAIL is replaced'}
    validation_path = HERE / 'reuse-validation.json'
    with validation_path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(validation, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    manifest = {'schema': SCHEMA, 'state': 'VALIDATED_REFERENCED_PASS', 'candidate_tree': TREE_SHA,
                'source_candidate_tree': SOURCE_TREE_SHA,
                'fixture_clock_equivalence': inputs['fixture_clock_equivalence'],
                'backend_only': True, 'continuous_campaign': False,
                'frontend_dependencies_reused': False,
                'frontend_dependencies_reused_scope': 'Legacy field refers only to historical frontend results',
                'frontend_results_reused': False, 'prepared_frontend_installation_reused': True,
                'runtime_reference': 'prepared-runtime-references.json',
                'validation_sha256': _sha(validation_path),
                'blocks': {label: {'campaign': campaign, 'origin': 'REFERENCED_PASS'}
                           for label, campaign in REUSED.items()}, 'sources': sources}
    with (HERE / 'reuse-manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    validate_references()
    return manifest
