"""
test_staff_deactivate_uuid.py — Día 6 audit F20 (ADR p18 Fase 5)

Cubre:
  - DELETE /staff/<uuid>/ propio → 204
  - DELETE /staff/<uuid>/ otra org → 404
  - DELETE /staff/<int_pk>/ con flag OFF → 404
  - DELETE /staff/not-a-uuid/ → 404
  - F13: self-deactivation bloqueada con ValidationError (400)
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization

User = get_user_model()


def _seed_admin(org):
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
    UserRole.objects.get_or_create(user=u, role=_seed_admin(org))
    return u


class StaffDeactivateUuidTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Staff Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Staff Org B", timezone="UTC")
        cls.admin_a = _make_admin("sd_admin_a", cls.org_a)
        _seed_admin(cls.org_b)

        cls.vet_a = User.objects.create_user(
            username="sd_vet_a", password="pass",
            organization=cls.org_a, role="VET",
        )
        cls.vet_b = User.objects.create_user(
            username="sd_vet_b", password="pass",
            organization=cls.org_b, role="VET",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_deactivate_own_org_user_returns_204(self):
        r = self.client.delete(f"/api/staff/{self.vet_a.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT, r.content)
        self.vet_a.refresh_from_db()
        self.assertFalse(self.vet_a.is_active)

    def test_deactivate_cross_tenant_user_returns_404(self):
        r = self.client.delete(f"/api/staff/{self.vet_b.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        self.vet_b.refresh_from_db()
        self.assertTrue(self.vet_b.is_active)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_deactivate_pk_returns_404_when_flag_off(self):
        r = self.client.delete(f"/api/staff/{self.vet_a.pk}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_deactivate_malformed_uuid_returns_404(self):
        r = self.client.delete("/api/staff/not-a-uuid/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_self_deactivation_blocked(self):
        """F13: admin no puede desactivarse a sí mismo (lockout prevention)."""
        r = self.client.delete(f"/api/staff/{self.admin_a.public_id}/")
        # ValidationError → 400 via DRF default
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.admin_a.refresh_from_db()
        self.assertTrue(self.admin_a.is_active)
