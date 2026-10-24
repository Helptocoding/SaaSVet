"""Compose unique case results; seal only after every required check finishes."""
import hashlib
import json
from pathlib import Path
import re
import sys

out = Path(__file__).resolve().parent
root = out.parents[2]
backend_tags = ['new-media', 'affected', 'corrected', 'final-integration', 'proxy-final', 'b1-caption', 'b1-raw-contract']
frontend_tags = ['media', 'media-fixed', 'affected', 'final-media', 'historical-fixed', 'historical-cap']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if '--verify' in sys.argv:
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest:
        assert digest(root / item['path']) == item['sha256'], item['path']
    print(json.dumps(dict(status='PASS', verified_files=len(manifest))))
    raise SystemExit(0)

backend, frontend, missing, receipts = {}, {}, [], []
for tag in backend_tags:
    path = out / f'backend-{tag}.json'
    if not path.exists():
        missing.append(path.name)
        continue
    receipt = json.loads(path.read_text(encoding='utf-8'))
    assert receipt['test_database_remains'] is False
    assert receipt['working_database_migrated'] is False
    log = path.with_suffix('.log').read_text(encoding='utf-8')
    # unittest places a short docstring between the identity and result line.
    cases = re.findall(r'^test_\w+ \((apps\.[^)]+)\)', log, re.M)
    failures = set(re.findall(r'^(?:ERROR|FAIL): test_\w+ \((apps\.[^)]+)\)', log, re.M))
    total = re.search(r'^Ran (\d+) tests? in ', log, re.M)
    assert total and int(total[1]) == len(cases), path.name
    assert bool(failures) == bool(receipt['exit_code']), path.name
    for case in cases:
        backend[case] = dict(status='failed' if case in failures else 'passed', receipt=path.name)
    receipts.append(path.name)
for tag in frontend_tags:
    path = out / f'frontend-{tag}-vitest.json'
    if not path.exists():
        missing.append(path.name)
        continue
    report = json.loads(path.read_text(encoding='utf-8'))
    for suite in report['testResults']:
        source = str(Path(suite['name']).relative_to(root)).replace('\\', '/')
        for case in suite['assertionResults']:
            if case['status'] in ('passed', 'failed'):
                frontend[source + '::' + case['fullName']] = dict(status=case['status'], receipt=path.name)
    receipts.append(path.name)
unresolved = {**{case: result for case, result in backend.items() if result['status'] != 'passed'},
              **{case: result for case, result in frontend.items() if result['status'] != 'passed'}}
summary = dict(status='PASS' if not unresolved and not missing else 'INCOMPLETE',
    backend_unique=len(backend), frontend_unique=len(frontend), missing=missing, unresolved=unresolved,
    backend_new=sum(any(name in key for name in ('test_media_pipeline.', 'test_media_integration.', 'test_inbox_media.')) for key in backend),
    receipts=receipts, ordinary_or_preview_database_migrated=False, meta_b2_real_validation=False,
    security_b9_status_unchanged=True)
print(json.dumps(summary, ensure_ascii=False, indent=2))
if '--seal' not in sys.argv:
    raise SystemExit(0)
assert summary['status'] == 'PASS'
assert not (out / 'manifest.json').exists() and not (out / 'summary.json').exists()
for name in ('build-final', 'lint-final', 'drift-final', 'migration-generate-m4'):
    assert json.loads((out / f'{name}.json').read_text(encoding='utf-8'))['exit_code'] == 0
assert json.loads((out / 'dependencies.json').read_text(encoding='utf-8'))['status'] == 'PASS'
assert json.loads((out / 'browser-retained/browser.json').read_text(encoding='utf-8'))['status'] == 'PASS'
assert not json.loads((out / 'browser-retained/browser-run.json').read_text(encoding='utf-8'))['temporary_server_listening']
(out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
(out / 'cases.json').write_text(json.dumps(dict(backend=backend, frontend=frontend), ensure_ascii=False, indent=2), encoding='utf-8')
sources = '''.gitignore
CHANGELOG.md
backend/.env.example
backend/Procfile
backend/config/settings.py
backend/requirements.txt
backend/requirements.lock
backend/apps/channels/models.py
backend/apps/channels/events.py
backend/apps/channels/views.py
backend/apps/channels/providers.py
backend/apps/channels/replies.py
backend/apps/channels/media_policy.py
backend/apps/channels/media_ingest.py
backend/apps/channels/media_transfer.py
backend/apps/channels/media_worker.py
backend/apps/channels/media_storage.py
backend/apps/channels/migrations/0017_message_media.py
backend/apps/channels/management/commands/maintain_inbox_media.py
backend/apps/channels/tests/test_media_pipeline.py
backend/apps/channels/tests/test_media_integration.py
backend/apps/channels/tests/test_webhook.py
backend/apps/agent/inbox_media.py
backend/apps/agent/inbox_sync.py
backend/apps/agent/sender.py
backend/apps/agent/services.py
backend/apps/agent/serializers.py
backend/apps/agent/views.py
backend/apps/agent/urls.py
backend/apps/agent/management/commands/run_agent_worker.py
backend/apps/agent/tests/test_inbox_media.py
backend/apps/agent/tests/test_inbox_replies.py
backend/apps/agent/tests/test_inbox_thread_performance.py
frontend/src/api/inbox.js
frontend/src/api/inbox.test.js
frontend/src/pages/inbox/index.jsx
frontend/src/pages/inbox/inbox.module.css
frontend/src/pages/inbox/MediaBubble.jsx
frontend/src/pages/inbox/MediaBubble.test.jsx
frontend/src/pages/inbox/useMediaUrl.js
frontend/src/pages/inbox/index.replies.test.jsx
scripts/crontab.example
docs/CIERRE-INBOX-WHATSAPP.md
docs/plan-implementacion-whatsapp-inbox-2026-08-22.md
docs/decisions/2026-08-22-p60-whatsapp-inbox-decisions.md
docs/modules/agent.md
docs/modules/frontend.md
docs/runbooks/inbox-media.md'''.splitlines()
files = {root / name for name in sources}
files.update(path for path in out.rglob('*') if path.is_file() and 'runtime' not in path.parts
             and '__pycache__' not in path.parts and path.name != 'manifest.json')
manifest = [dict(path=str(path.relative_to(root)).replace('\\', '/'), sha256=digest(path), bytes=path.stat().st_size)
            for path in sorted(files)]
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps(dict(sealed_files=len(manifest))))
