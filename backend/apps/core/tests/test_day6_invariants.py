"""
test_day6_invariants.py — Cobertura BLOCKERs Día 6 (ADR p18)

5 invariantes obligatorios pre-cutover:
1. flag cutover: PK lookup rechazado con ALLOW_LEGACY_ID_LOOKUP=False.
2. tenant 404 invariant: cross-tenant UUID → 404 (no 403, no 200).
3. query param resolution: ?pet=<uuid> filtra; ?pet=<pk> con flag OFF → 404.
4. CreateEmployeeSerializer.organization_id ignorado en body.
5. /me/ expone organization_public_id (UUID).
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={"is_system_role": True}
        )
        role.permissions.set(
            [wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


def _make_admin(username, org):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role="ADMIN"
    )
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles["ADMIN"])
    return u


class FlagCutoverTests(APITestCase):
    """B4-1: PK lookup rechazado bajo ALLOW_LEGACY_ID_LOOKUP=False."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Cutover Org", timezone="UTC")
        cls.admin = _make_admin("admin1", cls.org)
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Dueño Test", phone="5512345678"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Firulais",
            species="perro", birth_date="2020-01-01",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_pet_detail_pk_returns_404_when_flag_off(self):
        r = self.client.get(f"/api/pets/{self.pet.pk}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_pet_detail_uuid_returns_200_when_flag_off(self):
        r = self.client.get(f"/api/pets/{self.pet.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=True)
    def test_pet_detail_pk_returns_200_when_flag_on(self):
        r = self.client.get(f"/api/pets/{self.pet.pk}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_malformed_uuid_returns_404(self):
        r = self.client.get("/api/pets/not-a-uuid/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class TenantIsolation404InvariantTests(APITestCase):
    """B4-2: cross-tenant UUID retorna 404 (no 403, no 200)."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org B", timezone="UTC")
        cls.admin_a = _make_admin("admin_a", cls.org_a)
        cls.owner_b = Owner.objects.create(
            organization=cls.org_b, name="Owner B", phone="5598765432"
        )
        cls.pet_b = Pet.objects.create(
            organization=cls.org_b, owner=cls.owner_b, name="Pet B",
            species="gato", birth_date="2021-01-01",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_cross_tenant_pet_uuid_returns_404(self):
        # Admin de Org A pasa UUID válido de Pet de Org B → 404 (no 403)
        r = self.client.get(f"/api/pets/{self.pet_b.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=True)
    def test_cross_tenant_pet_pk_returns_404_even_with_flag_on(self):
        # Aun con flag ON, for_organization() bloquea cross-tenant lookup
        r = self.client.get(f"/api/pets/{self.pet_b.pk}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class QueryParamResolutionTests(APITestCase):
    """B4-3: ?pet= resuelve UUID, rechaza PK con flag OFF, cross-tenant 404."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="QP Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="QP Org B", timezone="UTC")
        cls.admin_a = _make_admin("qp_admin_a", cls.org_a)
        cls.owner_a = Owner.objects.create(
            organization=cls.org_a, name="Owner QPA", phone="5511112222"
        )
        cls.pet_a = Pet.objects.create(
            organization=cls.org_a, owner=cls.owner_a, name="PetQPA",
            species="perro", birth_date="2020-01-01",
        )
        cls.pet_b = Pet.objects.create(
            organization=cls.org_b,
            owner=Owner.objects.create(organization=cls.org_b, name="OwnerB", phone="5533334444"),
            name="PetQPB", species="gato", birth_date="2020-01-01",
        )
        MedicalRecord.objects.create(
            organization=cls.org_a, pet=cls.pet_a, veterinarian=cls.admin_a,
            consultation_type="general", diagnosis="dx", treatment="tx",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_pet_uuid_filters_correctly(self):
        r = self.client.get(f"/api/medical-records/?pet={self.pet_a.public_id}")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.json().get("results", r.json())
        self.assertEqual(len(results), 1)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_pet_pk_returns_404_when_flag_off(self):
        # Bug pre-Fase-3: PK aceptado → leak. Post-Fase-3 + flag OFF: 404
        r = self.client.get(f"/api/medical-records/?pet={self.pet_a.pk}")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_cross_tenant_pet_returns_404(self):
        # UUID válido de pet de OTRA org → resolve_public_id falla → 404
        r = self.client.get(f"/api/medical-records/?pet={self.pet_b.public_id}")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(ALLOW_LEGACY_ID_LOOKUP=False)
    def test_invalid_uuid_returns_404(self):
        r = self.client.get("/api/medical-records/?pet=not-a-uuid")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class CreateStaffOrgImmutableTests(APITestCase):
    """B4-4: CreateEmployeeSerializer.organization_id es read_only.
    Body con organization_id no puede crear user en org distinta."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Staff Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Staff Org B", timezone="UTC")
        cls.admin_a = _make_admin("staff_admin_a", cls.org_a)
        # Seed roles para org_b también — sino create_user no asigna RBAC
        _seed_roles(cls.org_b)

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_organization_id_in_body_is_ignored(self):
        # Admin de Org A intenta crear empleado pasando organization_id de Org B
        payload = {
            "username": "evil_vet",
            "email": "evil@example.com",
            "first_name": "Evil",
            "last_name": "Vet",
            "role": "VET",
            "license_number": "1234567",  # M01 (orden 7): obligatoria para VET
            "organization_id": self.org_b.id,
        }
        r = self.client.post("/api/staff/create/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

        created = User.objects.get(username="evil_vet")
        # CRITICAL: user creado en org_a (JWT-derived), NO en org_b (body)
        self.assertEqual(created.organization_id, self.org_a.id)
        self.assertNotEqual(created.organization_id, self.org_b.id)


class MePublicIdResponseTests(APITestCase):
    """B4-5: /me/ expone organization_public_id (UUID) sin romper contrato."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Me Org", timezone="UTC")
        cls.admin = _make_admin("me_admin", cls.org)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_me_response_includes_organization_public_id(self):
        r = self.client.get("/api/me/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertIn("organization_public_id", data)
        self.assertEqual(data["organization_public_id"], str(self.org.public_id))
        # Verifica UUID parseable
        uuid.UUID(data["organization_public_id"])

    def test_me_response_retains_organization_pk_for_backcompat(self):
        # Día 6 deuda permitida D2: ambos campos coexisten pre-beta
        r = self.client.get("/api/me/")
        data = r.json()
        self.assertEqual(data["organization"], self.org.id)
