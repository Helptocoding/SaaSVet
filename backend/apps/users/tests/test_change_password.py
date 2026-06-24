"""
Tests for ``POST /api/users/change-password/`` and its underlying service
``apps.users.services.change_password`` (ADR p20).

What we are protecting here:
  - Atomicity — a failure at any step must not leave a half-rotated
    password or orphaned blacklist rows.
  - JWT lifecycle — every refresh token the user held *before* the
    change must be blacklisted, and the freshly-minted pair must work.
    This is the single most delicate part of the flow.
  - Audit trail — logs include actor, org, IP, UA for every success
    and every failure.
  - Throttle — brute-forcing the current password must be capped.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization


User = get_user_model()


URL = '/api/users/change-password/'
LOGIN_URL = '/api/token/'
REFRESH_URL = '/api/token/refresh/'


def _payload(**overrides):
    base = {
        'current_password': 'OldPass1234!',
        'new_password': 'NewPass4321!',
        'confirm_password': 'NewPass4321!',
    }
    base.update(overrides)
    return base


class ChangePasswordValidationTests(TestCase):
    """Field-level + service-level validation paths."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        self.client.force_authenticate(user=self.user)
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def test_wrong_current_password_rejected_400(self):
        res = self.client.post(
            URL,
            _payload(current_password='WrongPass1234!'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('current_password', res.data.get('errors', {}))

    def test_weak_new_password_below_min_length_rejected(self):
        res = self.client.post(
            URL,
            _payload(new_password='Short1!', confirm_password='Short1!'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', res.data.get('errors', {}))

    def test_new_password_numeric_only_rejected(self):
        res = self.client.post(
            URL,
            _payload(new_password='12345678', confirm_password='12345678'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', res.data.get('errors', {}))

    def test_new_password_too_similar_to_first_name_rejected(self):
        """UserAttributeSimilarityValidator with default max_similarity=0.7.

        Pick a first_name long enough that a password resembling it
        clearly exceeds the threshold. Short usernames like 'vet1' do
        NOT trigger the validator because the SequenceMatcher ratio
        stays below 0.7 once the password reaches min_length=8.
        """
        self.user.first_name = 'Alejandro'
        self.user.save(update_fields=['first_name'])
        res = self.client.post(
            URL,
            _payload(
                new_password='Alejandro12',
                confirm_password='Alejandro12',
            ),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', res.data.get('errors', {}))

    def test_new_password_common_dictionary_word_rejected(self):
        res = self.client.post(
            URL,
            _payload(new_password='password1234', confirm_password='password1234'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_password_mismatch_rejected_400(self):
        res = self.client.post(
            URL,
            _payload(confirm_password='NoMatchPass1!'),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm_password', res.data.get('errors', {}))

    def test_new_equals_current_rejected_400(self):
        res = self.client.post(
            URL,
            _payload(
                new_password='OldPass1234!',
                confirm_password='OldPass1234!',
            ),
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', res.data.get('errors', {}))

    def test_unauthenticated_401(self):
        unauth = APIClient()
        res = unauth.post(URL, _payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class ChangePasswordSuccessTests(TestCase):
    """Happy path + state mutations."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def _login_get_tokens(self):
        public = APIClient()
        res = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'OldPass1234!'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        return res.data['access'], res.data['refresh']

    def test_password_changed_successfully_200(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post(URL, _payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.assertEqual(res.data['detail'], 'Contraseña actualizada.')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass4321!'))
        self.assertFalse(self.user.check_password('OldPass1234!'))

    def test_response_includes_new_access_and_refresh_pair(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post(URL, _payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertTrue(res.data['access'])
        self.assertTrue(res.data['refresh'])
        self.assertNotEqual(res.data['access'], res.data['refresh'])

    def test_new_access_token_works_in_authenticated_request(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post(URL, _payload(), format='json')
        new_access = res.data['access']

        # Fresh client without force_auth — exercise the real JWT layer.
        public = APIClient()
        public.credentials(HTTP_AUTHORIZATION=f'Bearer {new_access}')
        me = public.get('/api/me/')
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data['username'], 'vet1')

    def test_old_password_no_longer_works_for_login(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(URL, _payload(), format='json')

        public = APIClient()
        res = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'OldPass1234!'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_new_password_works_for_login(self):
        self.client.force_authenticate(user=self.user)
        self.client.post(URL, _payload(), format='json')

        public = APIClient()
        res = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'NewPass4321!'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class ChangePasswordJWTLifecycleTests(TestCase):
    """The most delicate part — refresh-token rotation + blacklist semantics."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def _real_login(self):
        public = APIClient()
        res = public.post(
            LOGIN_URL,
            {'username': 'vet1', 'password': 'OldPass1234!'},
            format='json',
        )
        return res.data['access'], res.data['refresh']

    def test_old_refresh_token_blacklisted_after_change(self):
        """The refresh token the user held BEFORE the change must be
        unable to mint new access tokens once the change completes."""
        access_v1, refresh_v1 = self._real_login()

        change_client = APIClient()
        change_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_v1}')
        res = change_client.post(URL, _payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Try to use the OLD refresh token — must fail.
        public = APIClient()
        refresh_res = public.post(
            REFRESH_URL,
            {'refresh': refresh_v1},
            format='json',
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_new_refresh_token_is_valid(self):
        access_v1, _ = self._real_login()
        change_client = APIClient()
        change_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_v1}')
        res = change_client.post(URL, _payload(), format='json')
        new_refresh = res.data['refresh']

        public = APIClient()
        refresh_res = public.post(
            REFRESH_URL,
            {'refresh': new_refresh},
            format='json',
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_res.data)

    def test_other_user_refresh_tokens_not_affected(self):
        """Multi-user isolation — changing vet1's password must NOT
        blacklist vet2's refresh tokens."""
        vet2 = User.objects.create_user(
            username='vet2',
            email='vet2@clinica.com',
            password='OtherPass1234!',
            role='VET',
            organization=self.org,
        )
        vet2_refresh = str(RefreshToken.for_user(vet2))

        self.client.force_authenticate(user=self.user)
        self.client.post(URL, _payload(), format='json')

        public = APIClient()
        refresh_res = public.post(
            REFRESH_URL,
            {'refresh': vet2_refresh},
            format='json',
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)

    def test_multiple_old_refresh_tokens_all_blacklisted(self):
        """If the user had several active sessions (different devices),
        all of their refresh tokens must be blacklisted."""
        old_refresh_strings = [str(RefreshToken.for_user(self.user)) for _ in range(3)]

        self.client.force_authenticate(user=self.user)
        self.client.post(URL, _payload(), format='json')

        public = APIClient()
        for old_refresh in old_refresh_strings:
            refresh_res = public.post(
                REFRESH_URL,
                {'refresh': old_refresh},
                format='json',
            )
            self.assertEqual(
                refresh_res.status_code,
                status.HTTP_401_UNAUTHORIZED,
                msg=f"old refresh {old_refresh[:20]}... still works",
            )

    def test_blacklist_count_in_log_matches_outstanding_snapshot(self):
        # Pre-create 2 refresh tokens so snapshot is non-empty
        RefreshToken.for_user(self.user)
        RefreshToken.for_user(self.user)
        outstanding_before = OutstandingToken.objects.filter(user=self.user).count()
        self.assertGreaterEqual(outstanding_before, 2)

        self.client.force_authenticate(user=self.user)
        with self.assertLogs('users.events', level='INFO') as logs:
            res = self.client.post(URL, _payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        records = [r for r in logs.records if r.msg == 'USER_PASSWORD_CHANGED']
        self.assertEqual(len(records), 1)
        # The log should claim it blacklisted exactly the pre-existing count.
        self.assertEqual(records[0].blacklisted_refresh_count, outstanding_before)

        # And the corresponding BlacklistedToken rows should exist.
        blacklisted_count = BlacklistedToken.objects.filter(
            token__user=self.user
        ).count()
        self.assertEqual(blacklisted_count, outstanding_before)


class ChangePasswordLoggingTests(TestCase):
    """Structured log events for SIEM / audit pipeline."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        self.client.force_authenticate(user=self.user)
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def test_success_log_carries_actor_org_ip_useragent(self):
        with self.assertLogs('users.events', level='INFO') as logs:
            res = self.client.post(
                URL,
                _payload(),
                format='json',
                HTTP_X_FORWARDED_FOR='203.0.113.42, 10.0.0.1',
                HTTP_USER_AGENT='pytest-ua/1.0',
                HTTP_X_REQUEST_ID='trace-change-001',
            )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        records = [r for r in logs.records if r.msg == 'USER_PASSWORD_CHANGED']
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.event, 'USER_PASSWORD_CHANGED')
        self.assertEqual(rec.actor_id, self.user.pk)
        self.assertEqual(rec.actor_username, 'vet1')
        self.assertEqual(rec.organization_id, self.org.pk)
        self.assertEqual(rec.client_ip, '203.0.113.42')
        self.assertEqual(rec.user_agent, 'pytest-ua/1.0')
        self.assertEqual(rec.request_id, 'trace-change-001')
        self.assertIsInstance(rec.duration_ms, int)

    def test_failed_attempt_logged_with_warning(self):
        with self.assertLogs('users.events', level='WARNING') as logs:
            res = self.client.post(
                URL,
                _payload(current_password='WrongPass1234!'),
                format='json',
                HTTP_X_FORWARDED_FOR='198.51.100.7',
            )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        fails = [r for r in logs.records if r.msg == 'USER_PASSWORD_CHANGE_FAILED']
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0].reason, 'wrong_current_password')
        self.assertEqual(fails[0].actor_id, self.user.pk)
        self.assertEqual(fails[0].client_ip, '198.51.100.7')


class ChangePasswordThrottleTests(TestCase):
    """Rate limiting — 10/hour scope ``change_password`` per user."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        self.client.force_authenticate(user=self.user)
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def test_throttle_blocks_after_budget_exceeded(self):
        from unittest import mock
        from rest_framework.throttling import ScopedRateThrottle

        # Patch the throttle scope to a small budget — keeps the test fast.
        original_get_rate = ScopedRateThrottle.get_rate

        def fake_get_rate(self):
            if getattr(self, 'scope', None) == 'change_password':
                return '2/hour'
            return original_get_rate(self)

        with mock.patch.object(ScopedRateThrottle, 'get_rate', fake_get_rate):
            # Each failed attempt with wrong current password — also counts.
            for i in range(2):
                res = self.client.post(
                    URL,
                    _payload(current_password='WrongPass1234!'),
                    format='json',
                )
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

            # 3rd call must be throttled.
            third = self.client.post(
                URL,
                _payload(current_password='WrongPass1234!'),
                format='json',
            )
            self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class ChangePasswordAtomicityTests(TestCase):
    """Rollback guarantee — a failure after partial work must revert."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Clinica X')
        self.user = User.objects.create_user(
            username='vet1',
            email='vet@clinica.com',
            password='OldPass1234!',
            role='VET',
            organization=self.org,
        )
        cache.clear()
        # Login throttle vive en la cache `throttle_login` (no en `default`);
        # limpiarla aísla el bucket 5/15min entre tests (evita 429 acumulado).
        caches['throttle_login'].clear()

    def test_password_unchanged_when_token_blacklist_step_fails(self):
        """If the blacklist write fails (DB error, etc.), the password
        must remain on its OLD value — the user's session is preserved.

        DRF's exception handler converts unexpected exceptions to a 500
        Response inside the request cycle, so the test asserts on the
        observed post-rollback state instead of on the raised exception.
        """
        from unittest import mock

        # Pre-create OutstandingToken so the blacklist loop executes.
        RefreshToken.for_user(self.user)

        self.client.force_authenticate(user=self.user)
        with mock.patch.object(
            BlacklistedToken.objects,
            'get_or_create',
            side_effect=RuntimeError('simulated blacklist failure'),
        ):
            res = self.client.post(URL, _payload(), format='json')

        # Server returned an error status — exact code depends on the
        # project's exception handler; what matters is "not 200".
        self.assertNotEqual(res.status_code, status.HTTP_200_OK)

        # Password unchanged — @transaction.atomic rolled back.
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass1234!'))
        self.assertFalse(self.user.check_password('NewPass4321!'))
