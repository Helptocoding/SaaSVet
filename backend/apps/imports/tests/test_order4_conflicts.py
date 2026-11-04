from unittest.mock import patch

from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import UserRole
from apps.imports.conflict_reports import collect
from apps.imports.models import ImportConflict, ImportJob
from apps.imports.services import _append_conflict, _base_result, commit_job, ImportHasBlockingErrors
from apps.imports.tests.test_owner_pet_import import _seed_roles
from apps.organizations.models import Organization
from apps.inventory.models import Product
from apps.users.models import User


class ConflictReportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Synthetic')
        roles = _seed_roles(self.org)
        self.user = User.objects.create_user(username='synthetic-order4', password='synthetic', organization=self.org, role='ADMIN')
        UserRole.objects.get_or_create(user=self.user, role=roles['ADMIN'])
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.job = ImportJob.objects.create(organization=self.org, entity_type='inventory')
        self.url = f'/api/imports/{self.job.public_id}/conflicts/'

    def publish(self, count):
        def calculate():
            result = _base_result()
            for row in range(1, count + 1):
                _append_conflict(result, {'row': row, 'match_confidence': 'high' if row % 2 else 'uncertain'})
            return result
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(pk=self.job.pk)
            job.result = collect(job, calculate)
            job.save(update_fields=['result'])
        self.job.refresh_from_db()

    def test_all_pages_and_exact_counts(self):
        for count in (0, 100, 101, 2000):
            with self.subTest(count=count):
                self.publish(count)
                result = self.job.result
                self.assertEqual(len(result['conflicts']), min(100, count))
                self.assertEqual(result['conflicts_high'] + result['conflicts_uncertain'], count)
                version = result['conflict_report']['version']
                cursor = None
                rows = []
                while True:
                    params = {'page_size': 100, 'version': version}
                    if cursor:
                        params['cursor'] = cursor
                    response = self.client.get(self.url, params)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data['total'], count)
                    rows.extend(item['row'] for item in response.data['results'])
                    cursor = response.data['next_cursor']
                    if not cursor:
                        break
                self.assertEqual(rows, list(range(1, count + 1)))

    def test_version_cursor_and_transactional_publication(self):
        self.publish(101)
        old = self.client.get(self.url).data
        self.assertEqual(self.client.get(self.url, {'page_size': 101}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'cursor': 'bad', 'version': old['version']}).status_code, 400)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                locked = ImportJob.objects.select_for_update().get(pk=self.job.pk)
                with patch('apps.imports.conflict_reports.ImportConflict.objects.bulk_create', side_effect=RuntimeError('synthetic')):
                    collect(locked, lambda: self._conflicts(101))
        self.assertEqual(self.client.get(self.url, {'version': old['version']}).data['version'], old['version'])
        self.publish(2)
        self.assertEqual(self.client.get(self.url, {'version': old['version'], 'cursor': old['next_cursor']}).status_code, 409)

    def test_cursor_from_another_job_is_rejected(self):
        self.publish(101)
        first = self.client.get(self.url).data
        other = ImportJob.objects.create(organization=self.org, entity_type='inventory')
        # Usar misma versión simulada comprueba que también se vincula al job,
        # sin depender solo del rechazo por una versión diferente.
        result = dict(self.job.result)
        other.result = result
        other.save(update_fields=['result'])
        response = self.client.get(f'/api/imports/{other.public_id}/conflicts/', {
            'version': first['version'], 'cursor': first['next_cursor'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'invalid_conflict_cursor')

    def _conflicts(self, count):
        result = _base_result()
        for row in range(1, count + 1):
            _append_conflict(result, {'row': row, 'match_confidence': 'high'})
        return result

    def test_legacy_is_converted_from_persisted_result_and_marks_missing(self):
        self.job.result = {'conflicts': [{'row': 3, 'match_confidence': 'high'}], 'skipped_conflicts': 2}
        self.job.save(update_fields=['result'])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 2)
        self.assertFalse(response.data['complete'])
        self.assertEqual(response.data['results'][0]['row'], 3)
        self.assertEqual(ImportConflict.objects.filter(job=self.job).count(), 1)

    def test_preview_is_stable_and_mapping_invalidates_old_version(self):
        self.job.source_columns = ['name', 'code', 'price']
        self.job.mapping = {'name': 'product.name', 'code': 'product.internal_code', 'price': 'presentation.sale_price'}
        self.job.rows = [['Primero', 'SAME', '10'], ['Segundo', 'SAME', '10']]
        self.job.save()
        response = self.client.post(f'/api/imports/{self.job.public_id}/validate/', format='json')
        self.assertEqual(response.status_code, 200, response.data)
        result = response.data['result']
        self.assertEqual(result['created_products'], 1)
        self.assertEqual(result['skipped_conflicts'], 1)
        version = result['conflict_report']['version']
        before = self.client.get(self.url, {'version': version}).data['results']
        Product.objects.create(organization=self.org, name='Synthetic change', internal_code='SAME')
        self.assertEqual(self.client.get(self.url, {'version': version}).data['results'], before)
        mapped = self.client.patch(f'/api/imports/{self.job.public_id}/mapping/', {'mapping': self.job.mapping}, format='json')
        self.assertEqual(mapped.status_code, 200)
        self.assertEqual(self.client.get(self.url, {'version': version}).status_code, 409)

    def test_other_tenant_cannot_read_report(self):
        self.publish(1)
        other = Organization.objects.create(name='Other synthetic')
        roles = _seed_roles(other)
        user = User.objects.create_user(username='other-order4', password='synthetic', organization=other, role='ADMIN')
        UserRole.objects.get_or_create(user=user, role=roles['ADMIN'])
        self.client.force_authenticate(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('total', response.data)

    def test_unauthenticated_cannot_read_report(self):
        self.publish(1)
        response = APIClient().get(self.url)
        self.assertIn(response.status_code, (401, 403))
        self.assertNotEqual(response.data.get('code'), 'demo_account_restricted')
        self.assertNotIn('total', response.data)
        upload = APIClient().post('/api/imports/', {}, format='multipart')
        self.assertIn(upload.status_code, (401, 403))
        self.assertNotEqual(upload.data.get('code'), 'demo_account_restricted')

    def test_commit_checks_blocking_after_reloading_locked_job(self):
        stale = ImportJob.objects.get(pk=self.job.pk)
        ImportJob.objects.filter(pk=self.job.pk).update(result={'blocking': [{'row': 1}]})
        with self.assertRaises(ImportHasBlockingErrors):
            commit_job(stale, created_by=self.user)
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.status, ImportJob.STATUS_COMMITTED)

    def test_disabled_organization_jwt_cannot_read_report(self):
        self.publish(1)
        token = str(RefreshToken.for_user(self.user).access_token)
        self.org.is_active = False
        self.org.save(update_fields=['is_active'])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.get(self.url)
        self.assertIn(response.status_code, (401, 403))
        self.assertNotEqual(response.data.get('code'), 'demo_account_restricted')
        self.assertNotIn('total', response.data)
        upload = client.post('/api/imports/', {}, format='multipart')
        self.assertIn(upload.status_code, (401, 403))
        self.assertNotEqual(upload.data.get('code'), 'demo_account_restricted')
