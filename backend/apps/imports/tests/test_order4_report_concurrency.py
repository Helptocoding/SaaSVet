import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from apps.core.models import UserRole
from apps.imports.conflict_reports import collect
from apps.imports.models import ImportJob
from apps.imports.services import _append_conflict, _base_result
from apps.imports.tests.test_owner_pet_import import _seed_roles
from apps.organizations.models import Organization
from apps.users.models import User


class ReportConcurrencyTests(TransactionTestCase):
    def test_page_waiting_for_replacement_cannot_mix_versions(self):
        self.assertEqual(connection.vendor, 'postgresql')
        org = Organization.objects.create(name='Synthetic concurrent')
        roles = _seed_roles(org)
        user = User.objects.create_user(username='report-concurrency', password='synthetic', organization=org, role='ADMIN')
        UserRole.objects.get_or_create(user=user, role=roles['ADMIN'])
        job = ImportJob.objects.create(organization=org, entity_type='inventory')

        def make_result(row):
            result = _base_result()
            _append_conflict(result, {'row': row, 'match_confidence': 'high'})
            return result

        with transaction.atomic():
            locked = ImportJob.objects.select_for_update().get(pk=job.pk)
            locked.result = collect(locked, lambda: make_result(1))
            locked.save(update_fields=['result'])
        version = locked.result['conflict_report']['version']
        started = threading.Event()

        def read_page():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=user.pk))
                started.set()
                response = client.get(f'/api/imports/{job.public_id}/conflicts/', {'version': version})
                return response.status_code, response.data
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                locked = ImportJob.objects.select_for_update().get(pk=job.pk)
                future = pool.submit(read_page)
                self.assertTrue(started.wait(10))
                self.assertFalse(future.done())
                locked.result = collect(locked, lambda: make_result(2))
                locked.save(update_fields=['result'])
            status, body = future.result(timeout=30)
        self.assertEqual(status, 409)
        self.assertEqual(body['code'], 'conflict_report_changed')
        self.assertNotIn('results', body)
