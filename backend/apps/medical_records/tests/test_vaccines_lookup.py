"""
test_vaccines_lookup.py — Día 6 audit F19 (ADR p18 Fase 5)

VaccineRecord promovido a modelo público con public_id (UUID). Verifica:
  - GET /vaccines/<uuid>/ propio → 200
  - GET /vaccines/<uuid>/ otra org → 404 (no leak)
  - GET /vaccines/<int_pk>/ con flag OFF → 404
  - GET /vaccines/not-a-uuid/ → 404 (no 500)
  - DELETE bloqueado por consistencia NOM (PR-4B)
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.medical_records.models import VaccineRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

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


class VaccineUuidLookupTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Vac Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Vac Org B", timezone="UTC")
        cls.admin_a = _make_admin("vac_admin_a", cls.org_a)
        _seed_admin(cls.org_b)

        owner_a = Owner.objects.create(
            organization=cls.org_a, name="OwA", phone="5500110011"
        )
        cls.pet_a = Pet.objects.create(
            organization=cls.org_a, owner=owner_a, name="PetA",
            species="perro", birth_date="2020-01-01",
        )
        cls.vac_a = VaccineRecord.objects.create(
            organization=cls.org_a, pet=cls.pet_a,
            vaccine_name="Antirrábica", application_date="2026-04-01",
        )

        owner_b = Owner.objects.create(
            organization=cls.org_b, name="OwB", phone="5599220022"
        )
        pet_b = Pet.objects.create(
            organization=cls.org_b, owner=owner_b, name="PetB",
            species="gato", birth_date="2021-01-01",
        )
        cls.vac_b = VaccineRecord.objects.create(
            organization=cls.org_b, pet=pet_b,
            vaccine_name="Triple", application_date="2026-04-15",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_get_own_vaccine_uuid_returns_200(self):
        r = self.client.get(f"/api/vaccines/{self.vac_a.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_get_cross_tenant_vaccine_returns_404(self):
        r = self.client.get(f"/api/vaccines/{self.vac_b.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_get_vaccine_pk_returns_404_when_flag_off(self):
        r = self.client.get(f"/api/vaccines/{self.vac_a.pk}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_get_malformed_uuid_returns_404(self):
        r = self.client.get("/api/vaccines/not-a-uuid/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_delete_blocked_by_method_restriction(self):
        """PR-4B / ADR p16: DELETE removido por motivación NOM."""
        r = self.client.delete(f"/api/vaccines/{self.vac_a.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_405_METHOD_NOT_ALLOWED, r.content)


class VaccineListQueryParamTests(APITestCase):
    """?pet=<uuid> resuelve via resolve_public_id (Fase 3)."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="VQ Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="VQ Org B", timezone="UTC")
        cls.admin_a = _make_admin("vq_admin_a", cls.org_a)
        _seed_admin(cls.org_b)

        owner_a = Owner.objects.create(
            organization=cls.org_a, name="OwA", phone="5599881100"
        )
        cls.pet_a = Pet.objects.create(
            organization=cls.org_a, owner=owner_a, name="PetA",
            species="perro", birth_date="2020-01-01",
        )
        VaccineRecord.objects.create(
            organization=cls.org_a, pet=cls.pet_a,
            vaccine_name="V1", application_date="2026-04-01",
        )

        owner_b = Owner.objects.create(
            organization=cls.org_b, name="OwB", phone="5577880011"
        )
        cls.pet_b = Pet.objects.create(
            organization=cls.org_b, owner=owner_b, name="PetB",
            species="gato", birth_date="2021-01-01",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_pet_uuid_filters_correctly(self):
        r = self.client.get(f"/api/vaccines/?pet={self.pet_a.public_id}")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        body = r.json()
        results = body if isinstance(body, list) else body.get("results", [])
        self.assertEqual(len(results), 1)

    def test_cross_tenant_pet_returns_404(self):
        r = self.client.get(f"/api/vaccines/?pet={self.pet_b.public_id}")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
