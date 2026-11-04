"""H-12: cerrar sesión revoca el refresh en el servidor.

El access token sigue siendo válido hasta expirar. Es una limitación conocida del
JWT sin estado, no un defecto de este endpoint; un test la fija para que nadie la
confunda con una revocación total.
"""
from django.contrib.auth import get_user_model
from django.core.cache import caches
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization

LOGOUT = '/api/token/logout/'
REFRESH = '/api/token/refresh/'
ME = '/api/me/'


class TokenLogoutTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica', timezone='UTC')
        cls.user = get_user_model().objects.create_user(
            username='ana', password='x', organization=cls.org, role='ADMIN')

    def setUp(self):
        caches['default'].clear()
        caches['throttle_login'].clear()

    def test_revoked_refresh_can_no_longer_be_used(self):
        refresh = RefreshToken.for_user(self.user)
        self.assertEqual(self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json').status_code, 200)
        response = self.client.post(REFRESH, {'refresh': str(refresh)}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_other_sessions_of_the_same_user_stay_valid(self):
        here, elsewhere = RefreshToken.for_user(self.user), RefreshToken.for_user(self.user)
        self.client.post(LOGOUT, {'refresh': str(here)}, format='json')
        response = self.client.post(REFRESH, {'refresh': str(elsewhere)}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_access_token_is_rejected_as_the_wrong_type(self):
        access = RefreshToken.for_user(self.user).access_token
        response = self.client.post(LOGOUT, {'refresh': str(access)}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_garbage_and_missing_tokens_are_rejected(self):
        self.assertEqual(self.client.post(LOGOUT, {'refresh': 'x'}, format='json').status_code, 401)
        self.assertEqual(self.client.post(LOGOUT, {}, format='json').status_code, 400)

    def test_works_without_any_access_token(self):
        """El access pudo expirar: el endpoint no puede depender de él."""
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials()
        self.assertEqual(self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json').status_code, 200)

    def test_a_token_rotated_by_an_in_flight_refresh_is_harmless(self):
        """Carrera refresh/logout: el viejo ya está revocado y el nuevo nunca se guardó."""
        refresh = RefreshToken.for_user(self.user)
        self.assertEqual(self.client.post(REFRESH, {'refresh': str(refresh)}, format='json').status_code, 200)
        self.assertEqual(self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json').status_code, 401)

    def test_logging_out_twice_does_not_error_on_the_server(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json')
        self.assertEqual(self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json').status_code, 401)

    def test_access_token_remains_valid_until_it_expires(self):
        refresh = RefreshToken.for_user(self.user)
        access = str(refresh.access_token)
        self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertNotEqual(self.client.get(ME).status_code, 401)

    def test_response_is_not_cacheable(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json')
        self.assertIn('no-store', response['Cache-Control'])

    def test_reachable_with_a_pending_password_change(self):
        self.user.password_must_change = True
        self.user.save(update_fields=['password_must_change'])
        refresh = RefreshToken.for_user(self.user)
        self.assertEqual(self.client.post(LOGOUT, {'refresh': str(refresh)}, format='json').status_code, 200)

    def test_throttled_in_its_own_bucket(self):
        from config.urls import PublicTokenLogoutView
        from apps.core.throttling import TokenLogoutThrottle
        self.assertEqual(PublicTokenLogoutView.throttle_classes, [TokenLogoutThrottle])
        self.assertNotEqual(TokenLogoutThrottle.scope, 'login')
        self.assertIn('token_logout', api_settings.DEFAULT_THROTTLE_RATES)

    def test_excess_requests_receive_429(self):
        from unittest import mock
        from apps.core.throttling import TokenLogoutThrottle
        with mock.patch.object(TokenLogoutThrottle, 'THROTTLE_RATES', {'token_logout': '2/hour'}):
            codes = [self.client.post(LOGOUT, {'refresh': 'x'}, format='json').status_code
                     for _ in range(3)]
        self.assertEqual(codes, [401, 401, 429])
