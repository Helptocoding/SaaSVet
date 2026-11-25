"""M01 (orden 7): cédula profesional en Equipo.

Alta: obligatoria para VET. Edición: PATCH /api/staff/<uuid>/ con `staff.update`,
que solo acepta especialidad y cédula. Los roles salen de la siembra real de la
organización, no de un comodín.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.permissions import user_has_permission_strict
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS, SENSITIVE_CODES
from apps.organizations.models import Organization

User = get_user_model()
CREATE_URL = '/api/staff/create/'


def staff_url(user):
    return f'/api/staff/{user.public_id}/'


class StaffLicenseTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org Cedula M01', timezone='UTC')
        cls.other_org = Organization.objects.create(name='Org Cedula Otra', timezone='UTC')
        cls.admin = User.objects.create_user(
            username='admin_ced', password='x', organization=cls.org, role='ADMIN')
        cls.vet = User.objects.create_user(
            username='vet_ced', password='x', organization=cls.org, role='VET',
            license_number='1234567')
        cls.assistant = User.objects.create_user(
            username='asst_ced', password='x', organization=cls.org, role='ASSISTANT')
        cls.foreign_vet = User.objects.create_user(
            username='vet_ced_otra', password='x', organization=cls.other_org, role='VET',
            license_number='7654321')

    def _create(self, **overrides):
        payload = {
            'username': 'nuevo_ced', 'email': 'nuevo_ced@example.com',
            'first_name': 'Ana', 'role': 'VET',
        }
        payload.update(overrides)
        self.client.force_authenticate(self.admin)
        return self.client.post(CREATE_URL, payload, format='json')

    def test_catalog_grants_staff_update_only_to_admin(self):
        self.assertIn('staff.update', PERMISSION_CODES)
        self.assertIn('staff.update', SENSITIVE_CODES)
        self.assertIn('staff.update', PERMISSIONS['ADMIN'])
        self.assertNotIn('staff.update', PERMISSIONS['VET'])
        self.assertNotIn('staff.update', PERMISSIONS['ASSISTANT'])
        self.assertTrue(user_has_permission_strict(self.admin, 'staff.update'))
        self.assertFalse(user_has_permission_strict(self.vet, 'staff.update'))

    def test_create_vet_requires_license(self):
        r = self._create()
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        # StaffCreateView devuelve serializer.errors sin el sobre {code, errors}.
        self.assertIn('license_number', r.data)
        self.assertFalse(User.objects.filter(username='nuevo_ced').exists())

    def test_create_vet_with_license_strips_spaces(self):
        r = self._create(license_number='  1234567 ')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        # Fase 1 Equipo: el alta responde con el integrante en `member`.
        self.assertEqual(r.data['member']['license_number'], '1234567')
        self.assertEqual(User.objects.get(username='nuevo_ced').license_number, '1234567')

    def test_create_assistant_without_license(self):
        r = self._create(role='ASSISTANT')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        self.assertEqual(r.data['member']['license_number'], '')

    def test_create_rejects_bad_formats(self):
        for value in ('1234', '12345678901', '12a4567', '123 4567'):
            with self.subTest(value=value):
                r = self._create(license_number=value)
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
                self.assertIn('license_number', r.data)

    def test_staff_list_exposes_license(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/staff/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        row = next(m for m in r.data if m['username'] == 'vet_ced')
        self.assertEqual(row['license_number'], '1234567')

    def test_admin_patches_vet_license_and_specialty(self):
        self.client.force_authenticate(self.admin)
        with self.assertLogs('users.events', level='INFO') as logs:
            r = self.client.patch(staff_url(self.vet), {
                'license_number': '87654321', 'specialties': ['surgery']}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.vet.refresh_from_db()
        self.assertEqual((self.vet.license_number, self.vet.specialties), ('87654321', ['surgery']))
        self.assertEqual(r.data['license_number'], '87654321')
        self.assertTrue(any('STAFF_PROFILE_UPDATED' in line for line in logs.output))

    def test_patch_cannot_clear_vet_license(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.vet), {'license_number': ''}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.license_number, '1234567')

    def test_admin_license_is_optional_and_self_editable(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.admin), {'license_number': '55555'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        r = self.client.patch(staff_url(self.admin), {'license_number': ''}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.license_number, '')

    def test_patch_rejects_other_fields(self):
        # ADR p69 §9: `role` ya es parte del PATCH (con sus propias reglas); el
        # usuario, la contraseña y el estado siguen teniendo su propio camino.
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.assistant), {
            'username': 'otro', 'license_number': '12345'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assistant.refresh_from_db()
        self.assertEqual((self.assistant.username, self.assistant.license_number),
                         ('asst_ced', ''))

    def test_patch_rejects_empty_body(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.vet), {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_patch_requires_staff_update(self):
        self.client.force_authenticate(self.vet)
        r = self.client.patch(staff_url(self.vet), {'license_number': '99999'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.license_number, '1234567')

    def test_patch_other_tenant_is_404(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.foreign_vet), {'license_number': '99999'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        self.foreign_vet.refresh_from_db()
        self.assertEqual(self.foreign_vet.license_number, '7654321')

    def test_delete_still_deactivates(self):
        target = User.objects.create_user(
            username='asst_baja', password='x', organization=self.org, role='ASSISTANT')
        self.client.force_authenticate(self.admin)
        r = self.client.delete(staff_url(target))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT, r.content)
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_database_rejects_non_digit_license(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.assistant.pk).update(license_number='abc12')
