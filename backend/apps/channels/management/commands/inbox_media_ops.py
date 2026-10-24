"""Explicit operator actions; never reopens traffic or changes activation flags."""
from datetime import datetime
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.channels.media_clock import media_now
from apps.channels.media_incidents import incident_counts
from apps.channels.media_revocations import (ledger_root, provision_ledger, read_record,
    revocation_record, revoke_media)
from apps.channels.media_storage import InboxMediaStorage
from apps.channels.models import MediaPurgeIncident, MessageMedia


class Command(BaseCommand):
    help = 'Media status, durable revocation, incident acknowledgment and restore reconciliation'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['status', 'init-ledger', 'revoke', 'ack', 'close', 'restore-check'])
        parser.add_argument('--organization', type=int)
        parser.add_argument('--media')
        parser.add_argument('--incident')
        parser.add_argument('--operator')
        parser.add_argument('--evidence')
        parser.add_argument('--workers-stopped', action='store_true')
        parser.add_argument('--limit', type=int, default=1000)

    def handle(self, *args, **options):
        action = options['action']
        if action == 'status':
            result = dict(**incident_counts(),
                access_hold=settings.INBOX_MEDIA_ACCESS_HOLD,
                alerts_pending_configuration=not (settings.INBOX_MEDIA_OPS_OWNER and settings.DISCORD_WEBHOOK_URL))
            if options['organization']:
                if not 1 <= options['limit'] <= 1000:
                    raise CommandError('limit debe ser 1..1000 para status')
                result['incidents'] = list(MediaPurgeIncident.objects.for_organization(options['organization'])
                    .filter(closed_at__isnull=True).order_by('deadline_at').values('public_id', 'media__public_id',
                        'first_failed_at', 'deadline_at', 'failure_count', 'escalated_at', 'breached_at',
                        'acknowledged_at', 'notification_receipts')[:options['limit']])
            self.stdout.write(json.dumps(result, default=str))
            return
        if action == 'init-ledger':
            provision_ledger()
            self.stdout.write('Independent ledger provisioned; custody/backup need operational validation')
            return
        if action == 'restore-check':
            return self.restore_check(options)
        if not options['organization'] or not options['operator'] or len(options['operator']) > 100:
            raise CommandError('Se requieren organization y operator (máximo 100 caracteres)')
        if action == 'revoke':
            if not options['media']:
                raise CommandError('Se requiere media public_id')
            row = revoke_media(organization_id=options['organization'], public_id=options['media'])
            self.stdout.write(json.dumps(dict(media_public_id=str(row.public_id), revoked=True, purge_pending=True)))
            return
        if not options['incident']:
            raise CommandError('Se requiere incident public_id')
        with transaction.atomic():
            issue = (MediaPurgeIncident.objects.for_organization(options['organization']).select_for_update()
                .select_related('media').get(public_id=options['incident']))
            if action == 'close' and (issue.media.purge_verified_at is None or issue.media.file.name
                    or not options['evidence'] or len(options['evidence']) > 200):
                raise CommandError('Cerrar requiere purga verificada y referencia de evidencia (máximo 200 caracteres)')
            issue.acknowledged_at = issue.acknowledged_at or media_now()
            issue.acknowledged_by = options['operator']
            if action == 'close':
                issue.closed_at, issue.resolution_ref = media_now(), options['evidence']
            issue.save()
        self.stdout.write(json.dumps(dict(incident_public_id=str(issue.public_id), closed=issue.closed_at is not None)))

    def restore_check(self, options):
        if not settings.INBOX_MEDIA_ACCESS_HOLD or not options['workers_stopped']:
            raise CommandError('Restore exige ACCESS_HOLD=True y workers/webhooks detenidos (--workers-stopped)')
        limit = options['limit']
        if not 1 <= limit <= 10000:
            raise CommandError('limit debe ser 1..10000; no se abre tráfico automáticamente')
        root = ledger_root(required=True)
        paths = sorted(root.glob('*.json'))
        rows = MessageMedia.objects.order_by('pk')
        if rows.count() > limit or len(paths) > limit:
            raise CommandError('Volumen supera limit: reconciliación incompleta, mantener tráfico cerrado')
        result = dict(revoked=0, frozen_jobs=0, expired=0, checked=0, ledger_objects_purged=0,
            traffic_reopened=False, requires_provider_orphan_inventory=True)
        now = media_now()
        for row in rows.iterator(chunk_size=100):
            if row.status in ('pending', 'downloading', 'failed') and row.persisted_at is None:
                # A dump predating persistence cannot start a fresh 180-day window.
                revoke_media(organization_id=row.organization_id, public_id=row.public_id, reason='restore_pending')
                result['frozen_jobs'] += 1
                continue
            record = revocation_record(row, allow_hold=True)
            values = {}
            if record:
                values = dict(status='expired', expired_at=datetime.fromisoformat(record['revoked_at']),
                    worker_token=None, lease_until=None, next_attempt_at=None, attempts=5, error='access_revoked')
                result['revoked'] += 1
            elif row.expires_at and row.expires_at <= now:
                values = dict(status='expired', expired_at=row.expired_at or row.expires_at,
                    worker_token=None, lease_until=None, next_attempt_at=None)
                result['expired'] += 1
            elif row.status == 'ready':
                if not row.file.storage.exists(row.file.name):
                    values = dict(status='failed', error='object_missing', attempts=5, worker_token=None, lease_until=None)
                result['checked'] += 1
            if values:
                MessageMedia.objects.for_organization(row.organization_id).filter(pk=row.pk).update(**values)
        # Keys recorded after the dump are checked even without a surviving DB row.
        for path in sorted(root.glob('*.json')):
            record = read_record(path)
            if record['object_key']:
                InboxMediaStorage().delete(record['object_key'])
                if InboxMediaStorage().exists(record['object_key']):
                    raise CommandError('Purga del ledger sin verificar; mantener tráfico cerrado')
                result['ledger_objects_purged'] += 1
        self.stdout.write(json.dumps(result))
        # Receipt only. Provider orphan inventory and restore gates remain required.
