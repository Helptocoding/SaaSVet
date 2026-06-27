"""
Restricciones de la cuenta demo (Organization.is_demo=True).

Regla de negocio: los usuarios de la org demo NO pueden cambiar su contraseña
(credenciales compartidas fijas) ni importar datos (contaminaría el dataset
demo). El frontend oculta ambas opciones; estos tests protegen el enforcement
backend (NotDemoAccount), que es la autoridad — un curl/Postman debe ser
rechazado igual.

Cubre:
  - /api/me/ expone is_demo (true demo / false real) para que el front oculte.
  - /api/users/change-password/ → 403 para demo, NO-403 (validación normal) para real.
  - /api/imports/ → 403 para demo, NO-403 (validación normal) para real.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization

User = get_user_model()

ME = '/api/me/'
CHANGE_PW = '/api/users/change-password/'
IMPORTS = '/api/imports/'


def _user(org, role='ADMIN', username='u1'):
    return User.objects.create_user(
        username=username,
        email=f'{username}@x.com',
        password='OldPass1234!',
        role=role,
        organization=org,
    )


def _clear_caches():
    cache.clear()
    caches['throttle_login'].clear()


class MeExposesIsDemoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _clear_caches()

    def test_demo_user_me_is_demo_true(self):
        org = Organization.objects.create(name='Demo Clinic', is_demo=True)
        self.client.force_authenticate(user=_user(org, username='demo'))
        res = self.client.get(ME)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['is_demo'])

    def test_real_user_me_is_demo_false(self):
        org = Organization.objects.create(name='Real Clinic')  # is_demo default False
        self.client.force_authenticate(user=_user(org, username='real'))
        res = self.client.get(ME)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['is_demo'])


class DemoChangePasswordBlockedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _clear_caches()

    def _payload(self):
        return {
            'current_password': 'OldPass1234!',
            'new_password': 'BrandNew9876!',
            'confirm_password': 'BrandNew9876!',
        }

    def test_demo_user_cannot_change_password_403(self):
        org = Organization.objects.create(name='Demo Clinic', is_demo=True)
        self.client.force_authenticate(user=_user(org, role='VET', username='demovet'))
        res = self.client.post(CHANGE_PW, self._payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_real_user_not_blocked_by_demo_guard(self):
        """Tenant real: el guard demo NO aplica → llega a la lógica normal
        (200 con cambio válido), nunca 403 por demo."""
        org = Organization.objects.create(name='Real Clinic')
        self.client.force_authenticate(user=_user(org, role='VET', username='realvet'))
        res = self.client.post(CHANGE_PW, self._payload(), format='json')
        self.assertNotEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class DemoImportBlockedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        _clear_caches()

    def test_demo_admin_cannot_import_403(self):
        org = Organization.objects.create(name='Demo Clinic', is_demo=True)
        self.client.force_authenticate(user=_user(org, role='ADMIN', username='demoadmin'))
        res = self.client.post(IMPORTS, {}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_real_admin_not_blocked_by_demo_guard(self):
        """Tenant real con permiso: el guard demo NO aplica → pasa permisos y
        llega a validación de payload (400), nunca 403 por demo."""
        org = Organization.objects.create(name='Real Clinic')
        self.client.force_authenticate(user=_user(org, role='ADMIN', username='realadmin'))
        res = self.client.post(IMPORTS, {}, format='multipart')
        self.assertNotEqual(res.status_code, status.HTTP_403_FORBIDDEN)
