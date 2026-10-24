"""Partition the frozen full inventory and aggregate unchanged native receipts."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ('b8b', 'b8c', 'b8d', 'b8e', 'general')


def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    path = HERE / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def projected_groups():
    full = read('full-selected.json')
    assert full == sorted(set(full)) and len(full) == 3331
    groups = {family: [test for test in full if test.startswith(
        'apps.agent.tests.test_' + family + '_processes.')] for family in ORDER[:-1]}
    processes = {test for ids in groups.values() for test in ids}
    groups['general'] = [test for test in full if test not in processes]
    flat = [test for family in ORDER for test in groups[family]]
    assert len(flat) == len(set(flat)) and sorted(flat) == full
    return groups


def build_partition():
    assert not (HERE / 'evaluation-seal.json').exists()
    contract = read('full-partition-contract.json')
    assembly = read('assembly.json')
    assert assembly['candidate_sha'] == contract['candidate_tree']
    assert digest(HERE / 'full-selected.json') == contract['full_selection_sha256']
    groups = projected_groups()
    rows = []
    for family in ORDER:
        ids = groups[family]
        assert len(ids) == contract['counts'][family]
        label = 'full-' + family
        database = 'test_b9i_full_general' if family == 'general' else 'test_' + family + '_b9i_full'
        save(label + '-selected.json', ids)
        if family != 'general':
            guard = contract['guards'][family]
            source = Path(assembly['tree']) / guard['path']
            assert digest(source) == guard['source_sha256']
            assert database.startswith(guard['required_prefix'])
        rows.append({'label': label, 'family': family, 'database': database, 'count': len(ids),
                     'selection_sha256': digest(HERE / (label + '-selected.json'))})
    save('full-partition.json', {'state': 'PASS', 'candidate_tree': assembly['candidate_sha'],
         'groups': rows, 'total_ids': 3331, 'duplicate_ids': 0, 'missing_ids': [],
         'full_selection_sha256': digest(HERE / 'full-selected.json'),
         'native_runner': 'RecordedFullRunner -> DiscoverRunner',
         'sequential_groups': True, 'internal_process_concurrency_unchanged': True,
         'application_tests_executed': False})
    validate_partition()
    print('FULL_PARTITION_PREFLIGHT_PASS 3331 IDs; no omissions or duplicates', flush=True)


def validate_partition():
    partition = read('full-partition.json')
    contract = read('full-partition-contract.json')
    assembly = read('assembly.json')
    assert partition['state'] == 'PASS'
    assert partition['candidate_tree'] == assembly['candidate_sha'] == contract['candidate_tree']
    assert partition['full_selection_sha256'] == contract['full_selection_sha256'] == digest(HERE / 'full-selected.json')
    assert [row['family'] for row in partition['groups']] == list(ORDER) == contract['order']
    projected = projected_groups()
    for row in partition['groups']:
        family = row['family']
        assert row['label'] == 'full-' + family
        ids = read(row['label'] + '-selected.json')
        assert ids == projected[family]
        assert len(ids) == row['count'] == contract['counts'][family]
        assert digest(HERE / (row['label'] + '-selected.json')) == row['selection_sha256']
        expected_db = 'test_b9i_full_general' if family == 'general' else 'test_' + family + '_b9i_full'
        assert row['database'] == expected_db
        if family != 'general':
            guard = contract['guards'][family]
            assert expected_db.startswith(guard['required_prefix'])
            assert digest(Path(assembly['tree']) / guard['path']) == guard['source_sha256']
    assert partition['total_ids'] == 3331 and partition['duplicate_ids'] == 0 and partition['missing_ids'] == []
    return partition


def aggregate_full():
    from composite_evidence import block_path, candidate_compatible, provenance, validate_references
    validate_references()
    partition = validate_partition()
    receipts, journal, command_rows = [], [], []
    for group in partition['groups']:
        label = group['label']
        group_provenance = provenance(label)
        gate = json.loads(block_path(label, '.gate.json').read_text(encoding='utf-8'))
        receipt = json.loads(block_path(label, '.results.json').read_text(encoding='utf-8'))
        command = json.loads(block_path(label, '.command.json').read_text(encoding='utf-8'))
        expected = read(label + '-selected.json')
        assert gate['state'] == 'PASS' and command['exit_code'] == 0
        assert command['invalidating_incident'] is None
        candidate_compatible(label, receipt['candidate_sha'])
        assert sorted(receipt['test_ids']) == expected and receipt['tests'] == len(expected)
        assert receipt['failures'] == receipt['errors'] == receipt['exit_code'] == 0
        rows = [json.loads(line) for line in block_path(label, '.ids.jsonl').read_text(encoding='utf-8').splitlines()]
        assert sorted(row['id'] for row in rows) == expected
        journal.extend([dict(row, evidence_source=group_provenance) for row in rows])
        receipts.append(receipt)
        command_rows.append({'label': label, 'database': group['database'],
                             'command_receipt': str(block_path(label, '.command.json').relative_to(HERE)),
                             'provenance': group_provenance,
                             'seconds': command['seconds'], 'tests': receipt['tests']})
    expected = read('full-selected.json')
    ids = sorted(test for receipt in receipts for test in receipt['test_ids'])
    assert ids == expected and len(ids) == len(set(ids)) == 3331
    assert sorted(row['id'] for row in journal) == expected
    combined = {'candidate_sha': partition['candidate_tree'], 'test_ids': ids,
                'tests': sum(row['tests'] for row in receipts),
                'failures': 0, 'errors': 0,
                'skips': [skip for row in receipts for skip in row['skips']],
                'xfail': sum(row['xfail'] for row in receipts),
                'xpass': sum(row['xpass'] for row in receipts),
                'failed_ids': [], 'exit_code': 0,
                'seconds': sum(row['seconds'] for row in receipts),
                'orchestration': 'Composite acceptance of five complete native groups from referenced and current executions; independent process tests unchanged',
                'evidence_mode': 'COMPOSITE_ACCEPTANCE', 'continuous_campaign_claimed': False,
                'group_receipts': command_rows}
    save('blocks/full.results.json', combined)
    target = HERE / 'blocks/full.ids.jsonl'
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        for row in journal:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    save('blocks/full.aggregate.json', {'state': 'PASS', 'tests': len(ids),
         'evidence_mode': 'COMPOSITE_ACCEPTANCE', 'continuous_campaign_claimed': False,
         'group_receipts': command_rows, 'additional_test_execution': False,
         'duplicate_ids': 0, 'missing_ids': [], 'gate_evaluated_by_original_check_suite': True})
    print('FULL_AGGREGATE_COMPLETE 3331 IDs', flush=True)


if __name__ == '__main__':
    build_partition()
