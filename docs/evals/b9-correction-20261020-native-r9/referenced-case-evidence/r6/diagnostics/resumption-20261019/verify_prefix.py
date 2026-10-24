"""Read existing evidence and current bytes; write one new prefix validation receipt."""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[1]
WORK = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r6')
TREE = WORK / 'src'
SHA = '68dffd746793700071f577a58528b0f9636930db'
OUTPUT = HERE / 'prefix-validation.json'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def check_files(label, expected, manifest):
    observed = hashlib.sha256()
    mismatches = []
    started = time.monotonic()
    for index, (path, wanted) in enumerate(sorted(expected.items()), 1):
        assert re.fullmatch('[0-9a-f]{64}', wanted), str(path)
        try:
            actual = file_digest(path)
            if actual != wanted:
                mismatches.append({'path': str(path), 'expected': wanted, 'actual': actual})
        except OSError as exc:
            actual = None
            mismatches.append({'path': str(path), 'expected': wanted,
                               'error_type': type(exc).__name__, 'error': str(exc)})
        observed.update((str(path) + '\0' + str(actual) + '\n').encode('utf-8'))
        if index % 2000 == 0 or index == len(expected):
            print(f'{label}: {index}/{len(expected)} checked; mismatches={len(mismatches)}', flush=True)
    return {'manifest': manifest.relative_to(EVIDENCE).as_posix(),
            'manifest_sha256': file_digest(manifest), 'checked': len(expected),
            'mismatches': mismatches, 'actual_path_hash_rows_sha256': observed.hexdigest(),
            'actual_path_hash_rows_encoding': 'sorted native path + NUL + actual SHA256 + LF; UTF-8',
            'seconds': time.monotonic() - started,
            'scope': 'CURRENT_BYTES_ONLY; not a historical after-block guard'}


def sample_proof(relative, journal):
    path = EVIDENCE / relative
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    start, end = epoch(journal[0]['utc']), epoch(journal[-1]['utc'])
    window = [r for r in rows if start - 10 <= r['utc_epoch_seconds'] <= end + 10]
    assert window and all(a['utc_epoch_seconds'] <= b['utc_epoch_seconds']
                          for a, b in zip(rows, rows[1:]))
    times = [r['utc_epoch_seconds'] for r in rows]
    ages = []
    for entry in journal:
        moment = epoch(entry['utc'])
        index = bisect_right(times, moment) - 1
        assert index >= 0
        ages.append(moment - times[index])
    result = {'path': relative, 'sha256': digest(raw), 'total_samples': len(rows),
              'samples_in_journal_window_plus_10s': len(window),
              'first_sample': window[0], 'last_sample': window[-1],
              'maximum_gap_seconds': max(b['utc_epoch_seconds'] - a['utc_epoch_seconds']
                                         for a, b in zip(window, window[1:])),
              'maximum_prior_sample_age_at_journal_seconds': max(ages)}
    if 'physical_available' in window[0]:
        result.update(minimum_physical_available=min(r['physical_available'] for r in window),
                      samples_below_2GiB=sum(r['physical_available'] < 2 * 1024 ** 3 for r in window))
    else:
        result['api_state_always_confirmed_in_window'] = all(
            r['api_previous_state'] == '0x80000001' for r in window)
    return result


def main():
    assert not OUTPUT.exists(), 'Existing validation must not be overwritten'
    started = datetime.now(timezone.utc).isoformat()
    names = ['blocks/full-general.ids.jsonl', 'blocks/full-general.command.json',
             'full-general-selected.json', 'full-partition.json', 'candidate-sources.json',
             'dependency-files.json', 'evaluation-seal.json', 'integrity-before-full-general.json',
             'dependency-check-before-full-general.json', 'seal-check-before-full-general.json',
             'blocks/full-general.command.log']
    originals = {name: (EVIDENCE / name).read_bytes() for name in names}
    parsed = {name: json.loads(raw) for name, raw in originals.items() if name.endswith('.json')}
    journal = [json.loads(line) for line in originals[names[0]].splitlines()]
    selected = parsed['full-general-selected.json']
    ids = [row['id'] for row in journal]
    actual, expected = set(ids), set(selected)
    missing = sorted(expected - actual)
    counts = dict(Counter(row['outcome'] for row in journal))
    projection = [item for item in selected if item in actual]
    log = originals['blocks/full-general.command.log'].decode('utf-8', errors='replace').replace('\r', '')
    class_name = 'apps.users.tests.test_change_password.ChangePasswordSuccessTests.'
    class_ids = [item for item in selected if item.startswith(class_name)]
    next_id = class_name + 'test_response_includes_new_access_and_refresh_pair'
    last_id = journal[-1]['id']
    display = lambda item: item.rsplit('.', 1)[1] + ' (' + item + ') ...'
    last_index, next_index = log.rfind(display(last_id)), log.rfind(display(next_id))
    advanced = (last_index >= 0 and next_index > last_index
                and log[last_index:next_index].rstrip().endswith('ok'))
    late_errors = re.findall(r'^ERROR:.*$|\.\.\.\s+ERROR\s*$', log[max(0, last_index):], re.MULTILINE)
    post_teardown = {'log': 'blocks/full-general.command.log',
        'log_sha256': digest(originals['blocks/full-general.command.log']),
        'last_journal_pass_id': last_id, 'next_case_started_id': next_id,
        'last_case_ok_then_next_case_started': advanced,
        'later_unittest_error_markers': late_errors,
        'later_error_holder_mentions': log[max(0, last_index):].count('_ErrorHolder'),
        'journal_error_holder_ids': [item for item in ids if '_ErrorHolder' in item],
        'class_selected_ids': class_ids,
        'class_pass_ids': [r['id'] for r in journal if r['id'] in class_ids and r['outcome'] == 'PASS'],
        'class_missing_ids': [item for item in class_ids if item not in actual],
        'class_teardown_complete_claimed': False, 'class_restart_claimed': False,
        'scope': 'Observed advance beyond the last recorded case; no claim about closure of the partial class'}
    sources = parsed['candidate-sources.json']
    dependencies = parsed['dependency-files.json']
    seal = parsed['evaluation-seal.json']
    group = next(row for row in parsed['full-partition.json']['groups'] if row['label'] == 'full-general')
    assert sources['candidate_sha'] == seal['candidate_sha'] == SHA
    assert digest(originals['candidate-sources.json']) == seal['candidate_manifest_sha256']
    assert digest(originals['full-general-selected.json']) == group['selection_sha256']
    assert len(sources['files']) == 3332 and len(dependencies['files']) == 44636 and len(seal['files']) == 160
    prefix_valid = (len(selected) == len(expected) == 3213 and len(ids) == len(actual) == 2485
                    and len(missing) == 728 and not actual - expected and ids == projection
                    and counts == {'PASS': 2483, 'SKIP': 2}
                    and all(set(row) == {'id', 'outcome', 'reason', 'utc', 'traceback'} for row in journal)
                    and all(a['utc'] <= b['utc'] for a, b in zip(journal, journal[1:])))
    before = {name: {'sha256': digest(originals[name]), 'receipt': parsed[name]}
              for name in names if name.startswith(('integrity-before-', 'dependency-check-before-', 'seal-check-before-'))}
    assert all(not item['receipt']['mismatches'] for item in before.values())
    source_files = {}
    for row in sources['files']:
        path = TREE / row['path']
        assert path.resolve().is_relative_to(TREE.resolve())
        source_files[path] = row['sha256']
    dependency_files = {Path(path): value for path, value in dependencies['files'].items()}
    assert all(path.resolve().is_relative_to(WORK.resolve()) for path in dependency_files)
    current = {'sources': check_files('sources', source_files, EVIDENCE / 'candidate-sources.json'),
               'dependencies': check_files('dependencies', dependency_files, EVIDENCE / 'dependency-files.json'),
               'seal': check_files('seal', {Path(p): value for p, value in seal['files'].items()},
                                   EVIDENCE / 'evaluation-seal.json')}
    changed = [name for name, raw in originals.items() if (EVIDENCE / name).read_bytes() != raw]
    gaps = ['blocks/full-general.result.json', 'blocks/full-general.results.json',
            'blocks/full-general.gate.json', 'monitor-full-general.json',
            'integrity-after-full-general.json', 'dependency-check-after-full-general.json',
            'seal-check-after-full-general.json']
    observed_gaps = [name for name in gaps if not (EVIDENCE / name).exists()]
    ram = sample_proof('resource-observer/samples.jsonl', journal)
    awake = sample_proof('awake-request/heartbeat.jsonl', journal)
    transition_valid = (advanced and not late_errors and not post_teardown['later_error_holder_mentions']
                        and not post_teardown['journal_error_holder_ids']
                        and len(class_ids) == 5 and len(post_teardown['class_pass_ids']) == 4
                        and post_teardown['class_missing_ids'] == [next_id])
    good = prefix_valid and transition_valid and not changed and all(not row['mismatches'] for row in current.values())
    receipt = {'schema': 'b9-prefix-validation/1',
        'state': 'PASS_INTEGRITY_WITH_HISTORICAL_GAP' if good else 'VALIDATION_FAILED',
        'utc_started': started, 'utc_finished': datetime.now(timezone.utc).isoformat(),
        'candidate_tree': SHA, 'helper_sha256': file_digest(Path(__file__)),
        'application_tests_executed': False, 'services_changed': False,
        'prior_files_modified': False, 'input_changes_during_validation': changed,
        'input_artifacts': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in originals.items()},
        'prefix': {'valid': prefix_valid, 'selected_count': len(selected), 'selected_unique': len(expected),
            'journal_rows': len(ids), 'unique_completed': len(actual), 'missing_count': len(missing),
            'duplicates': [key for key, value in Counter(ids).items() if value > 1],
            'unexpected': sorted(actual - expected), 'outcomes': counts,
            'journal_equals_selected_projection': ids == projection,
            'timestamps_monotonic': all(a['utc'] <= b['utc'] for a, b in zip(journal, journal[1:])),
            'completed_ids': sorted(actual), 'missing_ids': missing,
            'completed_ids_sha256': digest(('\n'.join(sorted(actual)) + '\n').encode()),
            'missing_ids_sha256': digest(('\n'.join(missing) + '\n').encode()),
            'skip_rows': [row for row in journal if row['outcome'] == 'SKIP'],
            'failure_or_error_rows': [row for row in journal if row['outcome'] in ('FAIL', 'ERROR')],
            'first_row': journal[0], 'last_row': journal[-1]},
        'historical_before_guards': before, 'current_byte_integrity': current,
        'post_teardown_observation': post_teardown,
        'historical_observations': {'ram': ram, 'awake': awake},
        'historical_gap': {'state': 'DISK_CLOCK_MONITOR_UNAVAILABLE',
            'missing_artifacts': observed_gaps,
            'durable_per_id_disk_reserve_proof': False,
            'durable_per_id_wall_minus_monotonic_proof': False,
            'current_hashes_reinterpreted_as_historical_after_guards': False,
            'full_group_pass': False, 'integral_acceptance_claimed': False}}
    with OUTPUT.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    print(receipt['state'], 'receipt_sha256=' + file_digest(OUTPUT), flush=True)
    if not good:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
