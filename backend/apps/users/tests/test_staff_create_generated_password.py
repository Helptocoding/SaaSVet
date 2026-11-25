"""Fase 1 Equipo: el alta genera la contraseña inicial.

- ``POST /api/staff/create/`` ya no acepta ``password``: el sistema la genera con
  la misma fuerza que la temporal del restablecimiento (ADR p21), la devuelve una
  sola vez con ``no-store`` y nunca la registra.
- Conserva las reglas de la contraseña inicial: cambio obligatorio en el primer
  acceso y sin caducidad (sin ``password_temp_issued_at``).
- El alta es una unidad (usuario + rol RBAC) y es durable, como la reactivación.
- Un usuario o correo repetido es 400 en su campo, nunca 500.
"""
import ast
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import transaction
from django.test import override_settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from apps.core.models import UserRole
from apps.organizations.models import Organization
from apps.users.access import ACCESS_PASSWORD_CHANGE_PENDING, ACCESS_PENDING_FIRST_LOGIN
from apps.users.services import TEMP_PASSWORD_ENTROPY_BYTES, create_staff_member

User = get_user_model()

CREATE_URL = '/api/staff/create/'
LOGIN_URL = '/api/token/'
BACKEND = Path(__file__).resolve().parents[3]
FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Alta', timezone='UTC')
        self.admin = User.objects.create_user(
            username='alta_admin', email='alta_admin@example.com', password='x',
            organization=self.org, role='ADMIN', first_name='Ada')
        self.client.force_authenticate(self.admin)

    def create(self, **over):
        payload = {
            'username': 'nueva.vet', 'email': 'nueva.vet@example.com',
            'first_name': 'Nueva', 'last_name': 'Vet', 'role': 'VET',
            'license_number': '1234567',
        }
        payload.update(over)
        return self.client.post(CREATE_URL, payload, format='json')


class GeneratedPasswordTests(_Fixtures):
    def test_creates_with_a_generated_one_time_password(self):
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res['Cache-Control'], 'no-store')
        temp = res.data['temp_password']
        # token_urlsafe(16) → 22 caracteres; misma fuerza que el restablecimiento.
        self.assertGreaterEqual(len(temp), int(TEMP_PASSWORD_ENTROPY_BYTES * 4 / 3))
        self.assertIsNone(res.data['expires_in_seconds'])
        self.assertTrue(res.data['must_change_on_first_login'])
        self.assertEqual(res.data['member']['username'], 'nueva.vet')
        self.assertEqual(res.data['member']['access']['status'], ACCESS_PENDING_FIRST_LOGIN)

        created = User.objects.get(username='nueva.vet')
        self.assertTrue(created.check_password(temp))
        self.assertTrue(created.password_must_change)
        self.assertIsNone(created.password_temp_issued_at)  # la inicial no caduca
        self.assertEqual(created.organization_id, self.org.pk)
        self.assertTrue(UserRole.objects.filter(
            user=created, role__name='VET', role__organization=self.org).exists())

    def test_each_creation_gets_a_different_password(self):
        first = self.create().data['temp_password']
        second = self.create(username='otra.vet', email='otra.vet@example.com').data['temp_password']
        self.assertNotEqual(first, second)

    def test_rejects_a_password_in_the_payload(self):
        res = self.create(password='Segura123')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('password', res.data)
        self.assertFalse(User.objects.filter(username='nueva.vet').exists())

    def test_the_generated_password_logs_in_and_forces_the_change(self):
        temp = self.create().data['temp_password']
        client = APIClient()
        res = client.post(LOGIN_URL, {'username': 'nueva.vet@example.com', 'password': temp},
                          format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertTrue(res.data['must_change_password'])
        row = next(r for r in self.client.get('/api/staff/').data if r['username'] == 'nueva.vet')
        self.assertEqual(row['access']['status'], ACCESS_PASSWORD_CHANGE_PENDING)
        self.assertIsNotNone(row['access']['last_login'])

    def test_password_is_never_logged(self):
        with self.assertLogs('users.events', level='INFO') as logs:
            with self.captureOnCommitCallbacks(execute=True):
                res = self.create()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        temp = res.data['temp_password']
        events = [r for r in logs.records if getattr(r, 'event', None) == 'STAFF_CREATED']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].target_username, 'nueva.vet')
        for record in logs.records:
            self.assertNotIn(temp, record.getMessage())
            self.assertNotIn(temp, str(record.__dict__))

    def test_username_taken_case_insensitively_is_a_field_error(self):
        User.objects.create_user(username='Ocupado', password='x', organization=self.org)
        res = self.create(username='ocupado')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['username'], ['Este nombre de usuario no está disponible.'])

    def test_role_outside_the_clinic_roles_is_rejected(self):
        for role in ('ADMIN_SAAS', 'AGENT'):
            with self.subTest(role):
                res = self.create(role=role)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
                self.assertIn('role', res.data)

    def test_vet_cannot_create(self):
        vet = User.objects.create_user(
            username='alta_vet', password='x', organization=self.org, role='VET')
        self.client.force_authenticate(vet)
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertFalse(User.objects.filter(username='nueva.vet').exists())


class CreateServiceTests(_Fixtures):
    """El servicio directamente: carreras, atomicidad y durabilidad."""

    def data(self, **over):
        data = {
            'username': 'svc.vet', 'email': 'svc.vet@example.com', 'first_name': 'Svc',
            'last_name': '', 'role': 'VET', 'specialties': [], 'license_number': '1234567',
        }
        data.update(over)
        return data

    def test_concurrent_username_loses_on_the_constraint_with_a_field_error(self):
        # La validación del serializer ya pasó (otra alta ganó entre medias): la
        # restricción de la base decide y el perdedor recibe 400, no 500.
        User.objects.create_user(username='svc.vet', password='x', organization=self.org)
        with self.assertRaises(ValidationError) as ctx:
            create_staff_member(admin=self.admin, data=self.data())
        self.assertIn('username', ctx.exception.detail)

    def test_concurrent_email_loses_on_the_constraint_with_a_field_error(self):
        User.objects.create_user(
            username='otro', email='svc.vet@example.com', password='x', organization=self.org)
        with self.assertRaises(ValidationError) as ctx:
            create_staff_member(admin=self.admin, data=self.data())
        self.assertIn('email', ctx.exception.detail)

    def test_a_failure_after_creating_leaves_no_member(self):
        with mock.patch('apps.users.services._assign_system_role', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                create_staff_member(admin=self.admin, data=self.data())
        self.assertFalse(User.objects.filter(username='svc.vet').exists())

    def test_refuses_to_run_inside_another_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                create_staff_member(admin=self.admin, data=self.data())
        self.assertFalse(User.objects.filter(username='svc.vet').exists())

    def test_rejects_a_role_outside_the_clinic_roles(self):
        with self.assertRaises(ValidationError):
            create_staff_member(admin=self.admin, data=self.data(role='ADMIN_SAAS'))


class SingleCallerGateTests(APITestCase):
    def test_create_staff_member_has_a_single_production_caller(self):
        callers = []
        for root in (BACKEND / 'apps', BACKEND / 'config'):
            for path in root.rglob('*.py'):
                parts = set(path.relative_to(BACKEND).parts)
                if parts & {'tests', 'migrations', '__pycache__'} or path.name.startswith('test_'):
                    continue
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and getattr(node.func, 'id', getattr(node.func, 'attr', None))
                        == 'create_staff_member'
                    ):
                        callers.append(path.relative_to(BACKEND).as_posix())
        self.assertEqual(
            callers, ['apps/users/views.py'],
            'create_staff_member es durable: un llamador nuevo debe invocarlo fuera '
            'de cualquier transacción.',
        )

