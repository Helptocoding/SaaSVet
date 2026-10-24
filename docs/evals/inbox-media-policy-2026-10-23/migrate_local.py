"""Back up and apply exactly channels.0018 to the inspected local development DB."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out/'migration-local.json'
assert not receipt.exists(), 'Do not overwrite migration evidence'
sys.path.insert(0, str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

db = settings.DATABASES['default']
assert db['ENGINE'] == 'django.db.backends.postgresql' and db['HOST'] in ('localhost','127.0.0.1')
assert db['NAME'] == 'veterinaria_saas' and str(db['PORT']) in ('','5432')
assert not settings.INBOX_MEDIA_ENABLED and not settings.INBOX_MEDIA_PRODUCTION_APPROVED
target = [('channels','0018_media_retention_policy')]
executor = MigrationExecutor(connection)
plan = executor.migration_plan(target)
assert all(not backwards and (migration.app_label,migration.name) in target for migration,backwards in plan)
assert len(plan) == 1, 'Expected one new additive migration only'
with connection.cursor() as cursor:
    cursor.execute("SELECT current_setting('server_version_num')")
    version = cursor.fetchone()[0]
    cursor.execute('SELECT count(*) FROM channels_message')
    messages = cursor.fetchone()[0]
    cursor.execute('SELECT count(*) FROM channels_messagemedia')
    media = cursor.fetchone()[0]
private = out/'runtime'
private.mkdir(exist_ok=True)
backup = private/'local-before-0018.dump'
assert not backup.exists()
ignored = subprocess.run(['rtk','proxy','git','check-ignore','--quiet',str(backup)],cwd=root)
assert ignored.returncode == 0, 'Private backup must be ignored by Git'
dump = Path(f'C:/Program Files/PostgreSQL/{int(version)//10000}/bin/pg_dump.exe')
assert dump.is_file()
env = {**os.environ,'PGHOST':str(db['HOST']),'PGPORT':str(db['PORT'] or 5432),'PGDATABASE':str(db['NAME']),
    'PGUSER':str(db['USER']),'PGPASSWORD':str(db['PASSWORD'])}
saved = subprocess.run(['rtk','proxy',str(dump),'--no-password','--format=custom','--file',str(backup)],
    env=env,capture_output=True,timeout=180)
assert saved.returncode == 0, 'Backup failed; no migration performed, no raw stderr emitted'
verified = subprocess.run(['rtk','proxy',str(dump.with_name('pg_restore.exe')),'--list',str(backup)],
    capture_output=True,timeout=60)
assert verified.returncode == 0 and backup.stat().st_size > 1024
result = dict(state='BACKUP_VERIFIED', target=target, local_database=db['NAME'], server_version_num=version,
    production_touched=False, preview_touched=False, messages_before=messages, media_before=media,
    backup=dict(path=backup.relative_to(root).as_posix(), bytes=backup.stat().st_size,
        sha256=hashlib.sha256(backup.read_bytes()).hexdigest(), ignored_by_git=True, restore_list_exit=0))
(out/'migration-local-before.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
with connection.cursor() as cursor:
    cursor.execute("SET lock_timeout='5s'")
    cursor.execute("SET statement_timeout='5min'")
executor.migrate(target)
assert not MigrationExecutor(connection).migration_plan(target)
with connection.cursor() as cursor:
    cursor.execute('SELECT count(*) FROM channels_message')
    assert cursor.fetchone()[0] == messages
    cursor.execute('SELECT count(*) FROM channels_messagemedia')
    assert cursor.fetchone()[0] == media
    cursor.execute('SELECT count(*) FROM channels_mediapurgeincident')
    incidents = cursor.fetchone()[0]
call_command('check')
result.update(state='PASS', incidents_after=incidents, messages_unchanged=True, media_unchanged=True,
    django_check='PASS', flags_enabled=False)
receipt.write_text(json.dumps(result,indent=2),encoding='utf-8')
connection.close()
print(json.dumps(result,ensure_ascii=False))
