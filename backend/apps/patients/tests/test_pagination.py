"""
P1-2 — Paginación de Owners + preservación del contrato de búsqueda.

OwnerViewSet pagina el listado completo (PageNumber 25) PERO el path `?search`
NO se pagina: devuelve un array plano [:20] para los dropdowns SearchSelect
(`paginate_queryset` retorna None). Estos tests blindan ambos contratos y el
aislamiento multi-tenant.
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


class OwnerPaginationTests(APITestCase):
    URL = '/api/owners/'

    @classmethod
    def setUpTestData(cls):
        # post_save de Organization siembra 1 Owner genérico por org → se filtra
        # con ?is_generic=false para un conteo de owners reales determinista.
        cls.org_a = Organization.objects.create(name="Org OWN A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org OWN B", timezone="UTC")
        cls.admin_a = _make_user("adm_own_a", cls.org_a, "ADMIN")

        for i in range(30):
            Owner.objects.create(
                name=f"PagOwner {i:02d}", phone=f"55500000{i:02d}", organization=cls.org_a,
            )
        # Ruido en org B (no debe contarse).
        for i in range(5):
            Owner.objects.create(
                name=f"OtherOrg {i}", phone=f"55599999{i:02d}", organization=cls.org_b,
            )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_list_without_search_is_paginated(self):
        r = self.client.get(self.URL, {'is_generic': 'false'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('results', r.data)
        self.assertIn('count', r.data)
        self.assertEqual(r.data['count'], 30)
        self.assertEqual(len(r.data['results']), 25)

    def test_search_returns_plain_array_not_paginated(self):
        r = self.client.get(self.URL, {'search': 'PagOwner'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # Contrato dropdown: array plano, NO envelope paginado.
        self.assertIsInstance(r.data, list)
        self.assertLessEqual(len(r.data), 20)   # cap [:20]
        self.assertTrue(all('PagOwner' in row['name'] for row in r.data))

    def test_pages_cover_all_without_overlap(self):
        p1 = self.client.get(self.URL, {'is_generic': 'false', 'page': 1}).data['results']
        p2 = self.client.get(self.URL, {'is_generic': 'false', 'page': 2}).data['results']
        ids1 = {row['public_id'] for row in p1}
        ids2 = {row['public_id'] for row in p2}
        self.assertEqual(ids1 & ids2, set())
        self.assertEqual(len(ids1 | ids2), 30)

    def test_count_tenant_scoped(self):
        r = self.client.get(self.URL, {'is_generic': 'false', 'page_size': 100})
        self.assertEqual(r.data['count'], 30)   # org B (5) nunca entra
