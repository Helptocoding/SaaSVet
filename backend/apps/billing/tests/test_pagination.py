"""
P1-2 — Paginación de Cobros (InvoiceListCreateView).

Cubre: contrato PageNumber, tope page_size, orden estable con tiebreaker `-id`,
ordering server-side y aislamiento multi-tenant del `count`.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import Invoice
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
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


class InvoicePaginationTests(APITestCase):
    URL = '/api/billing/invoices/'

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Org PAG A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Org PAG B", timezone="UTC")
        cls.admin_a = _make_user("adm_pag_a", cls.org_a, "ADMIN")

        cls.owner_a = Owner.objects.create(name="Own PAG A", phone="5551110001", organization=cls.org_a)
        cls.pet_a = Pet.objects.create(name="Pet PAG A", species="dog", owner=cls.owner_a, organization=cls.org_a)
        cls.owner_b = Owner.objects.create(name="Own PAG B", phone="5552220001", organization=cls.org_b)

        # 30 facturas en org A → 2 páginas (25 + 5).
        cls.invoices_a = [
            Invoice.objects.create(
                owner=cls.owner_a, pet=cls.pet_a, organization=cls.org_a,
                status='draft', invoice_type='direct_sale', total=Decimal(str(i)),
            )
            for i in range(30)
        ]
        # 4 facturas en org B → no deben contarse para org A.
        for i in range(4):
            Invoice.objects.create(
                owner=cls.owner_b, organization=cls.org_b,
                status='draft', invoice_type='direct_sale', total=Decimal('1'),
            )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_response_is_paginated_envelope(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for key in ('count', 'next', 'previous', 'results'):
            self.assertIn(key, r.data)
        self.assertEqual(r.data['count'], 30)
        self.assertEqual(len(r.data['results']), 25)   # page_size default
        self.assertIsNotNone(r.data['next'])
        self.assertIsNone(r.data['previous'])

    def test_second_page_has_remainder(self):
        r = self.client.get(self.URL, {'page': 2})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data['results']), 5)
        self.assertIsNone(r.data['next'])
        self.assertIsNotNone(r.data['previous'])

    def test_pages_do_not_overlap(self):
        p1 = self.client.get(self.URL, {'page': 1}).data['results']
        p2 = self.client.get(self.URL, {'page': 2}).data['results']
        ids1 = {row['id'] for row in p1}
        ids2 = {row['id'] for row in p2}
        self.assertEqual(len(ids1), 25)
        self.assertEqual(ids1 & ids2, set())          # sin solape (tiebreaker -id)
        self.assertEqual(len(ids1 | ids2), 30)        # cobertura total

    def test_page_size_capped_at_max(self):
        r = self.client.get(self.URL, {'page_size': 9999})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(r.data['results']), 100)   # max_page_size
        self.assertEqual(len(r.data['results']), 30)         # solo hay 30

    def test_custom_page_size_respected(self):
        r = self.client.get(self.URL, {'page_size': 10})
        self.assertEqual(len(r.data['results']), 10)
        self.assertEqual(r.data['count'], 30)

    def test_default_ordering_desc_created_then_id(self):
        # created_at idéntico (bulk en setUpTestData) → desempata -id desc.
        r = self.client.get(self.URL)
        ids = [row['id'] for row in r.data['results']]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_ordering_param_total_asc(self):
        r = self.client.get(self.URL, {'ordering': 'total', 'page_size': 100})
        totals = [Decimal(str(row['total'])) for row in r.data['results']]
        self.assertEqual(totals, sorted(totals))

    def test_count_is_tenant_scoped(self):
        # org A tiene 30; las 4 de org B nunca entran al count ni a results.
        r = self.client.get(self.URL, {'page_size': 100})
        self.assertEqual(r.data['count'], 30)
        owner_ids = {row['owner'] for row in r.data['results']}
        self.assertNotIn(self.owner_b.pk, owner_ids)


class InvoiceOrderingStabilityTests(APITestCase):
    """
    StableOrderingFilter: `?ordering=total` con valores empatados NO debe
    duplicar ni saltar filas entre páginas (el tiebreaker `-id` da orden total).
    """
    URL = '/api/billing/invoices/'

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org ORD", timezone="UTC")
        cls.admin = _make_user("adm_ord", cls.org, "ADMIN")
        cls.owner = Owner.objects.create(name="Own ORD", phone="5551112222", organization=cls.org)
        cls.pet = Pet.objects.create(name="Pet ORD", species="dog", owner=cls.owner, organization=cls.org)
        # 30 facturas con el MISMO total → empate total para forzar el desempate.
        for _ in range(30):
            Invoice.objects.create(
                owner=cls.owner, pet=cls.pet, organization=cls.org,
                status='draft', invoice_type='direct_sale', total=Decimal('0.00'),
            )

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_ordering_total_paged_no_overlap_no_skip(self):
        seen = []
        for page in (1, 2, 3):
            r = self.client.get(self.URL, {'ordering': 'total', 'page_size': 10, 'page': page})
            self.assertEqual(r.status_code, status.HTTP_200_OK)
            seen.extend(row['id'] for row in r.data['results'])
        self.assertEqual(len(seen), 30)            # cubrió todo
        self.assertEqual(len(set(seen)), 30)       # sin duplicados pese al empate
