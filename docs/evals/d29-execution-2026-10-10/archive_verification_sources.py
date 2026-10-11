"""Preserve exact verifier versions identified by already written SHA-256s."""
import hashlib
import json
from lab_control import HERE,lab

records=[]
for folder in HERE.iterdir():
    if not folder.is_dir():continue
    for receipt in folder.glob('*.json'):
        value=json.loads(receipt.read_text())
        if not isinstance(value,dict):continue
        hashes=value.get('verification_source_hashes')
        if receipt.name=='verification-repair-v2.json':hashes=value.get('source_hashes')
        if not hashes:continue
        target=folder/('sources-'+receipt.stem)
        target.mkdir(exist_ok=True)
        for name,expected in hashes.items():
            candidates=[(HERE/name).read_bytes()]
            candidates.extend(p.read_bytes() for p in HERE.glob('*/execution-sources/'+name))
            current=(HERE/name).read_text()
            if name=='native_cleanup.py':
                candidates.append((current.split('def participant_exit',1)[0]+'def validate'+current.split('def validate',1)[1]).encode())
            if name=='test_native_cleanup.py':
                candidates.append(current.split('    def test_participant_capture',1)[0].replace('import validate,participant_exit','import validate').encode())
            exact=next((b for b in candidates if hashlib.sha256(b).hexdigest()==expected),None)
            if exact is None:raise ValueError('VERIFIER_VERSION_UNAVAILABLE:'+str(receipt)+':'+name)
            path=target/name
            if path.exists():assert lab.sha(path)==expected
            else:path.write_bytes(exact)
        records.append(dict(receipt=str(receipt.relative_to(HERE)),receipt_sha256=lab.sha(receipt),
            source_directory=str(target.relative_to(HERE)),sources=hashes))
lab.write(HERE/'verification-archives.json',records)
print('EXACT_VERIFICATION_VERSIONS_ARCHIVED '+str(len(records)),flush=True)
