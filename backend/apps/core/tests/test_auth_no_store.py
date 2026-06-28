"""
test_auth_no_store.py — H-09 (auth audit).

Los endpoints de autenticación devuelven material de credencial (access /
refresh tokens). Deben marcar ``Cache-Control: no-store`` para que un proxy
intermediario mal configurado nunca persista esas respuestas.

Cubre login, refresh y cambio de contraseña — incluyendo rutas de error
(credenciales inválidas), porque el header se aplica vía
``finalize_response`` (``NoStoreResponseMixin``) y debe cubrir todo retorno.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from rest_framework_simplejwt.tokens import RefreshToken

from apps.organizations.models import Organization

User = get_user_model()

LOGIN_URL = '/api/token/'
REFRESH_URL = '/api/token/refresh/'
CHANGE_URL = '/api/users/change-password/'


class AuthNoStoreHeaderTests(APITestCase):
    def setUp(self):
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name="NoStore Org", timezone="UTC")
        self.user = User.objects.create_user(
            username="nostore_user",
            password="StrongPass1234!",
            organization=self.org,
            role="VET",
        )

    def _assert_no_store(self, response):
        self.assertEqual(response.get('Cache-Control'), 'no-store', response.content)

    def test_login_success_sets_no_store(self):
        client = APIClient()
        res = client.post(
            LOGIN_URL,
            {'username': 'nostore_user', 'password': 'StrongPass1234!'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self._assert_no_store(res)

    def test_login_failure_sets_no_store(self):
        client = APIClient()
        res = client.post(
            LOGIN_URL,
            {'username': 'nostore_user', 'password': 'wrong'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self._assert_no_store(res)

    def test_refresh_sets_no_store(self):
        refresh = str(RefreshToken.for_user(self.user))
        client = APIClient()
        res = client.post(REFRESH_URL, {'refresh': refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self._assert_no_store(res)

    def test_change_password_sets_no_store(self):
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.post(
            CHANGE_URL,
            {
                'current_password': 'StrongPass1234!',
                'new_password': 'BrandNewPass1234!',
                'confirm_password': 'BrandNewPass1234!',
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self._assert_no_store(res)
