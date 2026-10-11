"""A single versioned interface change; all other R209 gate code is retained."""
from lab_control import HERE,lab

source=HERE/'r209_verification.py'
text=source.read_text()
changes=[
    ('import json','import json\nfrom native_ancestry import validate as validate_native_ancestry'),
    ("launches = read_lines(d/'process-launch.jsonl')",
     "launches = read_lines(d/'process-launch.jsonl')\n    native_samples = read_lines(d.parent/'resources.jsonl')\n    ancestry_proofs = {}"),
    ('l,i,r = launch[0],identities[0],ready[0]',
     "l,i,r = launch[0],identities[0],ready[0]\n        ancestry_proofs[role] = validate_native_ancestry(l,i,native_samples,roles[role][-1]['monotonic_ns'])"),
    ("i.get('parent_pid')!=l['launcher_pid']","not ancestry_proofs[role]['passed']"),
    ('obligations=obligations,definite_overlaps=overlap',
     'native_ancestry=ancestry_proofs,obligations=obligations,definite_overlaps=overlap')]
for old,new in changes:
    assert text.count(old)==1,old
    text=text.replace(old,new,1)
target=HERE/'r209_verification_v3.py'
with target.open('x',encoding='utf-8') as f:f.write(text)
lab.write(HERE/'r209-v3-adaptation.json',dict(original_sha256=lab.sha(source),versioned_sha256=lab.sha(target),
    source_preserved=True,changes=[dict(original=a,replacement=b) for a,b in changes],
    reason='WINDOWS_VENV_HAS_NATIVE_INTERMEDIATE_PROCESS',acceptance_bounds_changed=False))
print('VERSIONED_NATIVE_ANCESTRY_ADAPTER_WRITTEN',flush=True)
