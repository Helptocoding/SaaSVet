"""Fase 1 Equipo: registro del último acceso (``User.last_login``).

Antes nunca se actualizaba (``SIMPLE_JWT['UPDATE_LAST_LOGIN']`` apagado). Ahora
``services.record_user_access`` lo escribe:

- al iniciar sesión, solo si pasó todas las compuertas (organización inactiva,
  contraseña temporal vencida); un intento rechazado no cuenta como acceso;
- al renovar la sesión (refresh), porque una sesión que se renueva sola también
  es actividad;
- como máximo una vez por hora, con un ``UPDATE`` condicional de ese único
  campo (la versión de sesión y el resto no se tocan);
- nunca para cuentas de servicio; un error de base no rompe la autenticación.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import DatabaseError
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.users.services import (
    ACCESS_RECORD_INTERVAL,
    TEMP_PASSWORD_VALIDITY,
    ensure_agent_user,
    record_user_access,
)

User = get_user_model()

LOGIN_URL = '/api/token/'
REFRESH_URL = '/api/token/refresh/'
PASSWORD = 'OldPass1234!'
FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        cache.clear()
        caches['throttle_login'].clear()
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica Acceso Reg', timezone='UTC')
        self.vet = User.objects.create_user(
            username='la_vet', email='la_vet@example.com', password=PASSWORD,
            organization=self.org, role='VET', first_name='Eva', license_number='1234567')

    def login(self, password=PASSWORD):
        return APIClient().post(
            LOGIN_URL, {'username': 'la_vet@example.com', 'password': password}, format='json')

    def last_login(self):
        return User.objects.values_list('last_login', flat=True).get(pk=self.vet.pk)

    def age_last_login(self, delta):
        User.objects.filter(pk=self.vet.pk).update(last_login=timezone.now() - delta)


class LoginRecordsAccessTests(_Fixtures):
    def test_successful_login_records_the_access(self):
        self.assertIsNone(self.last_login())
        before = timezone.now()
        res = self.login()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertGreaterEqual(self.last_login(), before)

    def test_only_last_login_changes(self):
        snapshot = User.objects.values().get(pk=self.vet.pk)
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        after = User.objects.values().get(pk=self.vet.pk)
        changed = {key for key in snapshot if snapshot[key] != after[key]}
        self.assertEqual(changed, {'last_login'})

    def test_at_most_one_write_per_interval(self):
        self.login()
        first = self.last_login()
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertEqual(self.last_login(), first)

        self.age_last_login(ACCESS_RECORD_INTERVAL + timedelta(minutes=1))
        stale = self.last_login()
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)
        self.assertGreater(self.last_login(), stale)

    def test_wrong_password_is_not_an_access(self):
        res = self.login(password='Incorrecta123')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)
        self.assertIsNone(self.last_login())

    def test_expired_temporary_password_is_not_an_access(self):
        User.objects.filter(pk=self.vet.pk).update(
            password_must_change=True,
            password_temp_issued_at=timezone.now() - TEMP_PASSWORD_VALIDITY - timedelta(hours=1),
        )
        res = self.login()
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertIsNone(self.last_login())

    def test_inactive_organization_is_not_an_access(self):
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        res = self.login()
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertIsNone(self.last_login())

    def test_inactive_member_is_not_an_access(self):
        User.objects.filter(pk=self.vet.pk).update(is_active=False)
        res = self.login()
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)
        self.assertIsNone(self.last_login())

    def test_a_database_error_does_not_break_the_login(self):
        with mock.patch('django.db.models.query.QuerySet.update', side_effect=DatabaseError):
            with self.assertLogs('users.events', level='WARNING') as logs:
                res = self.login()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertIn('USER_ACCESS_RECORD_FAILED', logs.output[0])
        self.assertIsNone(self.last_login())


class RefreshRecordsAccessTests(_Fixtures):
    def test_refresh_records_activity(self):
        refresh = self.login().data['refresh']
        self.age_last_login(ACCESS_RECORD_INTERVAL + timedelta(minutes=5))
        stale = self.last_login()
        res = APIClient().post(REFRESH_URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertGreater(self.last_login(), stale)

    def test_refresh_within_the_interval_does_not_write(self):
        refresh = self.login().data['refresh']
        recorded = self.last_login()
        res = APIClient().post(REFRESH_URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(self.last_login(), recorded)

    def test_revoked_refresh_is_not_an_access(self):
        from apps.users.services import bump_session_version

        refresh = self.login().data['refresh']
        self.age_last_login(ACCESS_RECORD_INTERVAL + timedelta(minutes=5))
        stale = self.last_login()
        bump_session_version(self.vet)  # p. ej., un restablecimiento
        res = APIClient().post(REFRESH_URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)
        self.assertEqual(self.last_login(), stale)


class RecordUserAccessServiceTests(_Fixtures):
    def test_service_accounts_are_skipped(self):
        agent, _ = ensure_agent_user(self.org)
        self.assertFalse(record_user_access(agent))
        agent.refresh_from_db()
        self.assertIsNone(agent.last_login)

    def test_single_conditional_update(self):
        with self.assertNumQueries(1):
            self.assertTrue(record_user_access(self.vet))
        with self.assertNumQueries(1):
            self.assertFalse(record_user_access(self.vet))
