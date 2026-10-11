"""Final classification of raw byte differences without rewriting files."""
import json
import zipfile
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
v=read(OUT/'integrity-audit-v3.json')
task=Path(read(OUT/'environment.json')['task'])
line_endings=[];other=[]
with zipfile.ZipFile(task/'baseline.zip') as z:
    for name in v['tracked_backend_python_mismatches']:
        a=z.read(name);b=(ROOT/name).read_bytes()
        if a.replace(b'\r\n',b'\n')==b.replace(b'\r\n',b'\n'):
            line_endings.append(dict(path=name,archive_CRLF=a.count(b'\r\n'),checkout_CRLF=b.count(b'\r\n'),lines=a.count(b'\n')))
        else:other.append(name)
result=dict(baseline=v['baseline'],head=v['head'],executed_archive_python_count=v['tracked_backend_python_count'],
    executed_archive_python_mismatches=v['executed_archive_python_mismatches'],
    checkout_line_ending_only_differences=line_endings,checkout_other_content_mismatches=other,
    git_backend_diff_paths=v['git_backend_diff_paths'],initial_protected_source_mismatches=v['initial_protected_source_mismatches'],
    historical_evidence_mismatches=v['historical_evidence_mismatches'],historical_indexes=v['historical_indexes'],
    confirmed_base_sha256=v['confirmed_base_sha256'],
    explanation='Archive and checkout each contain CRLF; checkout has some LF lines. v2 raw differences and the one-sided v3 normalization are retained. This comparison normalizes both sides only in memory. Runtime execution used exact archived bytes. No source file was normalized or modified.',
    runtime_and_history_intact=v['baseline_head_unchanged'] and not (v['executed_archive_python_mismatches'] or other or v['git_backend_diff_paths'] or v['initial_protected_source_mismatches'] or v['historical_evidence_mismatches']))
with (OUT/'integrity-audit-v4.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(dict(executed_archive_count=result['executed_archive_python_count'],executed_archive_mismatches=result['executed_archive_python_mismatches'],line_ending_only=len(line_endings),other=other,runtime_and_history_intact=result['runtime_and_history_intact'])))
