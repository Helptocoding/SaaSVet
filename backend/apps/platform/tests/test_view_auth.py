"""
Authorization tests for `PlatformOrgCreateView`.

The view's permission gate is the only thing standing between a regular
tenant ADMIN (or VET / ASSISTANT) and the ability to create new tenants.
A regression here would let any clinic admin spin up sibling tenants —
catastrophic for billing, support, and isolation.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization


User = get_user_model()


PAYLOAD = {
    'name': 'Clinica Test',
    'timezone': 'America/Mexico_City',
    'tax_rate': '0.1600',
    'admin_username': 'newadmin',
    'admin_email': 'newadmin@test.com',
    'admin_password': 'SuperPass1234!',
    'admin_first_name': 'Laura',
    'admin_last_name': 'García',
}


class PlatformOrgCreateAuthTests(TestCase):
    """Permission matrix — every non-ADMIN_SAAS caller must be rejected."""

    URL = '/api/platform/organizations/'

    def setUp(self):
        self.client = APIClient()

        # Tenant org with regular roles.
        self.tenant_org = Organization.objects.create(name='Clinica X')
        self.admin = User.objects.create_user(
            username='clinic_admin',
            email='admin@clinica.com',
            password='AdminPass1234!',
            role='ADMIN',
            organization=self.tenant_org,
        )
        self.vet = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='VetPass1234!',
            role='VET',
            organization=self.tenant_org,
        )
        self.assistant = User.objects.create_user(
            username='asst1',
            email='asst@clinica.com',
            password='AsstPass1234!',
            role='ASSISTANT',
            organization=self.tenant_org,
        )

        # Platform operator.
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.platform_op = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )

    def _force(self, user):
        self.client.force_authenticate(user=user)

    def test_admin_saas_authorized_201(self):
        self._force(self.platform_op)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('organization', response.data)
        self.assertIn('admin', response.data)

    def test_regular_admin_forbidden_403(self):
        self._force(self.admin)
        with self.assertLogs('platform.events', level='WARNING') as logs:
            response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        denied = [r for r in logs.records if r.msg == 'PLATFORM_ACCESS_DENIED']
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0].actor_id, self.admin.pk)
        self.assertEqual(denied[0].actor_role, 'ADMIN')

    def test_vet_forbidden_403(self):
        self._force(self.vet)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assistant_forbidden_403(self):
        self._force(self.assistant)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_401(self):
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_saas_without_is_staff_forbidden_403(self):
        """ADMIN_SAAS predicate requires is_staff=True. A degraded
        superuser (is_staff=False) must still be blocked."""
        self.platform_op.is_staff = False
        self.platform_op.save(update_fields=['is_staff'])
        self._force(self.platform_op)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_saas_without_is_superuser_forbidden_403(self):
        """Same predicate — is_superuser=False must be rejected even
        if role is ADMIN_SAAS."""
        self.platform_op.is_superuser = False
        self.platform_op.save(update_fields=['is_superuser'])
        self._force(self.platform_op)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_role_admin_with_superuser_flags_still_forbidden(self):
        """Defense in depth: a clinic ADMIN that somehow has both flags
        (shouldn't, but enforce predicate) is still blocked because
        role != 'ADMIN_SAAS'."""
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save(update_fields=['is_staff', 'is_superuser'])
        self._force(self.admin)
        response = self.client.post(self.URL, PAYLOAD, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
