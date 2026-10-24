"""Finite closure hygiene, no network or application database writes."""
import json
from pathlib import Path
import subprocess
import sys

out = Path(__file__).resolve().parent
root = out.parents[2]
target = out / 'final-checks.json'
assert not target.exists()
paths = ['.gitignore', 'CHANGELOG.md', 'backend/.env.example', 'backend/Procfile',
    'backend/apps/channels', 'backend/apps/agent/sender.py', 'backend/apps/agent/services.py',
    'backend/apps/agent/serializers.py', 'backend/apps/agent/views.py', 'backend/apps/agent/urls.py',
    'backend/apps/agent/management/commands/run_agent_worker.py',
    'backend/apps/agent/tests/test_inbox_replies.py', 'backend/apps/agent/tests/test_inbox_thread_performance.py',
    'backend/config/settings.py', 'backend/requirements.txt', 'backend/requirements.lock',
    'frontend/src/api/inbox.js', 'frontend/src/api/inbox.test.js', 'frontend/src/pages/inbox',
    'scripts/crontab.example', 'docs/CIERRE-INBOX-WHATSAPP.md',
    'docs/plan-implementacion-whatsapp-inbox-2026-08-22.md', 'docs/modules/agent.md',
    'docs/modules/frontend.md', 'docs/decisions/2026-08-22-p60-whatsapp-inbox-decisions.md']
check = subprocess.run(['rtk', 'proxy', 'git', 'diff', '--check', '--', *paths], cwd=root,
    capture_output=True, text=True, encoding='utf-8')
assert check.returncode == 0, check.stdout + check.stderr
runtime_files = [path for path in (out / 'runtime').rglob('*') if path.is_file()]
assert not runtime_files
summary = subprocess.run(['rtk', 'proxy', sys.executable, '-X', 'utf8', str(out / 'verify_evidence.py')],
    capture_output=True, text=True, encoding='utf-8', check=True)
composed = json.loads(summary.stdout)
assert composed['status'] == 'PASS'
data = dict(status='PASS', diff_check_exit_code=check.returncode, private_runtime_files=0,
    screenshots_visually_inspected=['browser-retained/media-states-desktop.png', 'browser-retained/media-states-mobile.png',
        'browser-focus/media-lightbox-desktop.png'], source_and_evidence_not_yet_sealed=True,
    backend_unique=composed['backend_unique'], frontend_unique=composed['frontend_unique'])
target.write_text(json.dumps(data, indent=2), encoding='utf-8')
print(json.dumps(data))
