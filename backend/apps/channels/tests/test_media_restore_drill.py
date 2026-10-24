"""Opt-in local DR proof with a real pg_dump/pg_restore of a disposable test DB."""
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.agent.tests.process_database import validate_test_database
from apps.channels.media_clock import media_now
from apps.channels.media_revocations import provision_ledger, revoke_media
from apps.channels.media_worker import claim_media, expire_media
from apps.channels.models import MessageMedia
from apps.channels.tests.test_media_pipeline import MediaFixtures

PG_DUMP = shutil.which('pg_dump') or 'C:/Program Files/PostgreSQL/18/bin/pg_dump.exe'
PG_RESTORE = str(Path(PG_DUMP).with_name('pg_restore.exe')) if os.name == 'nt' else shutil.which('pg_restore')


@skipUnless(Path(PG_DUMP).is_file() and PG_RESTORE and Path(PG_RESTORE).is_file(), 'Installed PostgreSQL dump/restore tools required')
@override_settings(INBOX_MEDIA_ENABLED=True, MEDIA_BACKEND='local', INBOX_MEDIA_ALLOW_LOCAL=True)
class MediaDatabaseRestoreDrill(MediaFixtures, TransactionTestCase):
    def test_old_dump_cannot_reactivate_revoked_expired_or_recovered_jobs(self):
        database = connection.settings_dict
        validate_test_database(database, allowed_prefixes=('test_inbox_policy_', 'test_ci_'),
                               source_url=os.environ.get('DATABASE_URL', ''))
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            self.assertEqual(cursor.fetchone()[0], database['NAME'])
        self.build()
        with TemporaryDirectory(prefix='inbox-restore-drill-') as folder:
            root = Path(folder)
            with override_settings(INBOX_MEDIA_REVOCATION_ROOT=str(root/'inbox-media-revocations'),
                    INBOX_MEDIA_OPS_OWNER='', DISCORD_WEBHOOK_URL='', INBOX_MEDIA_ACCESS_HOLD=False):
                provision_ledger()
                revoked = self.ready()
                stamps = revoked.persisted_at, revoked.expires_at
                expired = self.ready()
                MessageMedia.objects.filter(pk=expired.pk).update(expires_at=media_now()-timedelta(days=1))
                pending = self.media()
                recovered_claim = claim_media()
                self.assertIsNotNone(recovered_claim)
                backup = root/'old-test-db.dump'
                env = {**os.environ, 'PGHOST': str(database['HOST']), 'PGPORT': str(database['PORT'] or 5432),
                    'PGDATABASE': str(database['NAME']), 'PGUSER': str(database['USER']), 'PGPASSWORD': str(database['PASSWORD'])}
                dumped = subprocess.run([PG_DUMP, '--no-password', '--format=custom', '--no-owner',
                    '--no-acl', '--file', str(backup)], env=env, capture_output=True, timeout=180)
                self.assertEqual(dumped.returncode, 0, 'Local synthetic pg_dump failed; no raw stderr emitted')
                sha = hashlib.sha256(backup.read_bytes()).hexdigest()
                revoke_media(organization_id=self.org.pk, public_id=revoked.public_id)
                self.assertEqual(MessageMedia.objects.get(pk=revoked.pk).status, 'expired')
                connection.close()
                restored = subprocess.run([PG_RESTORE, '--no-password', '--clean', '--if-exists',
                    '--no-owner', '--no-acl', '--exit-on-error', '--dbname', str(database['NAME']), str(backup)],
                    env=env, capture_output=True, timeout=180)
                self.assertEqual(restored.returncode, 0, 'Local synthetic pg_restore failed; no raw stderr emitted')
                revoked.refresh_from_db()
                self.assertEqual(revoked.status, 'ready', 'Old DB state must actually have been restored')
                output = io.StringIO()
                client = APIClient()
                client.force_authenticate(self.actor)
                with override_settings(INBOX_MEDIA_ACCESS_HOLD=True):
                    self.assertEqual(client.get(f'/api/inbox/media/{revoked.public_id}/').status_code, 503)
                    call_command('inbox_media_ops', 'restore-check', workers_stopped=True, stdout=output)
                for row in (revoked, expired, pending):
                    row.refresh_from_db()
                    self.assertEqual(row.status, 'expired')
                    self.assertEqual(client.get(f'/api/inbox/media/{row.public_id}/').status_code, 410)
                self.assertEqual((revoked.persisted_at, revoked.expires_at), stamps)
                self.assertIsNone(claim_media())
                self.assertIsNone(pending.worker_token)
                expire_media()
                self.assertFalse(expired.file.storage.exists(expired.file.name))
                self.assertFalse(revoked.file.storage.exists(revoked.file.name))
                result = json.loads(output.getvalue())
                self.assertFalse(result['traffic_reopened'])
                print('RESTORE_DUMP_DRILL '+json.dumps(dict(pg_dump_exit=dumped.returncode,
                    pg_restore_exit=restored.returncode, backup_sha256=sha, backup_bytes=backup.stat().st_size,
                    old_database_state_restored=True, independent_ledger_preserved=True,
                    expired_revoked_jobs_denied=True, persistence_timestamps_preserved=True,
                    provider='synthetic local private files', traffic_reopened=False)))
