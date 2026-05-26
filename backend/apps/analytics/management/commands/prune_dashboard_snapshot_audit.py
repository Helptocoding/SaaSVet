"""
prune_dashboard_snapshot_audit — purga filas viejas de DashboardSnapshotAudit.

DashboardSnapshotAudit es append-only y de uso debug (lifecycle de snapshots):
crece sin limite (orgs x dias x eventos). No es dato de negocio ni contable, asi
que se purga por retencion. Default 180 dias.

Borrado FISICO (all_objects + .delete()) en lotes, para no tomar locks largos ni
una sola transaccion gigante. Solo lee + borra; sin select_for_update.

Exit codes: 0 ok, 2 error de uso.

Usage:
  python manage.py prune_dashboard_snapshot_audit                 # >180d, ejecuta
  python manage.py prune_dashboard_snapshot_audit --days 90
  python manage.py prune_dashboard_snapshot_audit --dry-run       # solo cuenta
  python manage.py prune_dashboard_snapshot_audit --org 12
"""
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone


BATCH = 1000


class Command(BaseCommand):
    help = "Purga DashboardSnapshotAudit por retencion (default 180 dias). Borrado fisico en lotes."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=180,
                            help="Retencion en dias. Borra filas con created_at mas antiguo. Default 180.")
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Solo cuenta lo que borraria, no borra.")

    def handle(self, *args, **opts):
        from apps.analytics.models import DashboardSnapshotAudit

        days = opts['days']
        if days < 1:
            self.stderr.write("--days debe ser >= 1.")
            sys.exit(2)

        cutoff = timezone.now() - timedelta(days=days)
        org_filter = Q(organization_id=opts['org']) if opts['org'] else Q()
        # all_objects: borrado fisico. objects (TenantManager) bloquea delete().
        base = DashboardSnapshotAudit.all_objects.filter(org_filter, created_at__lt=cutoff)

        total = base.count()

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                f"[dry-run] borraria {total} filas con created_at < {cutoff.isoformat()} "
                f"(retencion {days}d)"
            ))
            sys.exit(0)

        deleted = 0
        while True:
            ids = list(base.values_list('pk', flat=True)[:BATCH])
            if not ids:
                break
            DashboardSnapshotAudit.all_objects.filter(pk__in=ids).delete()
            deleted += len(ids)

        self.stdout.write(self.style.SUCCESS(
            f"Purgadas {deleted} filas de DashboardSnapshotAudit "
            f"(retencion {days}d, cutoff {cutoff.isoformat()})."
        ))
        sys.exit(0)
