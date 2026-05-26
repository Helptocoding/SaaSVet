"""
Tests de prune_dashboard_snapshot_audit: retención por created_at, dry-run y
borrado físico en lotes.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import DashboardSnapshotAudit
from apps.organizations.models import Organization


class PruneDashboardSnapshotAuditTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org Prune', timezone='UTC')

    def _audit(self, age_days):
        row = DashboardSnapshotAudit.all_objects.create(
            organization=self.org,
            snapshot_date=timezone.localdate(),
            kind='build',
        )
        # created_at es auto_now_add; sobrescribir vía update() para simular edad.
        old = timezone.now() - timedelta(days=age_days)
        DashboardSnapshotAudit.all_objects.filter(pk=row.pk).update(created_at=old)
        return row

    def _run(self, *args):
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command('prune_dashboard_snapshot_audit', *args, stdout=out)
        return out.getvalue(), ctx.exception.code

    def test_deletes_only_older_than_retention(self):
        self._audit(age_days=200)   # viejo -> borrar
        self._audit(age_days=200)   # viejo -> borrar
        keep = self._audit(age_days=10)  # reciente -> conservar

        _, code = self._run('--days', '180')
        self.assertEqual(code, 0)
        remaining = list(DashboardSnapshotAudit.all_objects.values_list('pk', flat=True))
        self.assertEqual(remaining, [keep.pk])

    def test_dry_run_deletes_nothing(self):
        self._audit(age_days=200)
        self._audit(age_days=200)

        out, code = self._run('--days', '180', '--dry-run')
        self.assertEqual(code, 0)
        self.assertIn('dry-run', out)
        self.assertEqual(DashboardSnapshotAudit.all_objects.count(), 2)

    def test_org_scope(self):
        other = Organization.objects.create(name='Org Otra', timezone='UTC')
        mine = self._audit(age_days=200)
        other_row = DashboardSnapshotAudit.all_objects.create(
            organization=other, snapshot_date=timezone.localdate(), kind='build',
        )
        DashboardSnapshotAudit.all_objects.filter(pk=other_row.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )

        _, code = self._run('--days', '180', '--org', str(self.org.pk))
        self.assertEqual(code, 0)
        # Solo se borró la de mi org; la de la otra org sigue.
        self.assertFalse(DashboardSnapshotAudit.all_objects.filter(pk=mine.pk).exists())
        self.assertTrue(DashboardSnapshotAudit.all_objects.filter(pk=other_row.pk).exists())

    def test_invalid_days_exits_2(self):
        _, code = self._run('--days', '0')
        self.assertEqual(code, 2)
