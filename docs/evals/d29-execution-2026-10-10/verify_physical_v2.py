"""Versioned verifier connection repair; preserved physical capture only."""
import argparse
import hashlib
import json
from pathlib import Path
from verify_physical import verify, HERE
from native_verifier_bridge import installed


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder',type=Path)
    args = p.parse_args()
    files = ['native_verifier_bridge.py','verify_physical_v2.py','test_verifier_bridge.py']
    receipt = dict(schema='D29_VERIFIER_INTERFACE_REPAIR_V2',raw_evidence_modified=False,
        original_verifiers_modified=False,original_gates_relaxed=False,
        repairs=['argument order at savepoint adapter boundary','UTC representation of the identical anchor instant'],
        source_hashes={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in files})
    with (args.folder/'verification-repair-v2.json').open('x',encoding='utf-8') as f:
        json.dump(receipt,f,indent=2)
    with installed():
        verify(args.folder)
