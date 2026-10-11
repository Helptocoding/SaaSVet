"""Offline evidence utilities. No database, providers or service control."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = '825db75df68bf076929fa787e77beefe96803350'
BASE = ROOT / 'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'
BASE_HASH = '71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56'
PRIOR = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07'
REQUEST = Path('C:/Users/LAP/.codex/attachments/4c4a3dd0-68ba-4697-9efa-9332f3f9975a/Texto pegado.txt')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def lines(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(name, value):
    target = (HERE / name).resolve()
    if not target.is_relative_to(HERE) or target.exists():
        raise ValueError('Refuse out-of-phase write or receipt overwrite: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return target


def check_integrity():
    original = read(PRIOR / 'initial-integrity.json')
    bad = [p for p, expected in original['protected_sources'].items()
           if not (ROOT / p).is_file() or sha(ROOT / p) != expected]
    head = subprocess.run(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    return {'at_utc': utc(), 'head': head, 'expected_head': BASELINE,
            'base_sha256': sha(BASE), 'expected_base_sha256': BASE_HASH,
            'protected_sources_checked': len(original['protected_sources']),
            'protected_source_changes': bad,
            'valid': not bad and head == BASELINE and sha(BASE) == BASE_HASH}


if __name__ == '__main__':
    result = check_integrity()
    result['request_sha256'] = sha(REQUEST)
    result['execution_authorized'] = False
    result['scope'] = 'PREPARATION_AND_OFFLINE_VALIDATION_ONLY'
    save('initial-seal.json', result)
    print(json.dumps(result))
