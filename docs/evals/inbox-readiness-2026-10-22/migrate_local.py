"""Apply only the three authorized additive Inbox migrations after a local dump."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

out = Path(__file__).resolve().parent
root = out.parents[2]
receipt = out / 'migrations-local.json'
assert not receipt.exists(), 'Never overwrite a migration receipt'
sys.path.insert(0, str(root / 'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

database = settings.DATABASES['default']
assert database['ENGINE'] == 'django.db.backends.postgresql'
assert database['HOST'] in ('127.0.0.1', 'localhost') and str(database['PORT']) in ('', '5432')
assert database['NAME'] == 'veterinaria_saas', 'Only the inspected local working database is authorized'
expected = {('channels', '0016_message_reply_to'), ('channels', '0017_message_media'), ('agent', '0029_inbox_read_state')}
# Inspected prerequisites already implemented/tested by B3..B9. They are
# required by M2/M3/M4 on this older local DB; no other app is migrated.
prerequisites = {('agent', name) for name in (
    '0022_conversation_ownership_epoch_turnwork', '0023_humanhandoff_acknowledged_at_and_more',
    '0024_matter_binding_b6', '0025_conversation_operation_b7a', '0026_b7b_consent_evidence',
    '0027_attendance_consent_policy', '0028_b9_operational_budget')}
prerequisites |= {('channels', name) for name in (
    '0011_message_origin_epoch_message_output_ordinal_and_more', '0012_b3_scope_and_membership',
    '0013_b4_durable_sender', '0014_alter_message_semantic_type', '0015_b7b_receipt_guard')}
targets = [('channels', '0017_message_media'), ('agent', '0029_inbox_read_state')]
executor = MigrationExecutor(connection)
plan = executor.migration_plan(targets)
actual = {(migration.app_label, migration.name) for migration, backward in plan}
assert actual <= expected | prerequisites and not any(backward for migration, backward in plan), 'Unexpected migration dependency/rollback'
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database(), current_setting(\'server_version_num\'), pg_database_size(current_database())')
    name, version, size = cursor.fetchone()
    cursor.execute('SELECT count(*) FROM channels_message')
    count_before = cursor.fetchone()[0]
result = dict(state='PREPARED', database=name, host=database['HOST'], server_version_num=version,
    database_bytes=size, plan=[list(item) for item in sorted(actual)], existing_message_count=count_before,
    required_prerequisites=[list(item) for item in sorted(actual & prerequisites)],
    production_touched=False, preview_database_touched=False, media_enabled=settings.INBOX_MEDIA_ENABLED,
    started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
if plan:
    major = int(version) // 10000
    dump = Path(f'C:/Program Files/PostgreSQL/{major}/bin/pg_dump.exe')
    assert dump.is_file(), 'Compatible installed pg_dump required'
    private = out / 'runtime'
    private.mkdir(exist_ok=True)
    # Runtime already lives under the user's private checkout and is ignored.
    ignored = subprocess.run(['rtk', 'proxy', 'git', 'check-ignore', '--quiet', str(private / 'local-before.dump')], cwd=root)
    assert ignored.returncode == 0
    path = private / 'local-before.dump'
    assert not path.exists()
    env = {**os.environ, 'PGHOST': str(database['HOST']), 'PGPORT': str(database['PORT'] or 5432),
        'PGDATABASE': str(database['NAME']), 'PGUSER': str(database['USER']), 'PGPASSWORD': str(database['PASSWORD'])}
    backup = subprocess.run(['rtk', 'proxy', str(dump), '--no-password', '--format=custom', '--file', str(path)],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if backup.returncode:
        result.update(state='BACKUP_FAILED', exit_code=backup.returncode)
        receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
        raise SystemExit('Backup failed; database was not migrated. No raw stderr emitted.')
    verify = subprocess.run(['rtk', 'proxy', str(dump.with_name('pg_restore.exe')), '--list', str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert verify.returncode == 0 and path.stat().st_size > 1024
    result['backup'] = dict(path=str(path.relative_to(root)).replace('\\', '/'), bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), pg_restore_list_exit_code=verify.returncode, ignored_by_git=True)
    (out / 'migrations-local-before.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SET statement_timeout = '5min'")
    try:
        executor.migrate(targets)
    except Exception as error:
        result.update(state='MIGRATION_FAILED', error_type=type(error).__name__)
        receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
        raise
fresh = MigrationExecutor(connection)
assert not fresh.migration_plan(targets)
assert expected <= set(fresh.loader.applied_migrations)
with connection.cursor() as cursor:
    cursor.execute('SELECT count(*) FROM channels_message')
    count_after = cursor.fetchone()[0]
    assert count_after == count_before
    cursor.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name='channels_message' AND column_name='reply_to_id'")
    assert cursor.fetchone() == ('YES',)
    cursor.execute("SELECT count(*) FROM channels_messagemedia")
    media_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM agent_inboxreadstate")
    reads_count = cursor.fetchone()[0]
result.update(state='PASS', applied=[list(item) for item in sorted(actual)], messages_after=count_after,
    media_rows=media_count, read_state_rows=reads_count,
    finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
connection.close()
print(json.dumps(result, ensure_ascii=False, indent=2))
