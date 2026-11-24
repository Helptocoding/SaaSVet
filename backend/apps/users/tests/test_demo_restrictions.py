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
        self.assertEqual(res.data['code'], 'permission_denied')

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


class DemoSeedAccountsInEquipoTests(TestCase):
    """Plan Equipo (D5): las tres cuentas semilla de la demo no se editan,
    restablecen ni desactivan por la API, y en la demo solo se aceptan correos
    de dominios reservados. La autorización está en los servicios:
    `demo_protected` solo sirve a la interfaz."""

    def setUp(self):
        from apps.core.demo_reset import DEMO_SEED_USERNAMES
        from apps.core.models import Permission, Role, UserRole, set_current_user

        set_current_user(None)
        _clear_caches()
        self.org = Organization.objects.create(name='Demo Clinic', is_demo=True)
        self.admin = User.objects.create(
            username='visitor_admin', organization=self.org, role='ADMIN',
        )
        role, _ = Role.objects.get_or_create(
            name='ADMIN', organization=self.org, defaults={'is_system_role': True},
        )
        role.permissions.set([Permission.objects.get_or_create(code='*.*')[0]])
        UserRole.objects.get_or_create(user=self.admin, role=role)
        self.seeds = [
            User.objects.create(username=username, organization=self.org, role='ASSISTANT')
            for username in sorted(DEMO_SEED_USERNAMES)
        ]
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_seed_accounts_are_protected_through_the_api(self):
        for seed in self.seeds:
            with self.subTest(username=seed.username):
                url = f'/api/staff/{seed.public_id}/'
                for res in (
                    self.client.patch(url, {'first_name': 'Otro'}, format='json'),
                    self.client.post(f'{url}reset-password/'),
                    self.client.delete(url),
                ):
                    self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)
                    self.assertEqual(res.data['code'], 'demo_seed_account')
                seed.refresh_from_db()
                self.assertTrue(seed.is_active)
                self.assertEqual(seed.first_name, '')

    def test_list_marks_seed_accounts_for_the_ui(self):
        res = self.client.get('/api/staff/')
        flags = {row['username']: row['demo_protected'] for row in res.data}
        for seed in self.seeds:
            self.assertTrue(flags[seed.username])
        self.assertFalse(flags['visitor_admin'])

    def test_no_visitor_can_create_a_seed_username(self):
        from apps.core.demo_reset import DEMO_SEED_USERNAMES
        from apps.users.serializers import USERNAME_REGEX

        for username in DEMO_SEED_USERNAMES:
            self.assertIsNone(USERNAME_REGEX.match(username), username)

    def test_seed_username_outside_the_demo_is_not_protected(self):
        from apps.core.demo_reset import DEMO_VET_USERNAME
        from apps.users.services import is_demo_seed_account

        real = Organization.objects.create(name='Real Clinic')
        user = User(username=DEMO_VET_USERNAME + '.copy', organization=real)
        self.assertFalse(is_demo_seed_account(user))
        user.username = DEMO_VET_USERNAME
        self.assertFalse(is_demo_seed_account(user))

    def test_demo_requires_reserved_email_domains(self):
        payload = {
            'username': 'visitante', 'first_name': 'Visita',
            'role': 'ASSISTANT',
        }
        res = self.client.post('/api/staff/create/', {**payload, 'email': 'alguien@gmail.com'},
                               format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['email'],
                         ['En la demo usa un correo de ejemplo, como nombre@example.com.'])
        for n, email in enumerate(('a@example.com', 'b@example.net', 'c@example.org',
                                    'd@clinica.test', 'e@algo.example')):
            res = self.client.post(
                '/api/staff/create/', {**payload, 'username': f'visitante{n}', 'email': email},
                format='json',
            )
            self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

        visitor = User.objects.get(username='visitante0')
        res = self.client.patch(f'/api/staff/{visitor.public_id}/', {'email': 'real@gmail.com'},
                                format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.data)

    def test_visitor_accounts_can_be_managed(self):
        visitor = User.objects.create(
            username='visitante_x', email='x@example.com', organization=self.org, role='VET',
            license_number='1234567',
        )
        url = f'/api/staff/{visitor.public_id}/'
        self.assertEqual(self.client.patch(url, {'first_name': 'Equis'}, format='json').status_code, 200)
        self.assertEqual(self.client.post(f'{url}reset-password/').status_code, 201)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.post(f'{url}reactivate/').status_code, 201)

    def test_seed_usernames_have_a_single_source(self):
        from apps.core.demo_reset import DEMO_SEED_USERNAMES
        from apps.core.management.commands._demo_data import DEMO_USERS

        self.assertEqual({u['username'] for u in DEMO_USERS}, set(DEMO_SEED_USERNAMES))
