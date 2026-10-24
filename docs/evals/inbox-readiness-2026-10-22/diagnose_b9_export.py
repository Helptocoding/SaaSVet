import hashlib
import json
from pathlib import Path

out = Path(__file__).resolve().parent
old = out.with_name('b9-correction-20261020-native-r12')
manifest = json.loads((old/'candidate-sources.json').read_text(encoding='utf-8'))
tree = out / 'runtime/b9/src'
groups = dict(equal=[], crlf=[], missing=[], other=[])
for row in manifest['files']:
    path = tree / row['path']
    if not path.is_file():
        group = 'missing'
    else:
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() == row['sha256']:
            group = 'equal'
        elif hashlib.sha256(content.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest() == row['sha256']:
            group = 'crlf'
        else:
            group = 'other'
    groups[group].append(row['path'])
(out/'b9-export-diagnosis.json').write_text(json.dumps(groups, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k: dict(count=len(v), examples=v[:8]) for k, v in groups.items()}))
