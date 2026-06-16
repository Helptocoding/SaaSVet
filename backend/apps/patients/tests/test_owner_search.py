"""
Búsqueda de clientes (GET /api/owners/?search=) — ADR p44b.

Con clínicas importadas un cliente se diferencia por su teléfono o nº de
expediente, no solo por el nombre (homónimos). El search ahora filtra por
nombre · teléfono · legacy_id, y pagina cuando se manda ?page (habilita el
"Ver más" de EntitySearch) sin romper el contrato de array plano [:20] de los
dropdowns legacy.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


class OwnerSearchTests(APITestCase):
    URL = "/api/owners/"

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org OS A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org OS B", timezone="UTC")
        cls.admin_a = _make_user("adm_os_a", cls.org_a, "ADMIN")

        # Dos homónimos diferenciables por teléfono / expediente.
        cls.luis1 = Owner.objects.create(name="Luis Pérez", phone="8123456780", legacy_id="EXP-100", organization=cls.org_a)
        cls.luis2 = Owner.objects.create(name="Luis Pérez", phone="8123456799", legacy_id="EXP-200", organization=cls.org_a)
        for i in range(30):
            Owner.objects.create(name=f"Luis Cliente {i:02d}", phone=f"55500000{i:02d}", organization=cls.org_a)
        # Ruido en otra org.
        Owner.objects.create(name="Luis Otro", phone="8123456780", organization=cls.org_b)

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_search_by_name(self):
        r = self.client.get(self.URL, {"search": "Luis Pérez"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(all("Luis" in o["name"] for o in r.data))

    def test_search_by_phone_disambiguates(self):
        r = self.client.get(self.URL, {"search": "8123456799"})
        names = [(o["name"], o["phone"]) for o in r.data]
        self.assertEqual(names, [("Luis Pérez", "8123456799")])

    def test_search_by_legacy_id(self):
        r = self.client.get(self.URL, {"search": "EXP-200"})
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]["legacy_id"], "EXP-200")

    def test_search_without_page_is_flat_capped(self):
        r = self.client.get(self.URL, {"search": "Luis"})
        self.assertIsInstance(r.data, list)         # NO envelope
        self.assertLessEqual(len(r.data), 20)       # cap [:20]

    def test_search_with_page_is_paginated(self):
        r = self.client.get(self.URL, {"search": "Luis", "page": 1, "page_size": 8})
        self.assertIn("results", r.data)
        self.assertIn("count", r.data)
        self.assertEqual(len(r.data["results"]), 8)
        self.assertEqual(r.data["count"], 32)       # 2 Pérez + 30 Cliente

    def test_search_load_more_no_overlap(self):
        p1 = self.client.get(self.URL, {"search": "Luis", "page": 1, "page_size": 8}).data["results"]
        p2 = self.client.get(self.URL, {"search": "Luis", "page": 2, "page_size": 8}).data["results"]
        ids1 = {o["public_id"] for o in p1}
        ids2 = {o["public_id"] for o in p2}
        self.assertEqual(ids1 & ids2, set())

    def test_search_tenant_scoped(self):
        # El "Luis Otro" de org B comparte teléfono pero nunca aparece.
        r = self.client.get(self.URL, {"search": "8123456780"})
        self.assertTrue(all(o["name"] != "Luis Otro" for o in r.data))
        self.assertEqual(len(r.data), 1)            # solo el luis1 de org A
