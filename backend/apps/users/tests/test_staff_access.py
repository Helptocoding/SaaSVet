"""Fase 1 Equipo: estado de acceso de cada integrante y privacidad del listado.

- El estado se deriva solo de campos existentes de ``User`` (apps/users/access.py),
  con una prioridad fija.
- ``GET /api/staff/`` entrega el integrante completo con su estado de acceso solo
  a quien gestiona personal; VET y ASSISTANT (``staff.list``, para Citas) reciben
  el directorio mínimo, sin correo, usuario, cédula ni datos de acceso.

Los roles son los reales: ``Organization.objects.create`` siembra los roles de
sistema y ``create_user`` asigna el ``UserRole`` por señal.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.users.access import (
    ACCESS_ACTIVE,
    ACCESS_INACTIVE,
    ACCESS_PASSWORD_CHANGE_PENDING,
    ACCESS_PENDING_FIRST_LOGIN,
    ACCESS_STATUSES,
    ACCESS_TEMP_PASSWORD_ACTIVE,
    ACCESS_TEMP_PASSWORD_EXPIRED,
    access_status,
    access_summary,
    can_manage_staff,
    temp_password_expires_at,
)
from apps.users.services import TEMP_PASSWORD_VALIDITY

User = get_user_model()

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)

DIRECTORY_FIELDS = {'id', 'public_id', 'first_name', 'last_name', 'role'}
SECRET_FIELDS = {
    'password', 'session_version', 'password_temp_issued_at', 'password_must_change',
    'is_superuser', 'is_staff', 'is_service_account', 'groups', 'user_permissions',
}


def _member(**fields):
    defaults = {
        'is_active': True, 'password_must_change': False,
        'password_temp_issued_at': None, 'last_login': None,
    }
    defaults.update(fields)
    return User(**defaults)


class AccessStatusTests(SimpleTestCase):
    """Cada estado y la prioridad entre ellos, sin base de datos."""

    def test_each_status(self):
        now = timezone.now()
        cases = {
            ACCESS_ACTIVE: _member(last_login=now),
            ACCESS_INACTIVE: _member(is_active=False),
            ACCESS_PENDING_FIRST_LOGIN: _member(password_must_change=True),
            ACCESS_PASSWORD_CHANGE_PENDING: _member(password_must_change=True, last_login=now),
            ACCESS_TEMP_PASSWORD_ACTIVE: _member(
                password_must_change=True, password_temp_issued_at=now - timedelta(hours=1)),
            ACCESS_TEMP_PASSWORD_EXPIRED: _member(
                password_must_change=True,
                password_temp_issued_at=now - TEMP_PASSWORD_VALIDITY - timedelta(minutes=1)),
        }
        self.assertEqual(set(cases), set(ACCESS_STATUSES))
        for expected, user in cases.items():
            with self.subTest(expected):
                self.assertEqual(access_status(user), expected)

    def test_inactive_wins_over_every_password_state(self):
        old = timezone.now() - TEMP_PASSWORD_VALIDITY - timedelta(hours=1)
        user = _member(is_active=False, password_must_change=True, password_temp_issued_at=old)
        self.assertEqual(access_status(user), ACCESS_INACTIVE)

    def test_active_never_used_account_is_active_without_last_access(self):
        # Sin contraseña pendiente pero sin accesos registrados (anteriores a esta
        # fase): «activo», y el último acceso queda vacío, no inventado.
        summary = access_summary(_member())
        self.assertEqual(summary['status'], ACCESS_ACTIVE)
        self.assertIsNone(summary['last_login'])

    def test_expiry_matches_the_login_rule(self):
        issued = timezone.now() - timedelta(hours=3)
        user = _member(password_must_change=True, password_temp_issued_at=issued)
        self.assertEqual(temp_password_expires_at(user), issued + TEMP_PASSWORD_VALIDITY)
        # La contraseña inicial del alta (sin fecha de emisión) no vence.
        self.assertIsNone(temp_password_expires_at(_member(password_must_change=True)))
        # Ya cambiada: ya no hay temporal aunque quede la fecha.
        self.assertIsNone(temp_password_expires_at(_member(password_temp_issued_at=issued)))

    def test_summary_has_only_public_keys(self):
        summary = access_summary(_member(last_login=timezone.now()))
        self.assertEqual(set(summary), {'status', 'last_login', 'temp_password_expires_at'})


@FAST_HASHER
class StaffListPrivacyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica Acceso', timezone='UTC')
        cls.other_org = Organization.objects.create(name='Clinica Ajena', timezone='UTC')
        cls.admin = User.objects.create_user(
            username='acc_admin', email='acc_admin@example.com', password='x',
            organization=cls.org, role='ADMIN', first_name='Ada')
        cls.vet = User.objects.create_user(
            username='acc_vet', email='acc_vet@example.com', password='x',
            organization=cls.org, role='VET', first_name='Eva', license_number='1234567')
        cls.assistant = User.objects.create_user(
            username='acc_asst', email='acc_asst@example.com', password='x',
            organization=cls.org, role='ASSISTANT', first_name='Ana')
        cls.pending = User.objects.create_user(
            username='acc_new', email='acc_new@example.com', password='x',
            organization=cls.org, role='ASSISTANT', first_name='Nuevo',
            password_must_change=True)
        cls.foreign = User.objects.create_user(
            username='acc_foreign', email='acc_foreign@example.com', password='x',
            organization=cls.other_org, role='VET', first_name='Otra',
            license_number='7654321')

    def _list(self, user, **params):
        self.client.force_authenticate(user)
        return self.client.get('/api/staff/', params)

    def test_manager_rows_carry_access_and_no_secrets(self):
        res = self._list(self.admin)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        rows = {row['username']: row for row in res.data}
        self.assertEqual(rows['acc_new']['access']['status'], ACCESS_PENDING_FIRST_LOGIN)
        self.assertEqual(rows['acc_vet']['access']['status'], ACCESS_ACTIVE)
        for row in rows.values():
            self.assertFalse(SECRET_FIELDS & set(row), row)
            self.assertFalse(SECRET_FIELDS & set(row['access']), row)

    def test_vet_and_assistant_get_the_minimal_directory(self):
        for user in (self.vet, self.assistant):
            with self.subTest(user.role):
                res = self._list(user)
                self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
                self.assertTrue(res.data)
                for row in res.data:
                    self.assertEqual(set(row), DIRECTORY_FIELDS)
                body = res.content.decode()
                self.assertNotIn('acc_vet@example.com', body)
                self.assertNotIn('1234567', body)

    def test_directory_still_serves_the_appointment_vet_picker(self):
        # Citas filtra VET/ADMIN por rol y usa el PK en el cuerpo de la cita.
        res = self._list(self.assistant)
        vet_row = next(row for row in res.data if row['id'] == self.vet.pk)
        self.assertEqual(vet_row['role'], 'VET')
        self.assertEqual(vet_row['first_name'], 'Eva')

    def test_role_filter_keeps_the_projection(self):
        res = self._list(self.vet, role='VET')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual({row['id'] for row in res.data}, {self.vet.pk})
        self.assertEqual(set(res.data[0]), DIRECTORY_FIELDS)

    def test_no_rows_from_another_clinic(self):
        for user in (self.admin, self.vet):
            with self.subTest(user.role):
                ids = {row['id'] for row in self._list(user).data}
                self.assertNotIn(self.foreign.pk, ids)

    def test_non_manager_cannot_list_inactive(self):
        res = self._list(self.vet, archived='true')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)

    def test_inactive_rows_report_inactive(self):
        User.objects.filter(pk=self.assistant.pk).update(is_active=False)
        res = self._list(self.admin, archived='true')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        rows = {row['username']: row for row in res.data}
        self.assertEqual(rows['acc_asst']['access']['status'], ACCESS_INACTIVE)

    def test_reset_shows_the_temporary_password_and_its_expiry(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(f'/api/staff/{self.vet.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        row = next(r for r in self._list(self.admin).data if r['username'] == 'acc_vet')
        self.assertEqual(row['access']['status'], ACCESS_TEMP_PASSWORD_ACTIVE)
        self.vet.refresh_from_db()
        expected = self.vet.password_temp_issued_at + TEMP_PASSWORD_VALIDITY
        self.assertEqual(
            row['access']['temp_password_expires_at'],
            expected.isoformat().replace('+00:00', 'Z'),
        )


class CanManageStaffTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica Gestion', timezone='UTC')

    def _user(self, username, role):
        return User.objects.create_user(
            username=username, password='x', organization=self.org, role=role)

    def test_seeded_roles(self):
        self.assertTrue(can_manage_staff(self._user('cm_admin', 'ADMIN')))
        self.assertFalse(can_manage_staff(self._user('cm_vet', 'VET')))
        self.assertFalse(can_manage_staff(self._user('cm_asst', 'ASSISTANT')))

    def test_any_single_management_permission_is_enough(self):
        user = self._user('cm_reactivate_only', 'ASSISTANT')
        role = Role.objects.create(name='SOLO_REACTIVAR', organization=self.org)
        role.permissions.set([
            Permission.objects.get_or_create(code='staff.list')[0],
            Permission.objects.get_or_create(code='staff.reactivate')[0],
        ])
        UserRole.objects.filter(user=user).delete()
        UserRole.objects.create(user=user, role=role)
        self.assertTrue(can_manage_staff(user))
