"""
test_service_account_throttle.py — É-F1 PR-10 (riesgo R9).

ServiceAwareUserRateThrottle: exime service accounts del rate global de
usuario; los humanos delegan al UserRateThrottle estándar (comportamiento
previo intacto).

Se prueba la CLASE directamente (no vía override_settings): DRF cachea
``api_settings`` al importar, así que sobreescribir REST_FRAMEWORK en un
test no re-inicializa el throttle real — probar el branch propio es más
honesto y no re-testea la maquinaria de DRF (ya cubierta upstream).
"""
from unittest import mock

from django.test import TestCase

from apps.core.throttling import ServiceAwareUserRateThrottle
from apps.organizations.models import Organization
from apps.users.models import User
from apps.users.services import ensure_agent_user
from apps.core.models import Permission, Role
from apps.core.permissions_codes import PERMISSIONS


def _fake_request(user):
    request = mock.Mock()
    request.user = user
    return request


class ServiceAwareThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Thr Org", timezone="UTC")
        role, _ = Role.objects.get_or_create(
            name="AGENT", organization=cls.org,
            defaults={"is_system_role": True},
        )
        role.permissions.set([
            Permission.objects.get_or_create(code=c)[0]
            for c in PERMISSIONS["AGENT"]
        ])
        cls.agent, _ = ensure_agent_user(cls.org)
        cls.human = User.objects.create_user(
            username="thr_human", password="pass",
            organization=cls.org, role="ASSISTANT",
        )

    def test_service_account_is_exempt_short_circuits(self):
        """El AGENT devuelve True sin tocar el rate limiter (no llama super)."""
        throttle = ServiceAwareUserRateThrottle()
        with mock.patch.object(
            ServiceAwareUserRateThrottle.__bases__[0],
            "allow_request",
        ) as super_allow:
            self.assertTrue(
                throttle.allow_request(_fake_request(self.agent), view=None)
            )
            super_allow.assert_not_called()

    def test_human_delegates_to_standard_throttle(self):
        """Un humano SÍ pasa por el rate limiter estándar (no se exime)."""
        throttle = ServiceAwareUserRateThrottle()
        with mock.patch.object(
            ServiceAwareUserRateThrottle.__bases__[0],
            "allow_request", return_value=False,
        ) as super_allow:
            self.assertFalse(
                throttle.allow_request(_fake_request(self.human), view=None)
            )
            super_allow.assert_called_once()

    def test_unauthenticated_delegates(self):
        anon = mock.Mock()
        anon.is_authenticated = False
        throttle = ServiceAwareUserRateThrottle()
        with mock.patch.object(
            ServiceAwareUserRateThrottle.__bases__[0],
            "allow_request", return_value=True,
        ) as super_allow:
            throttle.allow_request(_fake_request(anon), view=None)
            super_allow.assert_called_once()
