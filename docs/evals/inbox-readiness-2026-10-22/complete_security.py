"""Scan exactly the six B9 correction files, once, with the unchanged rule configuration."""
import hashlib
import json
from pathlib import Path
import shutil
from run_security import scan

out = Path(__file__).resolve().parent
root = out.parents[2]
old = out.with_name('b9-correction-20261020-native-r12')
tree = out/'runtime/b9/src'
assert not (out/'security-correction-verification.json').exists()
assert json.loads((out/'security-verification.json').read_text())['state'] == 'PASS'
assert (root/'.gitleaks.toml').read_bytes() == (tree/'.gitleaks.toml').read_bytes()
paths = json.loads((old/'candidate.json').read_text())['changed_paths']
assert len(paths) == 6
target = out/'runtime/security-correction'
target.mkdir(exist_ok=False)
for name in paths:
    p = target/name
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tree/name, p)
result = scan('correction', target, no_git=True)
state = 'PASS' if result['exit_code'] == 0 and result['findings'] == 0 else 'FAIL'
receipt = dict(state=state, result=result, paths={p:hashlib.sha256((target/p).read_bytes()).hexdigest() for p in paths},
               candidate_tree='f5f18d71847a46d66644775cd90d30268f072e3b', historical_r12_fail_preserved=True)
(out/'security-correction-verification.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(state=state, files=len(paths), findings=result['findings'])), flush=True)
raise SystemExit(0 if state == 'PASS' else 2)
