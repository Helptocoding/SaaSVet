"""ADR p65 — versión de sesión (F0 del plan de Equipo).

Garantía: un access o refresh token emitido antes de desactivar, restablecer
(de clínica o de plataforma) o cambiar la contraseña se rechaza en su siguiente
uso, sin esperar a que venza. La reactivación se prueba con su servicio (F3).

Las pruebas usan tokens reales y la cadena de autenticación completa; nunca
``force_authenticate`` para el usuario cuyo token se pone a prueba.
"""
import threading
from unittest import mock

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import connection, transaction
from django.http import Http404
from django.test import RequestFactory, TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.agent.executor import mint_agent_token
from apps.core.authentication import (
    SESSION_VERSION_CLAIM,
    TenantJWTAuthentication,
)
from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.organizations.models import Organization
from apps.platform.services.platform_reset_password import platform_reset_password
from apps.users.services import (
    bump_session_version,
    change_password,
    ensure_agent_user,
    reset_password_for_staff,
)

User = get_user_model()

LOGIN_URL = '/api/token/'
REFRESH_URL = '/api/token/refresh/'
LOGOUT_URL = '/api/token/logout/'
ME_URL = '/api/me/'
CHANGE_URL = '/api/users/change-password/'
OLD_PASSWORD = 'OldPass1234!'
NEW_PASSWORD = 'BrandNewPass1234!'

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


def _seed_admin_role(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    role, _ = Role.objects.get_or_create(
        name='ADMIN', organization=org, defaults={'is_system_role': True},
    )
    role.permissions.set([wildcard])
    return role


def _reset_caches():
    cache.clear()
    caches['throttle_login'].clear()


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        _reset_caches()
        set_current_user(None)  # no heredar el usuario de auditoría de otra prueba
        self.org = Organization.objects.create(name='Clinica SV', timezone='UTC')
        self.admin = User.objects.create_user(
            username='sv_admin', email='sv_admin@example.com', password=OLD_PASSWORD,
            organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=_seed_admin_role(self.org))
        self.vet = User.objects.create_user(
            username='sv_vet', email='sv_vet@example.com', password=OLD_PASSWORD,
            organization=self.org, role='VET',
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    # -- helpers ---------------------------------------------------------
    def login(self, identifier='sv_vet', password=OLD_PASSWORD):
        res = APIClient().post(
            LOGIN_URL, {'username': identifier, 'password': password}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        return res.data['access'], res.data['refresh']

    @staticmethod
    def probe(access):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return client.get(ME_URL)

    @staticmethod
    def refresh(refresh):
        return APIClient().post(REFRESH_URL, {'refresh': refresh}, format='json')

    def assertRevoked(self, response):
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.data)
        self.assertEqual(response.data['code'], 'session_revoked')

    def change_password_with(self, access, current=OLD_PASSWORD, new=NEW_PASSWORD):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return client.post(
            CHANGE_URL,
            {'current_password': current, 'new_password': new, 'confirm_password': new},
            format='json',
        )


class EmissionTests(_Fixtures):
    def test_login_by_username_and_by_email_stamps_current_version(self):
        for identifier in ('sv_vet', 'sv_vet@example.com'):
            access, refresh = self.login(identifier)
            self.assertEqual(AccessToken(access)[SESSION_VERSION_CLAIM], 0)
            self.assertEqual(RefreshToken(refresh)[SESSION_VERSION_CLAIM], 0)

        with transaction.atomic():
            bump_session_version(self.vet)
        access, refresh = self.login()
        self.assertEqual(AccessToken(access)[SESSION_VERSION_CLAIM], 1)
        self.assertEqual(RefreshToken(refresh)[SESSION_VERSION_CLAIM], 1)

    def test_rotation_keeps_the_claim(self):
        with transaction.atomic():
            bump_session_version(self.vet)
        _, refresh = self.login()
        res = self.refresh(refresh)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(RefreshToken(res.data['refresh'])[SESSION_VERSION_CLAIM], 1)
        self.assertEqual(AccessToken(res.data['access'])[SESSION_VERSION_CLAIM], 1)
        self.assertEqual(self.probe(res.data['access']).status_code, status.HTTP_200_OK)

    def test_change_password_returns_a_pair_with_the_new_version(self):
        access, _ = self.login()
        other_access, _ = self.login()  # otra sesión de la misma persona

        res = self.change_password_with(access)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(AccessToken(res.data['access'])[SESSION_VERSION_CLAIM], 1)
        self.assertEqual(self.probe(res.data['access']).status_code, status.HTTP_200_OK)
        self.assertEqual(self.refresh(res.data['refresh']).status_code, status.HTTP_200_OK)

        self.assertRevoked(self.probe(access))
        self.assertRevoked(self.probe(other_access))

    def test_stale_authorization_header_does_not_block_login(self):
        access, _ = self.login()
        with transaction.atomic():
            bump_session_version(self.vet)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = client.post(
            LOGIN_URL, {'username': 'sv_vet', 'password': OLD_PASSWORD}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)


class CompatibilityTests(_Fixtures):
    def test_token_without_claim_is_version_zero(self):
        refresh = RefreshToken.for_user(self.vet)  # como los vigentes al desplegar
        self.assertNotIn(SESSION_VERSION_CLAIM, refresh.payload)
        access = str(refresh.access_token)
        self.assertEqual(self.probe(access).status_code, status.HTTP_200_OK)

        with transaction.atomic():
            bump_session_version(self.vet)
        self.assertRevoked(self.probe(access))
        self.assertRevoked(self.refresh(str(refresh)))

    def test_malformed_claim_is_rejected(self):
        for bad in ('0', -1, True, 1.0, None):
            with self.subTest(sv=bad):
                token = AccessToken.for_user(self.vet)
                token[SESSION_VERSION_CLAIM] = bad
                self.assertRevoked(self.probe(str(token)))


class EveryBumpPathRevokesTests(_Fixtures):
    def _issued_before(self):
        access, refresh = self.login()
        return access, refresh, OutstandingToken.objects.count()

    def _assert_refresh_revoked_without_rotation(self, refresh, outstanding_before):
        # Estas vías también revocan el OutstandingToken, así que simplejwt lo
        # rechaza (`token_not_valid`) antes de llegar a la versión. Lo que importa
        # es el 401 sin rotar; el caso sin revocación lo cubre CompatibilityTests.
        res = self.refresh(refresh)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.data)
        self.assertEqual(OutstandingToken.objects.count(), outstanding_before)

    def test_clinic_reset(self):
        access, refresh, count = self._issued_before()
        res = self.admin_client.post(f'/api/staff/{self.vet.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertRevoked(self.probe(access))
        self._assert_refresh_revoked_without_rotation(refresh, count)

    def test_platform_reset(self):
        operator = User.objects.create_superuser(
            username='sv_ops', email='sv_ops@example.com', password=OLD_PASSWORD,
            role='ADMIN_SAAS', organization=None,
        )
        access, refresh, count = self._issued_before()
        client = APIClient()
        client.force_authenticate(user=operator)
        res = client.post(f'/api/platform/staff/{self.vet.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertRevoked(self.probe(access))
        self._assert_refresh_revoked_without_rotation(refresh, count)

    def test_change_password(self):
        access, refresh, _ = self._issued_before()
        other_access, other_refresh, _ = self._issued_before()
        res = self.change_password_with(access)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        count = OutstandingToken.objects.count()
        self.assertRevoked(self.probe(other_access))
        self._assert_refresh_revoked_without_rotation(other_refresh, count)

    def test_deactivate(self):
        access, refresh, count = self._issued_before()
        res = self.admin_client.delete(f'/api/staff/{self.vet.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.session_version, 1)
        # La cuenta inactiva conserva su propio rechazo (no `session_revoked`).
        res = self.probe(access)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(res.data.get('code'), 'session_revoked')
        self._assert_refresh_revoked_without_rotation(refresh, count)

        # Si alguien la reactiva fuera de la API, el token viejo sigue muerto.
        User.objects.filter(pk=self.vet.pk).update(is_active=True)
        self.assertRevoked(self.probe(access))

    def test_blocking_scenario_with_reset(self):
        """Login (T) → restablecer → login con la temporal → cambiar → T muerto."""
        token_t, _ = self.login()
        res = self.admin_client.post(f'/api/staff/{self.vet.public_id}/reset-password/')
        temp = res.data['temp_password']
        self.assertRevoked(self.probe(token_t))

        temp_access, _ = self.login(password=temp)
        res = self.change_password_with(temp_access, current=temp)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)

        self.assertRevoked(self.probe(token_t))
        self.assertEqual(self.probe(res.data['access']).status_code, status.HTTP_200_OK)


class AtomicityTests(_Fixtures):
    def test_failure_after_bump_rolls_everything_back(self):
        access, _ = self.login()
        with mock.patch('apps.users.services.logger') as log:
            log.info.side_effect = RuntimeError('fallo forzado después del incremento')
            with self.assertRaises(RuntimeError):
                reset_password_for_staff(admin=self.admin, target_user=self.vet)

        self.vet.refresh_from_db()
        self.assertEqual(self.vet.session_version, 0)
        self.assertTrue(self.vet.check_password(OLD_PASSWORD))
        self.assertFalse(self.vet.password_must_change)
        self.assertEqual(self.probe(access).status_code, status.HTTP_200_OK)


class MonotonicityTests(_Fixtures):
    def test_full_save_of_a_stale_instance_does_not_lower_the_version(self):
        stale = User.objects.get(pk=self.vet.pk)
        with transaction.atomic():
            bump_session_version(self.vet)
        stale.first_name = 'Nuevo'
        stale.save()

        fresh = User.objects.get(pk=self.vet.pk)
        self.assertEqual(fresh.session_version, 1)
        self.assertEqual(fresh.first_name, 'Nuevo')

    def test_full_save_with_deferred_fields_writes_only_loaded_fields(self):
        partial = User.objects.only('pk', 'first_name').get(pk=self.vet.pk)
        User.objects.filter(pk=self.vet.pk).update(last_name='Intacto')
        partial.first_name = 'Solo'
        with self.assertNumQueries(1):
            partial.save()
        fresh = User.objects.get(pk=self.vet.pk)
        self.assertEqual((fresh.first_name, fresh.last_name), ('Solo', 'Intacto'))

    def test_update_fields_with_session_version_is_rejected(self):
        with self.assertRaises(ValueError):
            self.vet.save(update_fields=['session_version'])

    def test_django_admin_cannot_lower_the_version(self):
        model_admin = django_admin.site._registry[User]
        request = RequestFactory().post('/')
        request.user = User.objects.create_superuser(
            username='sv_root', email='sv_root@example.com', password=OLD_PASSWORD,
        )
        form_class = model_admin.get_form(request, self.vet)
        self.assertNotIn('session_version', form_class.base_fields)

        stale = User.objects.get(pk=self.vet.pk)
        with transaction.atomic():
            bump_session_version(self.vet)
        model_admin.save_model(request, stale, form=None, change=True)
        self.assertEqual(User.objects.get(pk=self.vet.pk).session_version, 1)

    def test_rbac_receiver_still_runs_on_create_and_not_on_full_save(self):
        Role.objects.get_or_create(
            name='ASSISTANT', organization=self.org, defaults={'is_system_role': True},
        )
        user = User.objects.create_user(
            username='sv_asst', password=OLD_PASSWORD, organization=self.org, role='ASSISTANT',
        )
        self.assertEqual(UserRole.objects.filter(user=user).count(), 1)
        UserRole.objects.filter(user=user).delete()
        user.first_name = 'Otra'
        user.save()
        self.assertEqual(UserRole.objects.filter(user=user).count(), 0)


class ConcurrentBumpTests(TransactionTestCase):
    def setUp(self):
        set_current_user(None)  # no heredar el usuario de auditoría de otra prueba
        org = Organization.objects.create(name='Clinica SV concurrente', timezone='UTC')
        self.user = User.objects.create(
            username='sv_conc', organization=org, role='VET',
        )

    def test_two_simultaneous_bumps_both_count(self):
        barrier = threading.Barrier(2)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    bump_session_version(User.objects.get(pk=self.user.pk))
            except Exception as exc:  # pragma: no cover - se reporta abajo
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.user.refresh_from_db()
        self.assertEqual(self.user.session_version, 2)


class AuthenticationContractTests(_Fixtures):
    def _authenticate(self, token):
        request = RequestFactory().get(ME_URL, HTTP_AUTHORIZATION=f'Bearer {token}')
        return TenantJWTAuthentication().authenticate(request)

    def test_comparison_adds_no_queries(self):
        access, _ = self.login()
        # simplejwt carga al usuario y TenantJWTAuthentication lo relee con su
        # organización: las mismas dos consultas que antes de p65.
        with self.assertNumQueries(2):
            user, _ = self._authenticate(access)
        self.assertEqual(user.pk, self.vet.pk)

    def test_inactive_organization_keeps_its_own_rejection(self):
        access, _ = self.login()
        with transaction.atomic():
            bump_session_version(self.vet)
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        res = self.probe(access)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(res.data.get('code'), 'session_revoked')

    def test_revocation_is_logged_without_the_token(self):
        access, _ = self.login()
        with transaction.atomic():
            bump_session_version(self.vet)
        with self.assertLogs('apps.core.authentication', level='INFO') as logs:
            self.assertRevoked(self.probe(access))
        record = next(r for r in logs.records if r.getMessage() == 'AUTH_SESSION_REVOKED')
        self.assertEqual(record.user_id, self.vet.pk)
        self.assertEqual(record.token_session_version, 0)
        self.assertEqual(record.current_session_version, 1)
        for value in record.__dict__.values():
            self.assertNotIn(access, str(value))

    def test_logout_does_not_check_the_version(self):
        _, refresh = self.login()
        with transaction.atomic():
            bump_session_version(self.vet)  # sin revocar el refresh
        res = APIClient().post(LOGOUT_URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)


class ServiceAccountTests(_Fixtures):
    def setUp(self):
        super().setUp()
        self.agent, _ = ensure_agent_user(self.org)

    def test_agent_tokens_keep_authenticating(self):
        token = mint_agent_token(self.agent)
        self.assertNotIn(SESSION_VERSION_CLAIM, AccessToken(token).payload)
        request = RequestFactory().get(ME_URL, HTTP_AUTHORIZATION=f'Bearer {token}')
        user, _ = TenantJWTAuthentication().authenticate(request)
        self.assertEqual(user.pk, self.agent.pk)

    def test_platform_reset_refuses_service_accounts_in_view_and_service(self):
        operator = User.objects.create_superuser(
            username='sv_ops2', email='sv_ops2@example.com', password=OLD_PASSWORD,
            role='ADMIN_SAAS', organization=None,
        )
        client = APIClient()
        client.force_authenticate(user=operator)
        res = client.post(f'/api/platform/staff/{self.agent.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        with self.assertRaises(Http404):
            platform_reset_password(actor=operator, target_user=self.agent)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.session_version, 0)
        self.assertFalse(self.agent.password_must_change)

    def test_human_with_agent_role_is_versioned_as_a_person(self):
        human = User.objects.create_user(
            username='sv_fake_agent', password=OLD_PASSWORD, organization=self.org, role='AGENT',
        )
        with transaction.atomic():
            self.assertEqual(bump_session_version(human), 1)

    def test_agent_cannot_change_its_password(self):
        request = RequestFactory().post(CHANGE_URL)
        request.session = mock.MagicMock()
        with self.assertRaises(ValidationError):
            change_password(
                actor=self.agent, request=request,
                current_password='cualquiera', new_password=NEW_PASSWORD,
            )
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.session_version, 0)

    def test_ensure_agent_user_does_not_touch_the_version(self):
        User.objects.filter(pk=self.agent.pk).update(is_active=False, password_must_change=True)
        agent, state = ensure_agent_user(self.org)
        self.assertEqual(state, 'repaired')
        self.assertEqual(agent.session_version, 0)

    def test_bump_rejects_service_accounts(self):
        with self.assertRaises(ValueError):
            bump_session_version(self.agent)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.session_version, 0)
