from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.test import SimpleTestCase
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.core.throttling import (
    ExtendedRateThrottle,
    LoginRateThrottle,
    LoginUserRateThrottle,
)


class _DummyThrottle(ExtendedRateThrottle):
    scope = "dummy"
    rate = "1/min"

    def get_cache_key(self, request, view):
        return "dummy"


class ExtendedRateThrottleTests(SimpleTestCase):
    def setUp(self):
        self.throttle = _DummyThrottle()

    def test_parse_rate_supports_drf_native_format(self):
        num, duration = self.throttle.parse_rate("5/min")
        self.assertEqual(num, 5)
        self.assertEqual(duration, 60)

    def test_parse_rate_supports_extended_window_minutes(self):
        num, duration = self.throttle.parse_rate("5/15min")
        self.assertEqual(num, 5)
        self.assertEqual(duration, 900)

    def test_parse_rate_supports_extended_window_hours_short_unit(self):
        num, duration = self.throttle.parse_rate("10/2h")
        self.assertEqual(num, 10)
        self.assertEqual(duration, 7200)

    def test_parse_rate_raises_for_invalid_extended_unit(self):
        with self.assertRaises(ValueError):
            self.throttle.parse_rate("5/10weeks")


class LoginThrottleCacheWiringTests(SimpleTestCase):
    """P1-1 / ADR p41: the login throttles must use the `throttle_login` cache
    (fail-closed) so the brute-force counter is shared across gunicorn workers,
    not the per-worker LocMem of the `default` alias. No DB needed."""

    def setUp(self):
        caches['throttle_login'].clear()
        caches['default'].clear()
        self.factory = APIRequestFactory()

    def _anon_post(self, username='attacker'):
        request = self.factory.post('/api/token/', {'username': username})
        request.user = AnonymousUser()  # no auth middleware in a unit test
        return request

    def test_login_throttles_resolve_to_throttle_login_alias(self):
        self.assertIs(LoginRateThrottle().cache, caches['throttle_login'])
        self.assertIs(LoginUserRateThrottle().cache, caches['throttle_login'])

    def test_login_throttle_blocks_after_budget(self):
        # login rate = 5/15min → 5 allowed, 6th blocked. The counter is shared
        # via the throttle_login cache (the cross-worker fix this PR ships).
        request = self._anon_post()
        allowed = [LoginRateThrottle().allow_request(request, None) for _ in range(5)]
        self.assertTrue(all(allowed))
        self.assertFalse(LoginRateThrottle().allow_request(request, None))

    def test_login_counter_not_reset_by_clearing_default_cache(self):
        # Regression guard: clearing only `default` must NOT free the login
        # budget — proving the counter lives in throttle_login, not default.
        request = self._anon_post()
        for _ in range(5):
            LoginRateThrottle().allow_request(request, None)
        caches['default'].clear()
        self.assertFalse(LoginRateThrottle().allow_request(request, None))


class LoginThrottleIdentityTests(SimpleTestCase):
    """El bucket de throttle no lo puede elegir el cliente (auditoría run-1,
    `core/throttling/login-key-trusts-unvalidated-forwarded-for`).

    Antes, `LoginUserRateThrottle` leía `HTTP_X_FORWARDED_FOR` a mano y tomaba
    el valor de más a la IZQUIERDA — el segmento que un cliente fija libremente
    cuando la cabecera se añade en vez de reemplazarse. Como la clave es
    `ip_username`, una IP distinta era cupo nuevo para el mismo usuario: el
    límite de 5/15min se evadía rotando la cabecera.

    Ahora ambas clases derivan la identidad de `get_ident`, que respeta
    `REST_FRAMEWORK['NUM_PROXIES']` y toma el elemento de más a la DERECHA (el
    que escribe el proxy). Estos tests afirman sobre la configuración REAL del
    proyecto, no sobre un override: si alguien quita `NUM_PROXIES`, se ponen
    rojos.
    """

    def setUp(self):
        caches['throttle_login'].clear()
        self.factory = APIRequestFactory()

    def _post(self, username='victima', xff=None, body=None):
        """Petición DRF real.

        `LoginUserRateThrottle.get_cache_key` lee `request.data`, que solo
        existe en el `Request` de DRF: un `WSGIRequest` crudo de la factory no
        lo tiene. Por eso se envuelve con su parser, igual que lo hace la vista
        de login en producción.
        """
        extra = {'HTTP_X_FORWARDED_FOR': xff} if xff is not None else {}
        payload = {'username': username} if body is None else body
        wsgi = self.factory.post('/api/token/', payload, format='json', **extra)
        request = Request(wsgi, parsers=[JSONParser()])
        request.user = AnonymousUser()
        return request

    def test_num_proxies_is_declared(self):
        """Sin NUM_PROXIES, `get_ident` usa TODA la cabecera como identidad y
        vuelve a ser elegible por el cliente. Es el supuesto que la aplicación
        debe declarar en vez de dejarlo implícito en el proxy."""
        from django.conf import settings
        self.assertIsNotNone(
            settings.REST_FRAMEWORK.get('NUM_PROXIES'),
            "NUM_PROXIES no declarado: la identidad del throttle vuelve a "
            "derivarse de toda la cabecera X-Forwarded-For, que controla el "
            "cliente.",
        )

    def test_user_throttle_key_ignores_client_prepended_forwarded_for(self):
        """El escenario de evasión: el atacante prepende una IP inventada.

        El proxy confiable escribe su valor al final, así que ambas peticiones
        deben caer en el MISMO bucket.
        """
        throttle = LoginUserRateThrottle()
        honest = throttle.get_cache_key(self._post(xff='203.0.113.7'), None)
        spoofed = throttle.get_cache_key(
            self._post(xff='9.9.9.9, 203.0.113.7'), None,
        )
        self.assertEqual(honest, spoofed)

    def test_ip_throttle_key_ignores_client_prepended_forwarded_for(self):
        throttle = LoginRateThrottle()
        honest = throttle.get_cache_key(self._post(xff='203.0.113.7'), None)
        spoofed = throttle.get_cache_key(
            self._post(xff='9.9.9.9, 203.0.113.7'), None,
        )
        self.assertEqual(honest, spoofed)

    def test_user_throttle_key_falls_back_to_remote_addr(self):
        """Sin cabecera, la identidad sale de REMOTE_ADDR y sigue habiendo clave."""
        key = LoginUserRateThrottle().get_cache_key(self._post(), None)
        self.assertTrue(key)
        self.assertIn('victima', key)

    def test_user_throttle_key_is_stable_across_username_variants(self):
        """El cupo por cuenta no se parte con identificadores equivalentes.

        Si `Ana`, ` ana ` y `ANA` cayeran en buckets distintos, el límite por
        cuenta se multiplicaría por cada variante de capitalización.
        """
        throttle = LoginUserRateThrottle()
        keys = {
            throttle.get_cache_key(self._post(username=u, xff='203.0.113.7'), None)
            for u in ('Ana', ' ana ', 'ANA', 'aNa')
        }
        self.assertEqual(len(keys), 1, f"El cupo por cuenta se parte: {keys}")

    def test_different_accounts_get_different_buckets(self):
        """Contraparte: dos cuentas distintas no comparten cupo."""
        throttle = LoginUserRateThrottle()
        a = throttle.get_cache_key(self._post(username='ana', xff='203.0.113.7'), None)
        b = throttle.get_cache_key(self._post(username='luis', xff='203.0.113.7'), None)
        self.assertNotEqual(a, b)

    def test_user_throttle_key_without_username_is_ip_only(self):
        """Contrato preexistente: sin username, no se ignora la petición."""
        request = self._post(xff='203.0.113.7', body={})
        key = LoginUserRateThrottle().get_cache_key(request, None)
        self.assertTrue(key)
        self.assertIn('ip_', key)
