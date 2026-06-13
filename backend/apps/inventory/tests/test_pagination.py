"""
P1-2 — Paginación cursor del ledger de movimientos (StockMovementListView).

Cubre: contrato CursorPagination (results + next, sin count por diseño),
recorrido completo sin duplicar ni saltar filas (orden estable -created_at,-id)
y aislamiento multi-tenant.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product, StockMovement
from apps.organizations.models import Organization
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


def _presentation(org, code):
    product = Product.objects.create(name=f"Prod {code}", internal_code=code, organization=org)
    return Presentation.objects.create(
        product=product, name="Frasco", base_unit="bottle",
        sale_price=Decimal("100"), stock=Decimal("1000"), organization=org,
    )


class StockMovementCursorPaginationTests(APITestCase):
    URL = '/api/inventory/movements/'

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org MOV A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org MOV B", timezone="UTC")
        cls.admin_a = _make_user("adm_mov_a", cls.org_a, "ADMIN")

        cls.pres_a = _presentation(cls.org_a, "MOVA1")
        cls.pres_b = _presentation(cls.org_b, "MOVB1")

        # 120 movimientos org A → 3 páginas de 50/50/20.
        StockMovement.objects.bulk_create([
            StockMovement(
                presentation=cls.pres_a, product=cls.pres_a.product,
                movement_type='in', quantity=Decimal('1'), organization=cls.org_a,
            )
            for _ in range(120)
        ])
        # 10 movimientos org B → no deben aparecer para org A.
        StockMovement.objects.bulk_create([
            StockMovement(
                presentation=cls.pres_b, product=cls.pres_b.product,
                movement_type='in', quantity=Decimal('1'), organization=cls.org_b,
            )
            for _ in range(10)
        ])

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_cursor_envelope_shape(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('results', r.data)
        self.assertIn('next', r.data)
        self.assertIn('previous', r.data)
        self.assertNotIn('count', r.data)            # cursor no expone count
        self.assertEqual(len(r.data['results']), 50)  # page_size
        self.assertIsNotNone(r.data['next'])

    def test_full_walk_no_duplicates_no_skips(self):
        seen = []
        url = self.URL
        guard = 0
        while url and guard < 20:
            r = self.client.get(url)
            self.assertEqual(r.status_code, status.HTTP_200_OK)
            seen.extend(row['id'] for row in r.data['results'])
            url = r.data['next']
            guard += 1
        self.assertEqual(len(seen), 120)             # recorrió todo org A
        self.assertEqual(len(set(seen)), 120)        # sin duplicados (tiebreaker)

    def test_tenant_isolation(self):
        # Recorrer todo y verificar que ningún movimiento es de org B.
        org_b_ids = set(
            StockMovement.objects.filter(organization=self.org_b).values_list('id', flat=True)
        )
        seen = []
        url = self.URL
        guard = 0
        while url and guard < 20:
            r = self.client.get(url)
            seen.extend(row['id'] for row in r.data['results'])
            url = r.data['next']
            guard += 1
        self.assertEqual(set(seen) & org_b_ids, set())
