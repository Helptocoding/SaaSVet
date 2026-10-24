"""Bounded nightly expiration/reconciliation using the existing cron service."""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.channels.media_worker import maintain_media
from apps.channels.media_incidents import incident_counts, purge_backlog


class Command(BaseCommand):
    help = 'Expire private Inbox files, reconcile missing objects and clean orphan spools'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, default=100)
        parser.add_argument('--max-batches', type=int, default=10)
        parser.add_argument('--alerts-only', action='store_true', help='Evaluate alerts without retrying binary I/O')

    def handle(self, *args, **options):
        if not 1 <= options['batch'] <= 500 or not 1 <= options['max_batches'] <= 100:
            raise CommandError('batch debe ser 1..500 y max-batches 1..100')
        summary = dict(purged=0, checked=0, attempted=0, failed=0, alerts_accepted=0, spools=dict(removed=0, bytes=0))
        for _ in range(options['max_batches']):
            data = maintain_media(options['batch'], alerts_only=options['alerts_only'])
            summary['enabled'] = data['enabled']
            for key in ('purged', 'checked', 'attempted', 'failed'):
                summary[key] += data[key]
            summary['alerts_accepted'] += data['alerts']['accepted']
            summary['alerts_pending_configuration'] = data['alerts']['pending_configuration']
            for key in ('removed', 'bytes'):
                summary['spools'][key] += data['spools'][key]
            if not data['enabled'] or options['alerts_only'] or max(data['attempted'], data['checked']) < options['batch']:
                break
        summary.update(incident_counts() if summary['enabled'] else dict(open_incidents=0, compliance_incidents=0, unresolved_failures=0))
        summary.update(purge_backlog() if summary['enabled'] else dict(purge_pending=0, remaining_due=0))
        self.stdout.write(json.dumps(summary))
        if (summary['failed'] or summary['compliance_incidents'] or summary['unresolved_failures']
                or (summary['remaining_due'] and not options['alerts_only'])):
            raise CommandError('Purga sin resolver, capacidad agotada o incidente abierto; conservar el recibo JSON')
