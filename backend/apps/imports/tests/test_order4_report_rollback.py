from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from rest_framework.test import APIClient
from apps.core.models import UserRole
from apps.imports.tests.test_owner_pet_import import _seed_roles
from apps.users.models import User

from apps.imports.conflict_reports import collect
from apps.imports.models import ImportJob
from apps.imports.services import _append_conflict, _base_result
from apps.organizations.models import Organization


class ConflictReportRollbackTests(TransactionTestCase):
    def test_bridge_preserves_missing_evidence_marker_and_stops_on_mismatch(self):
        org = Organization.objects.create(name='Synthetic legacy')
        job = ImportJob.objects.create(organization=org, entity_type='inventory')
        from apps.imports.conflict_reports import convert_legacy
        job.result = {'skipped_conflicts': 3, 'conflicts': [{'row': 7, 'match_confidence': 'high'}]}
        with transaction.atomic():
            job.result = convert_legacy(job)
            job.save(update_fields=['result'])
        bridge = import_module('apps.imports.migrations.0004_conflict_rollback_bridge').restore_legacy_results
        bridge(apps, SimpleNamespace(connection=connection))
        job.refresh_from_db()
        self.assertFalse(job.result['conflict_report']['complete'])
        self.assertEqual(job.result['skipped_conflicts'], 3)
        self.assertEqual(len(job.result['conflicts']), 1)
        job.result['conflict_report']['available'] = 2
        job.save(update_fields=['result'])
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                bridge(apps, SimpleNamespace(connection=connection))
        job.refresh_from_db()
        self.assertEqual(job.result['conflict_report']['available'], 2)

    def test_migration_rollback_restores_detail_to_legacy_json(self):
        self.assertEqual(connection.vendor, 'postgresql')
        org = Organization.objects.create(name='Synthetic rollback')
        roles = _seed_roles(org)
        user = User.objects.create_user(username='rollback-report', password='synthetic', organization=org, role='ADMIN')
        UserRole.objects.get_or_create(user=user, role=roles['ADMIN'])
        job = ImportJob.objects.create(organization=org, entity_type='inventory')
        incomplete = ImportJob.objects.create(organization=org, entity_type='inventory', result={
            'skipped_conflicts': 3, 'conflicts': [{'row': 9, 'match_confidence': 'uncertain'}],
        })
        from apps.imports.conflict_reports import convert_legacy
        with transaction.atomic():
            incomplete.result = convert_legacy(incomplete)
            incomplete.save(update_fields=['result'])
        def calculate():
            result = _base_result()
            for row in range(1, 202):
                _append_conflict(result, {'row': row, 'match_confidence': 'high'})
            return result
        with transaction.atomic():
            locked = ImportJob.objects.select_for_update().get(pk=job.pk)
            locked.result = collect(locked, calculate)
            locked.save(update_fields=['result'])
        self.assertEqual(len(locked.result['conflicts']), 100)
        old_version = locked.result['conflict_report']['version']
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('imports', '0002_alter_importjob_entity_type')])
            historical = executor.loader.project_state([('imports', '0002_alter_importjob_entity_type')]).apps
            LegacyJob = historical.get_model('imports', 'ImportJob')
            restored = LegacyJob._base_manager.get(pk=job.pk).result
            self.assertEqual([entry['row'] for entry in restored['conflicts']], list(range(1, 202)))
            self.assertEqual(restored['skipped_conflicts'], 201)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            client = APIClient()
            client.force_authenticate(user)
            url = f'/api/imports/{job.public_id}/conflicts/'
            cursor = None
            version = None
            details = []
            while True:
                params = {'page_size': 50}
                if cursor:
                    params.update(cursor=cursor, version=version)
                response = client.get(url, params)
                self.assertEqual(response.status_code, 200, response.data)
                if version is None:
                    version = response.data['version']
                    self.assertNotEqual(version, old_version)
                self.assertEqual(response.data['version'], version)
                self.assertEqual(response.data['total'], 201)
                self.assertTrue(response.data['complete'])
                details.extend(response.data['results'])
                cursor = response.data['next_cursor']
                if cursor is None:
                    break
            self.assertEqual(details, [{'row': row, 'match_confidence': 'high'} for row in range(1, 202)])
            response = client.get(f'/api/imports/{incomplete.public_id}/conflicts/')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertFalse(response.data['complete'])
            self.assertEqual(response.data['total'], 3)
            self.assertEqual(response.data['available'], 1)
            self.assertEqual(response.data['results'], [{'row': 9, 'match_confidence': 'uncertain'}])
        finally:
            MigrationExecutor(connection).migrate(latest)
