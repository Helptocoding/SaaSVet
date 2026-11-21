"""
Staff created via POST /api/staff/create/ must change password on first login.

The flag is set in CreateEmployeeSerializer.create (endpoint path) — NOT in
User.create_user / a signal / the model default — so test fixtures, seeds and
createsuperuser are NOT gated. See
docs/fix-provision-must-change-password-2026-06-24.md §8.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import Organization


User = get_user_model()


class StaffCreateMustChangeTests(APITestCase):
    def setUp(self):
        # Organization.create fires initialize_organization → seeds the system
        # Roles (ADMIN/VET/ASSISTANT). The admin below is created directly via
        # create_user (NOT the gated endpoint), so it is NOT must-change and can
        # act as the staff creator.
        self.org = Organization.objects.create(name='Clinica Staff Test')
        self.admin = User.objects.create_user(
            username='clinicadmin',
            email='admin@clinic.test',
            password='AdminPass1234!',
            role='ADMIN',
            organization=self.org,
        )
        self.client.force_authenticate(user=self.admin)

    def test_created_staff_must_change_password(self):
        resp = self.client.post(
            '/api/staff/create/',
            {
                'username': 'newvet',
                'first_name': 'Nueva',  # D4 (plan Equipo): obligatorio en el alta
                'email': 'vet@clinic.test',
                'password': 'VetPass1234',
                'role': 'VET',
                'license_number': '1234567',  # M01: obligatoria para VET
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

        created = User.objects.get(username='newvet')
        self.assertTrue(created.password_must_change)
        # No 24h expiry — same rationale as the provisioned admin.
        self.assertIsNone(created.password_temp_issued_at)

    def test_admin_creating_staff_is_not_self_gated(self):
        """Sanity: the creating admin (made via create_user) is not gated."""
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.password_must_change)
