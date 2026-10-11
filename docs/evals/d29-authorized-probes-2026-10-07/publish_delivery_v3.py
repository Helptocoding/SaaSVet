"""Publish navigable local links while preserving the prior package snapshot."""
import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))

def files():
    return {p.relative_to(OUT).as_posix():p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact-index-v3.json' and '__pycache__' not in p.parts}

def main():
    previous = read(OUT/'artifact-index-v2.json')
    for relative, entry in previous.items():
        p = OUT/relative
        if sha(p)!=entry['sha256'] or p.stat().st_size!=entry['bytes']:
            raise RuntimeError('Prior package snapshot changed: '+relative)
    source = (OUT/'ENTREGA.md').read_text(encoding='utf-8')
    def link(match):
        target = (OUT/match.group(2).replace('\\','/')).resolve()
        if not target.is_file():
            raise RuntimeError('Report link missing: '+str(target))
        return '['+match.group(1)+']('+target.as_posix()+')'
    report = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,source)
    report = report.replace('\nRegresión D29:', '\n\nRegresión D29:').replace('\nLos dos laboratorios', '\n\nLos dos laboratorios')
    report += '\nEl paquete final usa `artifact-index-v3.json`. El índice v2 y su informe original se preservan como snapshot previo, sin cambiar ninguno de sus archivos.\n'
    with (OUT/'INFORME-FINAL.md').open('x',encoding='utf-8') as f:
        f.write(report)
    index = {relative:dict(sha256=sha(p),bytes=p.stat().st_size) for relative,p in sorted(files().items())}
    with (OUT/'artifact-index-v3.json').open('x',encoding='utf-8') as f:
        json.dump(index,f,indent=2)
    if set(files())!=set(index):
        raise RuntimeError('Final package fileset changed')
    for relative, entry in index.items():
        if sha(OUT/relative)!=entry['sha256']:
            raise RuntimeError('Final package artifact changed: '+relative)
    print(json.dumps(dict(status='PASS',artifacts=len(index),index_sha256=sha(OUT/'artifact-index-v3.json'),
        final_receipt_sha256=sha(OUT/'final-phase-receipt.json'),prior_snapshot_preserved=True)),flush=True)

if __name__ == '__main__':
    main()
