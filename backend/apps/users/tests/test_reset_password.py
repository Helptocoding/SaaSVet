"""
Tests for ``POST /api/staff/<public_id>/reset-password/`` and the
``apps.users.services.reset_password_for_staff`` service (ADR p21).

What we are protecting:
  - Authorisation matrix — only ADMIN of the SAME org can issue resets,
    never against themselves, never against ADMIN_SAAS, never
    cross-tenant.
  - Lifecycle — temp password is server-generated random, target gets
    every session revoked, ``password_must_change`` flips True with a
    24h validity window.
  - Audit — every reset emits a structured log without leaking the
    temp password itself.
  - Gate — the MustChangePasswordGate blocks normal endpoints until
    the target self-changes through ``change-password``.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization


User = get_user_model()


LOGIN_URL = '/api/token/'
REFRESH_URL = '/api/token/refresh/'
CHANGE_URL = '/api/users/change-password/'


def _reset_url(public_id):
    return f'/api/staff/{public_id}/reset-password/'


class _BaseFixtures(TestCase):
    def setUp(self):
        cache.clear()
        # El throttle de login usa la cache `throttle_login` (alias distinto del
        # `default`); cache.clear() NO lo toca → el bucket 5/15min se acumula
        # entre tests y dispara 429. Limpiarlo aquí aísla el throttle por test.
        caches['throttle_login'].clear()
        self.client = APIClient()

        self.org = Organization.objects.create(name='Clinica X')
        self.other_org = Organization.objects.create(name='Otra Clinica')

        # Roles dentro de la org bajo test
        self.admin = User.objects.create_user(
            username='clinic_admin',
            email='admin@clinica.com',
            password='AdminPass1234!',
            role='ADMIN',
            organization=self.org,
        )
        self.vet = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='VetPass1234!',
            role='VET',
            organization=self.org,
        )
        self.assistant = User.objects.create_user(
            username='asst1',
            email='asst@clinica.com',
            password='AsstPass1234!',
            role='ASSISTANT',
            organization=self.org,
        )

        # ADMIN de OTRA org (para tests cross-tenant)
        self.other_admin = User.objects.create_user(
            username='other_admin',
            email='other@clinica.com',
            password='OtherPass1234!',
            role='ADMIN',
            organization=self.other_org,
        )

        # ADMIN_SAAS (target prohibido)
        platform_org = Organization.objects.create(name='Vet Care Internal')
        self.admin_saas = User.objects.create_superuser(
            username='admin_saas',
            email='ops@vetcare.internal',
            password='SuperPass1234!',
            role='ADMIN_SAAS',
            organization=platform_org,
        )


class ResetPasswordAuthTests(_BaseFixtures):
    """Permission matrix — only ADMIN of same org, never self, never SAAS."""

    def test_admin_can_reset_staff_of_own_org_201(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertIn('temp_password', res.data)

    def test_admin_cannot_reset_self_403(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.admin.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_reset_admin_saas(self):
        # ADMIN_SAAS lives in another org — endpoint should treat it as
        # not found (404-as-403 convention).
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.admin_saas.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_cannot_reset_user_from_other_org_404(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.other_admin.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_vet_cannot_reset_403(self):
        self.client.force_authenticate(user=self.vet)
        res = self.client.post(_reset_url(self.assistant.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_assistant_cannot_reset_403(self):
        self.client.force_authenticate(user=self.assistant)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_401(self):
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class ResetPasswordServiceBehaviorTests(_BaseFixtures):
    """State mutations + temp password generation."""

    def _reset(self):
        self.client.force_authenticate(user=self.admin)
        return self.client.post(_reset_url(self.vet.public_id), format='json')

    def test_target_password_changed_to_temp(self):
        res = self._reset()
        temp = res.data['temp_password']
        self.vet.refresh_from_db()
        self.assertTrue(self.vet.check_password(temp))
        self.assertFalse(self.vet.check_password('VetPass1234!'))

    def test_password_must_change_flag_set_true(self):
        self._reset()
        self.vet.refresh_from_db()
        self.assertTrue(self.vet.password_must_change)

    def test_password_temp_issued_at_set(self):
        self._reset()
        self.vet.refresh_from_db()
        self.assertIsNotNone(self.vet.password_temp_issued_at)
        # within a few seconds of now
        delta = timezone.now() - self.vet.password_temp_issued_at
        self.assertLess(delta.total_seconds(), 5)

    def test_temp_password_is_random_url_safe_min_22_chars(self):
        # secrets.token_urlsafe(16) → 22-char base64-urlsafe string.
        res = self._reset()
        temp = res.data['temp_password']
        self.assertGreaterEqual(len(temp), 22)
        # base64-urlsafe alphabet
        import re
        self.assertRegex(temp, r'^[A-Za-z0-9_\-]+$')

    def test_temp_passwords_are_unique_per_call(self):
        # Two consecutive resets must produce two different temps.
        first = self._reset().data['temp_password']
        second = self._reset().data['temp_password']
        self.assertNotEqual(first, second)

    def test_target_existing_refresh_tokens_blacklisted(self):
        # Issue a refresh token for the target first.
        old_refresh = str(RefreshToken.for_user(self.vet))
        self._reset()
        # That refresh must no longer be valid.
        public = APIClient()
        refresh_res = public.post(
            REFRESH_URL,
            {'refresh': old_refresh},
            format='json',
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_response_includes_expires_in_seconds(self):
        res = self._reset()
        self.assertEqual(res.data['expires_in_seconds'], 24 * 3600)
        self.assertTrue(res.data['must_change_on_first_login'])

    def test_audit_log_emitted_without_temp_password(self):
        self.client.force_authenticate(user=self.admin)
        with self.assertLogs('users.events', level='INFO') as logs:
            res = self.client.post(_reset_url(self.vet.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        records = [r for r in logs.records if r.msg == 'ADMIN_PASSWORD_RESET_ISSUED']
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.actor_id, self.admin.pk)
        self.assertEqual(rec.target_user_id, self.vet.pk)
        self.assertEqual(rec.target_role, 'VET')
        self.assertEqual(rec.organization_id, self.org.pk)

        # The temp password must NEVER appear in any log record.
        temp = res.data['temp_password']
        for r in logs.records:
            for attr_name in dir(r):
                if attr_name.startswith('_'):
                    continue
                value = getattr(r, attr_name, None)
                if isinstance(value, str):
                    self.assertNotIn(temp, value)


class ResetPasswordLifecycleTests(_BaseFixtures):
    """The temp-password full lifecycle: reset → login → change → done."""

    def test_target_can_login_with_temp_password(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        temp = res.data['temp_password']

        public = APIClient()
        login = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': temp},
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertTrue(login.data.get('must_change_password'))

    def test_old_password_no_longer_works(self):
        self.client.force_authenticate(user=self.admin)
        self.client.post(_reset_url(self.vet.public_id), format='json')

        public = APIClient()
        login = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'VetPass1234!'},
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_temp_password_expired_24h_login_rejected_403(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        temp = res.data['temp_password']

        # Backdate the temp by 25h.
        self.vet.refresh_from_db()
        self.vet.password_temp_issued_at = timezone.now() - timedelta(hours=25)
        self.vet.save(update_fields=['password_temp_issued_at'])

        public = APIClient()
        login = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': temp},
            format='json',
        )
        self.assertEqual(login.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(login.data.get('code'), 'temp_password_expired')

    def test_change_password_with_temp_clears_must_change_flag(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        temp = res.data['temp_password']

        # Vet logs in with temp and changes their password.
        public = APIClient()
        login = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': temp},
            format='json',
        )
        access = login.data['access']

        change_client = APIClient()
        change_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        change_res = change_client.post(
            CHANGE_URL,
            {
                'current_password': temp,
                'new_password': 'BrandNewPass1234!',
                'confirm_password': 'BrandNewPass1234!',
            },
            format='json',
        )
        self.assertEqual(change_res.status_code, status.HTTP_200_OK, change_res.data)

        self.vet.refresh_from_db()
        self.assertFalse(self.vet.password_must_change)
        self.assertIsNone(self.vet.password_temp_issued_at)

    def test_new_password_works_for_subsequent_login(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        temp = res.data['temp_password']

        public = APIClient()
        login = public.post(LOGIN_URL, {'username': 'vet1', 'password': temp}, format='json')
        access = login.data['access']
        change_client = APIClient()
        change_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        change_client.post(
            CHANGE_URL,
            {
                'current_password': temp,
                'new_password': 'BrandNewPass1234!',
                'confirm_password': 'BrandNewPass1234!',
            },
            format='json',
        )

        login2 = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'BrandNewPass1234!'},
            format='json',
        )
        self.assertEqual(login2.status_code, status.HTTP_200_OK)
        self.assertFalse(login2.data.get('must_change_password', False))


class MustChangePasswordGateTests(_BaseFixtures):
    """The global gate must block normal endpoints while flag is on."""

    def _login_with_temp(self):
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(_reset_url(self.vet.public_id), format='json')
        temp = res.data['temp_password']
        public = APIClient()
        login = public.post(LOGIN_URL, {'username': 'vet1', 'password': temp}, format='json')
        return public, login.data['access'], temp

    def test_gate_blocks_normal_endpoint_403(self):
        public, access, _ = self._login_with_temp()
        public.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = public.get('/api/staff/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_gate_allows_change_password_endpoint(self):
        public, access, temp = self._login_with_temp()
        public.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = public.post(
            CHANGE_URL,
            {
                'current_password': temp,
                'new_password': 'BrandNewPass1234!',
                'confirm_password': 'BrandNewPass1234!',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_gate_allows_me_endpoint(self):
        public, access, _ = self._login_with_temp()
        public.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = public.get('/api/me/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data.get('must_change_password'))

    def test_gate_does_not_affect_users_without_flag(self):
        # An admin with a normal session must NOT be blocked.
        self.client.force_authenticate(user=self.admin)
        res = self.client.get('/api/staff/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class ResetPasswordThrottleTests(_BaseFixtures):
    """Rate-limit admin resets — insider abuse mitigation."""

    def test_throttle_blocks_after_5_per_hour(self):
        from unittest import mock
        from rest_framework.throttling import ScopedRateThrottle

        original_get_rate = ScopedRateThrottle.get_rate

        def fake_get_rate(self):
            if getattr(self, 'scope', None) == 'staff_password_reset':
                return '2/hour'
            return original_get_rate(self)

        # Create 3 targets to reset.
        targets = [
            User.objects.create_user(
                username=f'staff{i}',
                email=f'staff{i}@clinica.com',
                password='Pass1234!',
                role='ASSISTANT',
                organization=self.org,
            )
            for i in range(3)
        ]

        self.client.force_authenticate(user=self.admin)
        with mock.patch.object(ScopedRateThrottle, 'get_rate', fake_get_rate):
            for i in range(2):
                res = self.client.post(_reset_url(targets[i].public_id), format='json')
                self.assertEqual(
                    res.status_code,
                    status.HTTP_201_CREATED,
                    msg=f"call #{i} failed: {res.data}",
                )

            third = self.client.post(_reset_url(targets[2].public_id), format='json')
            self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
