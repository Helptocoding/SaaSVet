"""Complete the already-preserved r5 delivery without rebuilding its archive."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


CURRENT = Path(__file__).resolve().parents[1]
REPO = CURRENT.parents[2]
HERE = CURRENT.parent / 'b9-correction-20261017-native-r5'
SHARED = {'.gitattributes', '.gitignore', 'docs/evals/b9-consolidation-2026-10-11/ACTA.md'}
PATTERN = ('docs/evals/b9-correction-20261017-native-r5/referenced-evidence/**/*.diff '
           'whitespace=-blank-at-eol,-blank-at-eof,space-before-tab,cr-at-eol')


def require(condition, message):
    if not condition:
        raise RuntimeError('complete prior delivery: ' + message)


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    return digest(path.read_bytes())


def main():
    result_path = CURRENT / 'diagnostics/complete-prior-delivery.json'
    require(not result_path.exists(), 'completion already recorded; no silent rerun')
    previous = read('delivery-verification.json')
    require(previous['state'] == 'VERIFYING', 'prior delivery is not awaiting tail verification')
    selection_receipt = read('git-selection.json')
    require(selection_receipt['explicit'] is True, 'selection is not explicit')
    selection = selection_receipt['paths']
    require(len(selection) == len(set(selection)) == previous['selected_paths'], 'selection changed')
    baseline = read('index-before-delivery.json')
    manifest = read('preservation-manifest.json')
    files = manifest['files']
    proof = read('preservation-verification.json')
    require(all(proof[name]['state'] == 'PASS' and proof[name]['mismatches'] == [] and
                proof[name]['recovered_members'] == len(files)
                for name in ('internal_restore', 'actual_cli_restore')),
            'original independent recovery proofs are not both PASS')
    require(proof['package_sha256'] == manifest['archive_sha256'], 'recovery archive identity differs')
    original = read('checkout-before.json')
    native = read('native-closure.json')
    preservation = read('preservation-of-prior-work.json')
    require(native['state'] == 'PASS' and native['host_clock_configuration_changed'] is False and
            not preservation['prior_campaign_mismatches'] and preservation['unrelated_unchanged'],
            'prior cleanup/preservation prerequisite is incomplete')
    deliver = HERE / 'deliver_native.py'
    source_sha = sha(deliver)
    sealed = [value for name, value in read('evaluation-seal.json')['files'].items()
              if Path(name).resolve() == deliver.resolve()]
    require(sealed == [source_sha], 'original delivery helper differs from its seal')
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location('r5_original_delivery_without_main', deliver)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.HERE.resolve() == HERE.resolve() and module.REPO.resolve() == REPO.resolve() and
            module.SHARED == SHARED, 'original delivery module resolved an unexpected scope')
    require(module.run('git', 'rev-parse', 'HEAD').decode().strip() == original['head'] and
            module.run('git', 'branch', '--show-current').decode().strip() == original['branch'],
            'repository HEAD/branch differs from the original delivery')
    archive_hash = hashlib.sha256()
    package_sha_before = {}
    for part in manifest['parts']:
        path = HERE / part['path']
        require(path.resolve().is_relative_to(HERE.resolve()), 'archive part escaped campaign')
        content = path.read_bytes()
        require(len(content) == part['bytes'] and digest(content) == part['sha256'], 'archive part drift')
        archive_hash.update(content)
        package_sha_before[part['path']] = digest(content)
    require(archive_hash.hexdigest() == manifest['archive_sha256'], 'preserved archive checksum differs')
    preserved_metadata = {name: sha(HERE / name) for name in
                          ('preservation-manifest.json', 'preservation-verification.json',
                           'index-before-delivery.json', 'git-selection.json', 'evaluation-seal.json')}
    attributes = REPO / '.gitattributes'
    before = attributes.read_bytes()
    require(PATTERN not in before.decode('utf-8'), 'specific raw referenced diff rule already exists')
    addition = ('' if before.endswith(b'\n') else '\n') + PATTERN + '\n'
    with attributes.open('ab') as stream:
        stream.write(addition.encode('utf-8'))
    require(attributes.read_bytes() == before + addition.encode('utf-8'), 'attribute prefix changed')
    module.run('git', 'add', '--', '.gitattributes')
    module.run('git', 'diff', '--cached', '--check')

    # Original tail validations: unchanged baseline, explicit selected bytes,
    # preserved archive members, final receipt staging and another diff check.
    staged = module.staged_blobs(set(selection) | set(baseline))
    prior_drift = [name for name, value in baseline.items()
                   if name not in SHARED and digest(staged[name]) != value]
    mismatches, normalized = [], []
    for name in selection:
        local = (REPO / name).read_bytes()
        if local != staged[name]:
            if name in ('.gitattributes', '.gitignore') and local.replace(b'\r\n', b'\n') == staged[name].replace(b'\r\n', b'\n'):
                normalized.append(name)
            else:
                mismatches.append(name)
    drift = [name for name, row in files.items() if digest((HERE / name).read_bytes()) != row['sha256']]
    require(not prior_drift and not mismatches and not drift,
            'original delivery tail validation failed: ' + str((prior_drift, mismatches, drift)))
    module.save('delivery-verification.json', {
        'state': 'PASS', 'selected_paths': len(selection),
        'evidence_git_blobs_equal_local_bytes': True, 'root_text_normalized_paths': normalized,
        'prior_staged_paths_checked': len(baseline),
        'prior_staged_drift_outside_three_delivery_files': prior_drift,
        'evidence_drift': drift, 'cached_diff_check_exit_code': 0,
        'recovered_members': proof['internal_restore']['recovered_members'],
        'commits_created': 0, 'pushes_performed': 0})
    relative = (HERE / 'delivery-verification.json').relative_to(REPO).as_posix()
    module.run('git', 'add', '--', relative)
    require(module.run('git', 'show', ':' + relative) == (HERE / 'delivery-verification.json').read_bytes(),
            'final delivery receipt Git blob differs from its bytes')
    module.run('git', 'diff', '--cached', '--check')
    require(sha(deliver) == source_sha and
            all(sha(HERE / name) == value for name, value in preserved_metadata.items()) and
            all(sha(HERE / name) == value for name, value in package_sha_before.items()),
            'original source/archive/manifest changed')
    result = {'state': 'PASS', 'completed_campaign': HERE.name,
              'selected_paths': len(selection), 'recovered_members': len(files),
              'prior_staged_paths_checked': len(baseline), 'prior_staged_drift': prior_drift,
              'evidence_drift': drift, 'cached_diff_check_exit_code': 0,
              'archive_sha256': manifest['archive_sha256'], 'archive_rebuilt': False,
              'original_sealed_helper_modified': False, 'application_tests_executed': False,
              'attribute_added_only': PATTERN, 'attribute_prefix_sha256': digest(before),
              'attribute_final_sha256': sha(attributes),
              'independent_recovery_proofs_reused_without_rerun': True,
              'commits_created': 0, 'pushes_performed': 0}
    with result_path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
