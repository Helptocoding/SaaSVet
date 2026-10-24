"""Resolve the 550 unknown contexts; record exact immutable false positives."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

out = Path(__file__).resolve().parent
root = out.parents[2]
target = out / 'security-classification.json'
assert not target.exists()
contexts = json.loads((out / 'security-contexts.json').read_text(encoding='utf-8'))
findings = json.loads((root / 'docs/evals/b9-correction-20261020-native-r12/blocks/gitleaks-history.json').read_text(encoding='utf-8'))
lookup = {row['fingerprint']: row for row in contexts['contexts']}
assert len(lookup) == len(findings) == 3156
rows, blobs = [], {}
for finding in findings:
    item = lookup[finding['Fingerprint']]
    fields = item['fields']
    category = None
    if any(field['field'].endswith('.py') and field['shape'] == 'hex64' for field in fields):
        category = 'SOURCE_FILE_SHA256_METADATA'
    elif any(field['field'] == 'operation_key' and field['shape'] == 'uuid' for field in fields):
        category = 'DISPOSABLE_TEST_OPERATION_UUID'
    elif any(field['field'] in ('lease_token', 'token') and field['shape'] == 'uuid' for field in fields):
        category = 'DISPOSABLE_TEST_LEASE_UUID'
    elif item['code_shape'] is not None:
        key = (item['commit'], item['file'])
        if key not in blobs:
            blobs[key] = subprocess.check_output(['rtk', 'proxy', 'git', 'show', key[0]+':'+key[1]], cwd=root).decode('utf-8')
        source = blobs[key]
        line = source.splitlines()[item['line']-1]
        if item['file'].endswith('authorized_lab.py'):
            literal = re.search(r'SECRET_KEY\s*=\s*([\'\"])(.*?)\1', line).group(2)
            assert 'environment' in source and 'DATABASE_URL' in source
            assert any(marker in literal.lower() for marker in ('test', 'probe', 'd29', 'synthetic'))
            category = 'LOCAL_LAB_SIGNING_FIXTURE'
        elif item['file'].endswith(('bootstrap.py', 'infra.py')):
            assert '/e4-causal-diagnostic-' in item['file']
            assert re.search(r'\b(?:OLD_)?KEY\s*=\s*[\'\"]', line)
            # KEY names an isolated run/output directory, never a credential.
            assert ('OLD_KEY' in source and 'replace' in source) or ('tempfile.gettempdir()' in source and '+KEY' in source)
            category = 'DIAGNOSTIC_RUN_DIRECTORY_ID'
        elif item['file'].endswith('b9a_harness.py'):
            literal = re.search(r'SECRET\s*=\s*([\'\"])(.*?)\1', line).group(2)
            assert 'WHATSAPP_APP_SECRET=SECRET' in source
            assert '127.0.0.1' in source or 'localhost' in source
            assert any(marker in literal.lower() for marker in ('test', 'fixture', 'b9a', 'synthetic'))
            category = 'LOCAL_SIGNED_WEBHOOK_FIXTURE'
        elif item['file'].endswith('test_b9a_e2e.py'):
            assert 'self.h.inbound(' in line and 'key=' in line
            assert 'test_e2e_03_duplicate_signed_http_is_one_message_and_work' in source
            category = 'INBOUND_DEDUPLICATION_FIXTURE_ID'
    assert category, (item['file'], item['line'], item['fields'])
    assert item['file'].startswith(('docs/evals/', 'backend/apps/agent/tests/'))
    rows.append(dict(fingerprint=item['fingerprint'], category=category,
        source_file=item['file'], source_commit=item['commit'], source_line=item['line'],
        source_blob_sha256=item['source_blob_sha256'], source_line_sha256=item['source_line_sha256']))
counts = dict(Counter(row['category'] for row in rows))
data = dict(status='CLASSIFIED_FALSE_POSITIVE_CONTEXTS', total=len(rows), categories=counts,
    original_r12_gate='FAIL_PRESERVED', scanner_rerun=False, active_credentials_tested=False,
    claim='These exact historical findings are non-credential metadata/fixtures, not proof that the current checkout has no secrets.',
    raw_secret_or_match_emitted=False, findings=rows)
target.write_text(json.dumps(data, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in data.items() if key != 'findings'}, indent=2))
