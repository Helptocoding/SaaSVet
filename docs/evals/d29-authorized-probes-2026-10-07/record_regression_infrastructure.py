"""Preserve completed/error/interrupted suites without inventing a pass."""
import hashlib
import json
from pathlib import Path
OUT=Path(__file__).resolve().parent;d=OUT/'application-regression-v2'
labels=['test_b3_durable','test_b4_sender','test_w1_monotonic','test_b5_safety',
        'test_operation_execution','test_b9b_budget','test_b9c_concurrency','test_b9c_processes']
results=[]
for label in labels:
    p=d/(label+'.json');log=d/(label+'.log')
    receipt=json.loads(p.read_text()) if p.exists() else None
    results.append(dict(label=label,status=receipt['status'] if receipt else 'INCOMPLETE_INTERRUPTED' if log.exists() else 'NOT_RUN',
        receipt=receipt,log_path=str(log.relative_to(OUT)) if log.exists() else None,
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None))
log=(d/'test_b4_sender.log').read_text()
result=dict(status='INCOMPLETE_INFRASTRUCTURE',tests=sum(r['receipt']['tests'] for r in results if r['receipt']),
    tests_in_complete_receipts=sum(r['receipt']['tests'] for r in results if r['receipt']),
    tests_in_passing_suites=sum(r['receipt']['tests'] for r in results if r['receipt'] and r['receipt']['status']=='PASS'),
    failures=[x for r in results if r['receipt'] for x in r['receipt']['failures']],
    errors=[x for r in results if r['receipt'] for x in r['receipt']['errors']],
    skipped=0,labels=['apps.agent.tests.'+x for x in labels],suites=results,
    first_observed_cause='psycopg.errors.OutOfMemory in test_meta_failure_matrix_through_real_sender(index=3), followed by backend connection closure and cascading setup/teardown errors.',
    database_error_detail='Failed on request of size 48 in memory context MessageContext.',
    out_of_memory_directly_recorded='psycopg.errors.OutOfMemory' in log,
    runtime_regression_inferred=False,regression_not_demonstrated=True,tests_unmodified=True,
    scope='EXISTING_APPLICATION_REGRESSION_NOT_PHYSICAL_ACCREDITATION',benchmark=False,
    source_integrity=all(r['receipt']['source_integrity'] for r in results if r['receipt']),
    stop_receipt='regression-native-stop-receipt.json',
    next_requirement='Repeat the incomplete/error application suites in an evaluation environment with available resources, without altering runtime, tests, durability, or CONFIRMED_BASE. No retry executed in this phase after OutOfMemory.')
for name,value in [('application-regression.json',result),('application-regression-exit.json',dict(exit_code=None,status='STOPPED_AFTER_INFRASTRUCTURE_FAILURE'))]:
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)
print(json.dumps(dict(status=result['status'],tests_in_passing_suites=result['tests_in_passing_suites'],
    tests_in_complete_receipts=result['tests_in_complete_receipts'],out_of_memory=result['out_of_memory_directly_recorded'],
    pending_suites=[r['label'] for r in results if r['status']!='PASS'])))
