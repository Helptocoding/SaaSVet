"""
ADR p48 — Fase 2: índice único case-insensitive parcial sobre `User.email`.

Protege el invariante de identidad:
  - dos usuarios con el mismo correo (case-insensitive) NO pueden coexistir;
  - los correos vacíos SÍ conviven (cuentas técnicas/bootstrap/seeds/fixtures);
  - correos distintos no se bloquean entre sí.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.organizations.models import Organization

User = get_user_model()


class EmailCiUniqueConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Email CI Org", timezone="UTC")

    def _mk(self, username, email):
        return User.objects.create_user(
            username=username, password="x", email=email,
            organization=self.org, role="VET",
        )

    def test_duplicate_email_case_insensitive_rejected(self):
        self._mk("u1", "Vet@Clinica.com")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._mk("u2", "vet@clinica.com")

    def test_exact_duplicate_email_rejected(self):
        self._mk("u3", "a@b.com")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._mk("u4", "a@b.com")

    def test_blank_emails_coexist(self):
        # Índice parcial WHERE email<>'' → varias cuentas sin correo conviven.
        self._mk("sys1", "")
        self._mk("sys2", "")
        self.assertEqual(User.objects.filter(email="").count(), 2)

    def test_distinct_emails_ok(self):
        self._mk("u5", "x@y.com")
        self._mk("u6", "z@y.com")
        self.assertEqual(User.objects.exclude(email="").count(), 2)
