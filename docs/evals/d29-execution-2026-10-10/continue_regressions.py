"""Only the seven authorized suites, strictly sequential, no retries."""
import json
from run_task import HERE, run
from lab_control import lab

LABELS = ['test_b4_sender','test_w1_monotonic','test_b5_safety','test_operation_execution',
          'test_b9b_budget','test_b9c_concurrency','test_b9c_processes']


def completed(label):
    folder = HERE / label
    receipt = json.loads((folder / 'execution-receipt.json').read_text())
    result = json.loads((folder / 'suite-result.json').read_text())
    if (receipt['kind']!='suite' or receipt['status']!='ACCREDITED' or receipt['exit_code']!=0
            or not receipt.get('database_removed') or receipt.get('clients_after_child')
            or result['labels']!=['apps.agent.tests.'+label] or result['status']!='PASS'
            or result['failures'] or result['errors'] or not result.get('source_integrity')):
        raise RuntimeError('SEQUENCE_STOP_SUITE_OR_CLEANUP_FAILED:'+label)
    return dict(label=label,tests=result['tests'],skipped=result['skipped'],status='ACCREDITED',
                execution_receipt=str(folder/'execution-receipt.json'),suite_receipt=str(folder/'suite-result.json'))


if __name__ == '__main__':
    results = [completed(LABELS[0])]
    for label in LABELS[1:]:
        print('SEQUENTIAL_SUITE_START '+label,flush=True)
        run('suite',label)
        results.append(completed(label))
        print('SEQUENTIAL_SUITE_COMPLETE '+label,flush=True)
    lab.write(HERE/'sequential-regressions.json',dict(status='ACCREDITED',suites=results,
        max_simultaneous_suites=1,baseline_unchanged=True,physical_accreditation=False))
