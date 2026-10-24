"""Execute the 321 unobserved cases and two corrected snapshots, without PASS reruns."""
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    from case_resumption import validate_case_references, remaining_case_ids
    validate_case_references()
    ids = remaining_case_ids()
    assert len(ids) == 323
    assert not any(item.endswith('.test_upcoming_window') for item in ids)
    label = 'full-general-remainder'
    database = 'test_b9i_full_general_remainder_r8'
    journal = HERE / 'blocks' / (label + '.ids.jsonl')
    receipt = HERE / 'blocks' / (label + '.results.json')
    assert not journal.exists() and not receipt.exists()
    os.environ.update(B9I_SUITE=label, B9I_ID_JOURNAL=str(journal), B9I_SUITE_RECEIPT=str(receipt))
    import recorded_suite
    from full_partition import validate_partition
    group = next(row for row in validate_partition()['groups'] if row['label'] == 'full-general')
    assert group['count'] == 3213 and group['database'] == 'test_b9i_full_general'
    assert recorded_suite.EVIDENCE == HERE
    from django.conf import settings
    from django.core.management import call_command
    settings.DATABASES['default'].setdefault('TEST', {})['NAME'] = database
    journal.touch(exist_ok=False)
    call_command('test', *ids, parallel=1, interactive=False, verbosity=2,
                 testrunner='recorded_suite.RecordedFullRunner')


if __name__ == '__main__':
    main()
