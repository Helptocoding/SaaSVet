"""Read-only capability inventory. Never emit credentials or raw environment."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

out = Path(__file__).resolve().parent
root = out.parents[2]
target = out / 'preflight.json'
assert not target.exists()


def git(*args):
    return subprocess.check_output(['rtk', 'proxy', 'git', *args], cwd=root).decode('utf-8').strip()


def env_keys(path):
    if not path.exists():
        return dict(exists=False)
    from decouple import RepositoryEnv
    values = RepositoryEnv(str(path)).data
    names = ['MEDIA_BACKEND', 'INBOX_MEDIA_ENABLED', 'INBOX_MEDIA_PRODUCTION_APPROVED',
        'MEDIA_B2_ENDPOINT_URL', 'MEDIA_B2_REGION_NAME', 'MEDIA_B2_BUCKET',
        'MEDIA_B2_ACCESS_KEY_ID', 'MEDIA_B2_SECRET_ACCESS_KEY']
    return dict(exists=True, present={name: bool(values.get(name)) for name in names},
        dedicated_media_keys=[name for name in values if name.startswith(('MEDIA_B2_', 'B2_MEDIA_'))])


def package_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


data = dict(branch=git('branch', '--show-current'), head=git('rev-parse', 'HEAD'),
    tracked_change_count=len(git('status', '--porcelain', '--untracked-files=no').splitlines()),
    landing_repo_exists=(root.parent / 'LandingSaaS').exists(),
    environment_media_presence={name: bool(os.environ.get(name)) for name in
        ['MEDIA_B2_ENDPOINT_URL', 'MEDIA_B2_BUCKET', 'MEDIA_B2_ACCESS_KEY_ID', 'MEDIA_B2_SECRET_ACCESS_KEY']},
    env_files={str(path.relative_to(root)): env_keys(path) for path in
        [root / 'backend/.env', root / '.env', root / '.env.prod']},
    tools={name: shutil.which(name) for name in ['python', 'node', 'pnpm', 'git', 'pg_dump', 'gitleaks', 'ssh', 'b2', 'rclone']},
    packages={name: package_version(name) for name in ['boto3', 'psycopg']},
    python=sys.version.split()[0])
sys.path.insert(0, str(root / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['SENTRY_DSN'] = ''
import django
django.setup()
from django.conf import settings
database = settings.DATABASES['default']
data['django_database'] = dict(engine=database['ENGINE'], host=database['HOST'], port=database['PORT'],
    name=database['NAME'], local=database['HOST'] in ('127.0.0.1', 'localhost'))
data['media_settings'] = dict(backend=settings.MEDIA_BACKEND, enabled=settings.INBOX_MEDIA_ENABLED,
    production_approved=settings.INBOX_MEDIA_PRODUCTION_APPROVED,
    dedicated_credentials_present=bool(settings.MEDIA_B2_ACCESS_KEY_ID and settings.MEDIA_B2_SECRET_ACCESS_KEY))
target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(target.read_text(encoding='utf-8'))
