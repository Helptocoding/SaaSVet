"""Count the two recorded unittest runs without counting skipped tests as pass."""
import json
import re
from pathlib import Path
OUT=Path(__file__).resolve().parent
def counts(file):
    text=(OUT/file).read_text(encoding='utf-8')
    count=int(re.search(r'Ran (\d+) tests?',text).group(1))
    skipped=re.search(r'OK \(skipped=(\d+)\)',text)
    omitted=int(skipped.group(1)) if skipped else 0
    return dict(log=file,tests_discovered=count,tests_skipped=omitted,tests_executed=count-omitted)
first=counts('unit-regression.log');second=counts('d29-preserved-receipt-regression.log')
read=lambda name:json.loads((OUT/name).read_text())
ok=read('unit-regression.json')['exit_code']==0 and read('d29-preserved-receipt-regression.json')['exit_code']==0
v=dict(status='PASS' if ok else 'FAIL',distinct_tests=first['tests_discovered'],
    distinct_tests_executed=first['tests_executed']+second['tests_executed'],
    remaining_skips=first['tests_skipped']-second['tests_executed'],runs=[first,second],
    scope='D29_REGRESSION_AND_PRESERVED_RECEIPT_NEGATIVE_TESTS',new_physical_execution=False)
with (OUT/'d29-regression-complete.json').open('x',encoding='utf-8') as f:json.dump(v,f,indent=2)
print(json.dumps(v))
