"""
test_vaccines_rbac.py — É0-PR1: regresión del gap RBAC de vacunas.

Bug corregido: `VaccineRecordListCreateView` / `VaccineRecordDetailView`
declaran `resource_name="vaccinerecord"` pero el catálogo no tenía códigos
`vaccinerecord.*` → un VET/ASSISTANT con UserRole en DB (path DB-first de
HybridPermission, sin fallback) recibía RBAC_DENIED en GET /api/vaccines/.
Solo ADMIN (`*.*`) y superuser pasaban. El frontend SÍ llama ese endpoint
(ficha de mascota post-ADR p50 y banner del protocolo Vacuna).

Los roles se siembran DESDE `PERMISSIONS` (el catálogo real), no con listas
locales: si el catálogo vuelve a perder los códigos, estos tests fallan.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.medical_records.models import VaccineRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _seed_role_from_catalog(org, role_name):
    """Rol en DB con EXACTAMENTE los códigos del catálogo (como seed_permissions)."""
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True}
    )
    if "*.*" in codes:
        wildcard, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([wildcard])
    else:
        perms = [Permission.objects.get_or_create(code=c)[0] for c in codes]
        role.permissions.set(perms)
    return role


def _make_user(username, org, role_name):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role=role_name
    )
    UserRole.objects.get_or_create(user=u, role=_seed_role_from_catalog(org, role_name))
    return u


class VaccineRbacTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Vac RBAC Org", timezone="UTC")
        cls.vet = _make_user("vac_rbac_vet", cls.org, "VET")
        cls.assistant = _make_user("vac_rbac_asst", cls.org, "ASSISTANT")
        owner = Owner.objects.create(
            organization=cls.org, name="Ow RBAC", phone="5511223344"
        )
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=owner, name="Kira",
            species="perro", birth_date="2022-01-01",
        )
        cls.vac = VaccineRecord.objects.create(
            organization=cls.org, pet=cls.pet,
            vaccine_name="Antirrábica", application_date="2026-06-01",
        )

    def test_vet_with_db_role_can_list_vaccines(self):
        """Regresión directa del bug: antes 403, ahora 200."""
        self.client.force_authenticate(self.vet)
        r = self.client.get("/api/vaccines/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_vet_with_db_role_can_retrieve_vaccine(self):
        self.client.force_authenticate(self.vet)
        r = self.client.get(f"/api/vaccines/{self.vac.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_assistant_with_db_role_can_list_vaccines(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/vaccines/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_vet_can_create_vaccine_manually(self):
        self.client.force_authenticate(self.vet)
        r = self.client.post("/api/vaccines/", {
            "pet": self.pet.pk,
            "vaccine_name": "Triple felina",
            "application_date": "2026-07-01",
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

    def test_assistant_cannot_create_vaccine(self):
        """ASSISTANT es list/retrieve: registrar vacunas es acto clínico."""
        self.client.force_authenticate(self.assistant)
        r = self.client.post("/api/vaccines/", {
            "pet": self.pet.pk,
            "vaccine_name": "Triple felina",
            "application_date": "2026-07-01",
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)
