"""Restore the original evidence package into an absent or empty directory."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

def restore(evidence,destination):
    manifest=json.loads((evidence/'preservation-manifest.json').read_text(encoding='utf-8'))
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RuntimeError('Destination must be absent or empty')
    pieces=[]
    for part in manifest['parts']:
        data=(evidence/part['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=part['sha256']:
            raise RuntimeError('Package part checksum mismatch')
        pieces.append(data)
    data=b''.join(pieces)
    if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:
        raise RuntimeError('Archive checksum mismatch')
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=archive.namelist()
        if sorted(names)!=sorted(manifest['files']) or len(names)!=len(set(names)):
            raise RuntimeError('Archive member inventory mismatch')
        root=destination.resolve()
        for name in names:
            target=(root/name).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError('Unsafe package member')
            target.parent.mkdir(parents=True,exist_ok=True)
            content=archive.read(name)
            if hashlib.sha256(content).hexdigest()!=manifest['files'][name]['sha256']:
                raise RuntimeError('Member checksum mismatch: '+name)
            target.write_bytes(content)
    mismatches=[name for name,row in manifest['files'].items()
        if hashlib.sha256((destination/name).read_bytes()).hexdigest()!=row['sha256']]
    if mismatches:
        raise RuntimeError('Recovered evidence differs: '+str(mismatches))
    return {'state':'PASS','recovered_members':len(names),'mismatches':mismatches}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(restore(Path(__file__).resolve().parent,args.destination)))
