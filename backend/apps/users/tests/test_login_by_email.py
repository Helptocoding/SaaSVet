"""
ADR p48 — Fase 4: login por correo O username (resolver) + fix del gate de
temp-password (`config/urls.py`, lookup por user_id del token).

Protege:
  - login por correo (exacto y case-insensitive) y por username (regresión);
  - resolución al tenant correcto (el correo de B resuelve a B, nunca a A);
  - 401 genérico para correo/username inexistente y contraseña incorrecta;
  - usuario desactivado no entra por correo ni por username (gate is_active);
  - 403 `temp_password_expired` vía login por correo (prueba el fix del gate);
  - flag `must_change_password` vía login por correo.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.organizations.models import Organization

User = get_user_model()

LOGIN_URL = "/api/token/"
PW = "VetPass1234!"


class LoginByEmailTests(APITestCase):
    def setUp(self):
        cache.clear()
        # El throttle de login usa la cache `throttle_login` (alias distinto de
        # `default`); limpiarla aísla el bucket 5/15min por test.
        caches["throttle_login"].clear()
        self.client = APIClient()
        self.org_a = Organization.objects.create(name="Login Org A", timezone="UTC")
        self.org_b = Organization.objects.create(name="Login Org B", timezone="UTC")
        self.vet_a = User.objects.create_user(
            username="vet_a", email="vet.a@clinic.test", password=PW,
            role="VET", organization=self.org_a,
        )
        self.vet_b = User.objects.create_user(
            username="vet_b", email="vet.b@clinic.test", password=PW,
            role="VET", organization=self.org_b,
        )

    def _login(self, identifier, password=PW):
        return self.client.post(
            LOGIN_URL, {"username": identifier, "password": password}, format="json"
        )

    def _uid(self, resp):
        return int(AccessToken(resp.data["access"])["user_id"])

    # ── login por correo / username ──────────────────────────────────────
    def test_login_by_email_exact(self):
        r = self._login("vet.a@clinic.test")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertEqual(self._uid(r), self.vet_a.pk)

    def test_login_by_email_case_insensitive(self):
        r = self._login("VET.A@Clinic.Test")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertEqual(self._uid(r), self.vet_a.pk)

    def test_login_by_username_still_works(self):
        r = self._login("vet_a")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertEqual(self._uid(r), self.vet_a.pk)

    # ── tenant correcto ──────────────────────────────────────────────────
    def test_login_resolves_correct_tenant(self):
        r = self._login("vet.b@clinic.test")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        uid = self._uid(r)
        self.assertEqual(uid, self.vet_b.pk)
        self.assertEqual(User.objects.get(pk=uid).organization_id, self.org_b.pk)

    # ── 401 uniforme ─────────────────────────────────────────────────────
    def test_unknown_email_401(self):
        self.assertEqual(self._login("nobody@nowhere.test").status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_unknown_username_401(self):
        self.assertEqual(self._login("ghost").status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_wrong_password_401(self):
        self.assertEqual(self._login("vet.a@clinic.test", password="wrong").status_code,
                         status.HTTP_401_UNAUTHORIZED)

    # ── is_active ────────────────────────────────────────────────────────
    def test_deactivated_user_cannot_login(self):
        self.vet_a.is_active = False
        self.vet_a.save(update_fields=["is_active"])
        self.assertEqual(self._login("vet.a@clinic.test").status_code,
                         status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self._login("vet_a").status_code,
                         status.HTTP_401_UNAUTHORIZED)

    # ── gate temp-password vía correo (fix urls.py) ──────────────────────
    def test_temp_password_expired_via_email_403(self):
        self.vet_a.password_must_change = True
        self.vet_a.password_temp_issued_at = timezone.now() - timedelta(hours=25)
        self.vet_a.save(update_fields=["password_must_change", "password_temp_issued_at"])
        r = self._login("vet.a@clinic.test")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)
        self.assertEqual(r.data.get("code"), "temp_password_expired")

    def test_must_change_flag_via_email(self):
        self.vet_a.password_must_change = True
        self.vet_a.password_temp_issued_at = None
        self.vet_a.save(update_fields=["password_must_change", "password_temp_issued_at"])
        r = self._login("vet.a@clinic.test")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertTrue(r.data.get("must_change_password"))
