"""Read-only source/evidence audit. Never opens PostgreSQL or starts a worker."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = '825db75df68bf076929fa787e77beefe96803350'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit():
    protected = read(ROOT / 'docs/evals/d29-r102-base-2026-10-07/final-integrity.json')['protected_sources']
    errors = [p for p, digest in protected.items() if not (ROOT/p).is_file() or sha(ROOT/p) != digest]
    indexes = {}
    for name in ('d29-physical-2026-10-06', 'd29-frontiers-2026-10-07', 'd29-r102-base-2026-10-07', 'd29-dependent-2026-10-07'):
        folder = ROOT / 'docs/evals' / name
        index_path = folder / ('delivery-index.json' if name == 'd29-dependent-2026-10-07' else 'artifact-index.json')
        index = read(index_path)
        if name == 'd29-dependent-2026-10-07':
            index = index['artifacts']
        indexes[name] = dict(count=len(index), index_sha256=sha(index_path))
        errors.extend(name+'/'+p for p, item in index.items() if not (folder/p).is_file() or sha(folder/p) != item['sha256'])
    head = subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    base = ROOT / 'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'
    expected = '71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56'
    result = dict(baseline=BASELINE, head=head, protected_source_count=len(protected), historical_indexes=indexes,
                  base_sha256=sha(base), mismatches=errors, intact=not errors and head == BASELINE and sha(base) == expected,
                  physical_runs=0, commits=0, runtime_changes=False)
    return result


if __name__ == '__main__':
    result = audit()
    target = HERE / sys.argv[1]
    with target.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))
    raise SystemExit(0 if result['intact'] else 1)
