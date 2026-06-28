"""
test_deactivate_revokes_session.py — H-06 (auth audit).

Antes: ``StaffDeactivateView`` solo hacía ``is_active=False``. Un usuario
desactivado (ej. empleado despedido) conservaba acceso operativo hasta
``REFRESH_TOKEN_LIFETIME`` (7 días) usando un refresh token emitido antes
de la baja.

Estos tests fijan la garantía "desactivar = cortar acceso" en sus dos
superficies:

  1. El access token previamente emitido deja de funcionar de inmediato
     (gate ``is_active`` en ``TenantJWTAuthentication`` + el propio
     ``CHECK_USER_IS_ACTIVE`` de simplejwt).
  2. El refresh token previamente emitido deja de funcionar: la
     desactivación blacklistea TODOS los ``OutstandingToken`` del target,
     así que ``POST /api/token/refresh/`` lo rechaza con 401 — la cuenta no
     puede mintear nuevos access tokens.

Además se preserva el contrato previo del endpoint (204 en éxito, 400 en
self-deactivation).
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization

User = get_user_model()

ME_URL = '/api/me/'
REFRESH_URL = '/api/token/refresh/'


def _seed_admin_role(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True}
    )
    role.permissions.set([wildcard])
    return role


def _make_admin(username, org):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role="ADMIN"
    )
    UserRole.objects.get_or_create(user=u, role=_seed_admin_role(org))
    return u


class DeactivateRevokesSessionTests(APITestCase):
    def setUp(self):
        cache.clear()
        # El refresh endpoint usa LoginRateThrottle (cache `throttle_login`,
        # alias distinto de `default`). Limpiarlo aísla el bucket 5/15min.
        caches['throttle_login'].clear()

        self.org = Organization.objects.create(name="Deact Org", timezone="UTC")
        self.admin = _make_admin("deact_admin", self.org)
        self.vet = User.objects.create_user(
            username="deact_vet", password="pass",
            organization=self.org, role="VET",
        )

        # Tokens reales del target, emitidos MIENTRAS está activo.
        self.vet_refresh = RefreshToken.for_user(self.vet)
        self.vet_access = str(self.vet_refresh.access_token)

        # Cliente del target con su Bearer token real (NO force_authenticate:
        # necesitamos ejercitar la cadena de autenticación completa).
        self.target_client = APIClient()
        self.target_client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.vet_access}'
        )

    def _deactivate_vet(self):
        """Admin desactiva al vet vía el endpoint real."""
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        return admin_client.delete(f"/api/staff/{self.vet.public_id}/")

    # ── Baseline ──────────────────────────────────────────────────────────

    def test_active_user_access_token_works(self):
        res = self.target_client.get(ME_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    def test_active_user_can_refresh(self):
        public = APIClient()
        res = public.post(
            REFRESH_URL, {'refresh': str(self.vet_refresh)}, format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    # ── H-06 superficie 1: access token previamente emitido ───────────────

    def test_deactivated_user_access_token_rejected(self):
        deact = self._deactivate_vet()
        self.assertEqual(deact.status_code, status.HTTP_204_NO_CONTENT, deact.content)

        # El MISMO access token (aún dentro de su ventana de 15 min) ya no sirve.
        res = self.target_client.get(ME_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)

    # ── H-06 superficie 2: refresh token previamente emitido ──────────────

    def test_deactivated_user_cannot_refresh(self):
        old_refresh = str(self.vet_refresh)
        self._deactivate_vet()

        public = APIClient()
        res = public.post(REFRESH_URL, {'refresh': old_refresh}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED, res.content)

    def test_deactivation_blacklists_all_outstanding_tokens(self):
        # Emitir un segundo refresh para confirmar que se revocan TODOS, no
        # solo el último.
        RefreshToken.for_user(self.vet)
        outstanding = OutstandingToken.objects.filter(user=self.vet).count()
        self.assertGreaterEqual(outstanding, 2)

        self._deactivate_vet()

        blacklisted = BlacklistedToken.objects.filter(token__user=self.vet).count()
        self.assertEqual(blacklisted, outstanding)

    # ── Contrato previo preservado ────────────────────────────────────────

    def test_deactivation_sets_is_active_false(self):
        self._deactivate_vet()
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.is_active)

    def test_self_deactivation_blocked_400(self):
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        res = admin_client.delete(f"/api/staff/{self.admin.public_id}/")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_audit_log_emitted(self):
        with self.assertLogs('users.events', level='INFO') as logs:
            self._deactivate_vet()
        records = [r for r in logs.records if r.msg == 'STAFF_DEACTIVATED']
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.actor_id, self.admin.pk)
        self.assertEqual(rec.target_user_id, self.vet.pk)
        self.assertEqual(rec.organization_id, self.org.pk)
