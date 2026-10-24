"""Read historical blobs, report semantic shapes only; no raw secret/Match output."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
report = root / 'docs/evals/b9-correction-20261020-native-r12/blocks/gitleaks-history.json'
target = out / 'security-contexts.json'
assert not target.exists()
findings = json.loads(report.read_text(encoding='utf-8'))
groups = {}
for finding in findings:
    groups.setdefault((finding['Commit'], finding['File']), []).append(finding)
refs = [commit+':'+name for commit, name in groups]
process = subprocess.run(['rtk', 'proxy', 'git', 'cat-file', '--batch'], cwd=root,
    input=('\n'.join(refs)+'\n').encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert process.returncode == 0
cursor, blobs, rows = 0, {}, []
for key in groups:
    end = process.stdout.index(b'\n', cursor)
    header = process.stdout[cursor:end].decode('ascii').split()
    assert len(header) == 3 and header[1] == 'blob', header
    size = int(header[2])
    blob = process.stdout[end+1:end+1+size]
    blobs[key] = blob
    cursor = end+size+2
for key, items in groups.items():
    text = blobs[key].decode('utf-8')
    lines = text.splitlines()
    for finding in items:
        line = lines[finding['StartLine']-1]
        pairs = re.findall(r'"([^"\n]+)"\s*:\s*"([^"\n]*)"', line)
        # Value classifications contain only length/alphabet, never the value.
        shapes = []
        for field, value in pairs:
            if len(value) < 12:
                shape = 'short_literal'
            elif re.fullmatch(r'[0-9a-fA-F]{64}', value):
                shape = 'hex64'
            elif re.fullmatch(r'[0-9a-fA-F]{40}', value):
                shape = 'hex40'
            elif re.fullmatch(r'[0-9a-fA-F]{32}', value):
                shape = 'hex32'
            elif re.fullmatch(r'[0-9a-fA-F-]{36}', value):
                shape = 'uuid'
            else:
                shape = 'other_literal'
            shapes.append(dict(field=field, shape=shape, length=len(value)))
        # Code context keeps identifiers and removes all string literals/comments.
        code_shape = re.sub(r'([\'\"])(?:\\.|(?!\1).)*?\1', '<literal>', line).split('#', 1)[0].strip() if key[1].endswith('.py') else None
        row = dict(fingerprint=finding['Fingerprint'], commit=key[0], file=key[1], line=finding['StartLine'],
            source_blob_sha256=hashlib.sha256(blobs[key]).hexdigest(), fields=shapes, code_shape=code_shape,
            source_line_sha256=hashlib.sha256(line.encode()).hexdigest())
        rows.append(row)
data = dict(source_report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(), detections=len(rows),
    raw_values_emitted=False, historical_blobs=len(blobs), contexts=rows)
target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(detections=len(rows), blobs=len(blobs),
    field_shapes=dict(Counter((entry['field']+'::'+entry['shape']) for row in rows for entry in row['fields'])),
    python_shapes=[{k:row[k] for k in ('file','line','code_shape')} for row in rows if row['code_shape'] is not None]),ensure_ascii=False,indent=2))
