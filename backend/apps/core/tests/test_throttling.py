from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.test import SimpleTestCase
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
