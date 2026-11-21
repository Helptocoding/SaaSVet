"""
Tests for POST /api/platform/staff/<public_id>/reset-password/ (ADR p45).

What we are protecting:
  - Authorization matrix — only ADMIN_SAAS can call this endpoint.
    Any other role (ADMIN, VET, ASSISTANT) must be rejected.
  - Cross-tenant capability — ADMIN_SAAS can reset users from any org.
  - Invariants — cannot reset another ADMIN_SAAS, cannot self-reset.
  - Lifecycle — same post-conditions as the clinic-admin reset:
      temp password set, must_change=True, all tokens blacklisted.
  - Audit — PLATFORM_PASSWORD_RESET_ISSUED logged, temp_password never logged.
  - Throttle — blocks after budget exceeded.
"""
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

URL = '/api/platform/staff/{pk}/reset-password/'
LOGIN_URL = '/api/token/'


def _reset_url(public_id):
    return URL.format(pk=public_id)


class _BaseFixtures(TestCase):
    def setUp(self):
        cache.clear()
        # Login throttle usa la cache `throttle_login` (no `default`); limpiarla
        # aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()
        self.client = APIClient()

        # Org A with ADMIN + VET + ASSISTANT
        self.org_a = Organization.objects.create(name='Clinica A')
        self.admin_a = User.objects.create_user(
            username='admin_a', email='admin_a@a.com', password='AdminPass1234!',
            role='ADMIN', organization=self.org_a,
        )
        self.vet_a = User.objects.create_user(
            username='vet_a', email='vet_a@a.com', password='VetPass1234!',
            role='VET', organization=self.org_a,
        )
        self.asst_a = User.objects.create_user(
            username='asst_a', email='asst_a@a.com', password='AsstPass1234!',
            role='ASSISTANT', organization=self.org_a,
        )

        # Org B — separate tenant
        self.org_b = Organization.objects.create(name='Clinica B')
        self.admin_b = User.objects.create_user(
            username='admin_b', email='admin_b@b.com', password='AdminPass1234!',
            role='ADMIN', organization=self.org_b,
        )

        # ADMIN_SAAS — platform operator
        self.platform_org = Organization.objects.create(name='VetCare Platform')
        self.admin_saas = User.objects.create_superuser(
            username='admin_saas', email='ops@vetcare.internal',
            password='PlatformPass1234!', role='ADMIN_SAAS',
            organization=self.platform_org,
        )

        # Second ADMIN_SAAS (for the peer-reset blocked test)
        self.admin_saas_2 = User.objects.create_superuser(
            username='admin_saas_2', email='ops2@vetcare.internal',
            password='PlatformPass5678!', role='ADMIN_SAAS',
            organization=self.platform_org,
        )


class PlatformResetAuthTests(_BaseFixtures):
    """Permission matrix."""

    def test_admin_saas_can_reset_vet_own_org_201(self):
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertIn('temp_password', res.data)

    def test_admin_saas_can_reset_admin_other_org_201(self):
        """Cross-tenant reset — the key capability of ADR p45."""
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.admin_b.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

    def test_admin_saas_cannot_reset_self_404(self):
        """Self is excluded from queryset (all ADMIN_SAAS excluded) → 404."""
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.admin_saas.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_saas_cannot_reset_peer_admin_saas_404(self):
        """ADMIN_SAAS is excluded from the queryset (exclude role='ADMIN_SAAS')."""
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.admin_saas_2.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_clinic_admin_rejected_403(self):
        self.client.force_authenticate(user=self.admin_a)
        res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_vet_rejected_403(self):
        self.client.force_authenticate(user=self.vet_a)
        res = self.client.post(_reset_url(self.asst_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_assistant_rejected_403(self):
        self.client.force_authenticate(user=self.asst_a)
        res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_401(self):
        res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class PlatformResetBehaviorTests(_BaseFixtures):
    """State mutations + temp password mechanics."""

    def _reset(self, target=None):
        self.client.force_authenticate(user=self.admin_saas)
        target = target or self.vet_a
        return self.client.post(_reset_url(target.public_id), format='json')

    def test_target_password_changed_to_temp(self):
        res = self._reset()
        temp = res.data['temp_password']
        self.vet_a.refresh_from_db()
        self.assertTrue(self.vet_a.check_password(temp))
        self.assertFalse(self.vet_a.check_password('VetPass1234!'))

    def test_password_must_change_flag_set_true(self):
        self._reset()
        self.vet_a.refresh_from_db()
        self.assertTrue(self.vet_a.password_must_change)

    def test_password_temp_issued_at_set(self):
        self._reset()
        self.vet_a.refresh_from_db()
        self.assertIsNotNone(self.vet_a.password_temp_issued_at)
        delta = timezone.now() - self.vet_a.password_temp_issued_at
        self.assertLess(delta.total_seconds(), 5)

    def test_temp_password_random_url_safe_min_22_chars(self):
        import re
        res = self._reset()
        temp = res.data['temp_password']
        self.assertGreaterEqual(len(temp), 22)
        self.assertRegex(temp, r'^[A-Za-z0-9_\-]+$')

    def test_temp_passwords_unique_per_call(self):
        first = self._reset().data['temp_password']
        second = self._reset().data['temp_password']
        self.assertNotEqual(first, second)

    def test_existing_tokens_blacklisted(self):
        old_refresh = str(RefreshToken.for_user(self.vet_a))
        self._reset()
        public = APIClient()
        res = public.post('/api/token/refresh/', {'refresh': old_refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_response_includes_expires_in_seconds(self):
        res = self._reset()
        self.assertEqual(res.data['expires_in_seconds'], 24 * 3600)
        self.assertTrue(res.data['must_change_on_first_login'])

    def test_response_is_no_store(self):
        # Lleva una contraseña temporal: ninguna caché intermedia debe guardarla
        # (plan Equipo, D11; igual que el restablecimiento de clínica).
        res = self._reset()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res['Cache-Control'], 'no-store')

    def test_rejections_are_no_store_too(self):
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.admin_saas.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res['Cache-Control'], 'no-store')

    def test_cross_tenant_reset_works(self):
        """ADMIN_SAAS resets ADMIN in a different org — core ADR p45 invariant."""
        res = self._reset(target=self.admin_b)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.admin_b.refresh_from_db()
        self.assertTrue(self.admin_b.password_must_change)
        self.assertTrue(self.admin_b.check_password(res.data['temp_password']))


class PlatformResetAuditTests(_BaseFixtures):
    """Audit log — temp_password must NEVER appear in any log record."""

    def test_audit_log_emitted_without_temp_password(self):
        self.client.force_authenticate(user=self.admin_saas)
        with self.assertLogs('platform.events', level='INFO') as logs:
            res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        records = [r for r in logs.records if r.msg == 'PLATFORM_PASSWORD_RESET_ISSUED']
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.actor_id, self.admin_saas.pk)
        self.assertEqual(rec.target_user_id, self.vet_a.pk)
        self.assertEqual(rec.target_role, 'VET')
        self.assertEqual(rec.target_organization_id, self.org_a.pk)
        self.assertEqual(rec.target_organization_name, 'Clinica A')

        # Scan every log attribute — temp_password must never appear.
        temp = res.data['temp_password']
        for r in logs.records:
            for attr_name in dir(r):
                if attr_name.startswith('_'):
                    continue
                value = getattr(r, attr_name, None)
                if isinstance(value, str):
                    self.assertNotIn(temp, value)

    def test_audit_log_includes_target_org_for_cross_tenant(self):
        self.client.force_authenticate(user=self.admin_saas)
        with self.assertLogs('platform.events', level='INFO') as logs:
            self.client.post(_reset_url(self.admin_b.public_id), format='json')

        records = [r for r in logs.records if r.msg == 'PLATFORM_PASSWORD_RESET_ISSUED']
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.target_organization_id, self.org_b.pk)
        self.assertEqual(rec.target_organization_name, 'Clinica B')


class PlatformResetLifecycleTests(_BaseFixtures):
    """Full lifecycle: reset → login with temp → change → done."""

    def test_target_can_login_with_temp_password(self):
        self.client.force_authenticate(user=self.admin_saas)
        res = self.client.post(_reset_url(self.vet_a.public_id), format='json')
        temp = res.data['temp_password']

        public = APIClient()
        login = public.post(LOGIN_URL, {'username': 'vet_a', 'password': temp}, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertTrue(login.data.get('must_change_password'))

    def test_old_password_no_longer_works(self):
        self.client.force_authenticate(user=self.admin_saas)
        self.client.post(_reset_url(self.vet_a.public_id), format='json')

        public = APIClient()
        login = public.post(LOGIN_URL, {'username': 'vet_a', 'password': 'VetPass1234!'}, format='json')
        self.assertEqual(login.status_code, status.HTTP_401_UNAUTHORIZED)


class PlatformResetThrottleTests(_BaseFixtures):
    """Rate-limit platform resets."""

    def test_throttle_blocks_after_budget(self):
        from unittest import mock
        from rest_framework.throttling import ScopedRateThrottle

        original_get_rate = ScopedRateThrottle.get_rate

        def fake_get_rate(self_t):
            if getattr(self_t, 'scope', None) == 'platform_password_reset':
                return '2/hour'
            return original_get_rate(self_t)

        targets = [
            User.objects.create_user(
                username=f'staff{i}', email=f'staff{i}@a.com',
                password='Pass1234!', role='ASSISTANT', organization=self.org_a,
            )
            for i in range(3)
        ]

        self.client.force_authenticate(user=self.admin_saas)
        with mock.patch.object(ScopedRateThrottle, 'get_rate', fake_get_rate):
            for i in range(2):
                res = self.client.post(_reset_url(targets[i].public_id), format='json')
                self.assertEqual(res.status_code, status.HTTP_201_CREATED, f'call #{i}: {res.data}')
            third = self.client.post(_reset_url(targets[2].public_id), format='json')
            self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
