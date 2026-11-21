"""
ADR p48 — Fase 3: el alta de staff (POST /api/staff/create/) exige correo
obligatorio, normalizado a minúsculas y único global (cross-org incluido).
Mensaje genérico para no ampliar el leak de existencia cross-tenant (T-2).
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import Organization

User = get_user_model()


class StaffEmailEnforcementTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Clinica Email A")
        self.other_org = Organization.objects.create(name="Clinica Email B")
        self.admin = User.objects.create_user(
            username="emailadmin", email="admin@a.test",
            password="AdminPass1234!", role="ADMIN", organization=self.org,
        )
        # Usuario en OTRA org con correo conocido (para el caso cross-org).
        self.other_vet = User.objects.create_user(
            username="othervet", email="dup@shared.test",
            password="x", role="VET", organization=self.other_org,
        )
        self.client.force_authenticate(user=self.admin)

    def _create(self, **over):
        payload = {
            "username": "newvet", "email": "new@a.test",
            "password": "VetPass1234", "role": "VET",
            "first_name": "Nueva",  # D4 (plan Equipo): obligatorio en el alta
            "license_number": "1234567",  # M01: obligatoria para VET
        }
        payload.update(over)
        return self.client.post("/api/staff/create/", payload, format="json")

    def test_normalizes_email_to_lowercase(self):
        resp = self._create(username="mixedcase", email="New.Vet@A.Test")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(
            User.objects.get(username="mixedcase").email, "new.vet@a.test"
        )

    def test_rejects_duplicate_email_same_org(self):
        self.assertEqual(self._create(username="first", email="taken@a.test").status_code,
                         status.HTTP_201_CREATED)
        resp = self._create(username="second", email="taken@a.test")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)

    def test_rejects_duplicate_email_case_insensitive(self):
        self._create(username="first", email="ci@a.test")
        resp = self._create(username="second", email="CI@A.test")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)

    def test_rejects_duplicate_email_cross_org(self):
        # Único global: el correo de un usuario de OTRA org no se puede reusar.
        resp = self._create(username="collide", email="dup@shared.test")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)

    def test_generic_message_does_not_leak_org(self):
        resp = self._create(username="collide2", email="dup@shared.test")
        body = resp.content.decode().lower()
        self.assertNotIn("email b", body)
        self.assertNotIn("othervet", body)

    def test_rejects_missing_email(self):
        resp = self.client.post(
            "/api/staff/create/",
            # first_name presente (D4) para que el 400 se deba solo al correo.
            {"username": "noemail", "password": "VetPass1234", "role": "VET",
             "first_name": "Nueva"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
