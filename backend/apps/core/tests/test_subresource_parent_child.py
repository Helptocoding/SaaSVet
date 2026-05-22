"""
test_subresource_parent_child.py — Día 6 audit F17 (ADR p18 §5)

Invariante: sub-recurso detail DEBE filtrar `pk + parent=parent_obj` en la
misma query. Cross-parent (PK del child con UUID parent equivocado) retorna
404, no leak ni 200.

Cubre:
  - InvoiceItem bajo billing/invoices/<uuid>/items/<int:pk>/
  - MedicalRecordService bajo medical-records/<uuid>/services/<int:pk>/
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import Invoice, InvoiceItem, Service
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import MedicalRecord, MedicalRecordService
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _seed_admin_role(org):
    """Seed wildcard admin role per org."""
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
    UserRole.objects.get_or_create(user=u, role=_seed_admin_role(org))
    return u


class InvoiceItemSubresourceTests(APITestCase):
    """Cross-parent y cross-tenant invariants para InvoiceItem."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="Sub Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="Sub Org B", timezone="UTC")
        cls.admin_a = _make_admin("admin_sub_a", cls.org_a)
        _seed_admin_role(cls.org_b)

        cls.owner_a = Owner.objects.create(
            organization=cls.org_a, name="OwA", phone="5500001111"
        )
        cls.pet_a = Pet.objects.create(
            organization=cls.org_a, owner=cls.owner_a, name="PetA",
            species="perro", birth_date="2020-01-01",
        )

        # Dos invoices en org_a + un invoice en org_b
        cls.inv_a1 = Invoice.objects.create(
            organization=cls.org_a, pet=cls.pet_a, owner=cls.owner_a,
            invoice_type='consultation', status='draft',
        )
        cls.inv_a2 = Invoice.objects.create(
            organization=cls.org_a, pet=cls.pet_a, owner=cls.owner_a,
            invoice_type='consultation', status='draft',
        )
        owner_b = Owner.objects.create(
            organization=cls.org_b, name="OwB", phone="5599998888"
        )
        pet_b = Pet.objects.create(
            organization=cls.org_b, owner=owner_b, name="PetB",
            species="gato", birth_date="2021-01-01",
        )
        cls.inv_b = Invoice.objects.create(
            organization=cls.org_b, pet=pet_b, owner=owner_b,
            invoice_type='consultation', status='draft',
        )

        svc_a = Service.objects.create(
            organization=cls.org_a, name="Servicio A", base_price=Decimal("100.00"),
        )
        svc_b = Service.objects.create(
            organization=cls.org_b, name="Servicio B", base_price=Decimal("200.00"),
        )

        # Items: uno por invoice
        cls.item_a1 = InvoiceItem.objects.create(
            invoice=cls.inv_a1, service=svc_a, description="A1",
            quantity=Decimal("1"), unit_price=Decimal("100.00"),
            organization=cls.org_a,
        )
        cls.item_a2 = InvoiceItem.objects.create(
            invoice=cls.inv_a2, service=svc_a, description="A2",
            quantity=Decimal("1"), unit_price=Decimal("100.00"),
            organization=cls.org_a,
        )
        cls.item_b = InvoiceItem.objects.create(
            invoice=cls.inv_b, service=svc_b, description="B",
            quantity=Decimal("1"), unit_price=Decimal("200.00"),
            organization=cls.org_b,
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_get_item_under_correct_parent_returns_200(self):
        r = self.client.get(
            f"/api/billing/invoices/{self.inv_a1.public_id}/items/{self.item_a1.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_get_item_under_wrong_parent_returns_404(self):
        """item_a1 pertenece a inv_a1, NO a inv_a2. Cross-parent → 404."""
        r = self.client.get(
            f"/api/billing/invoices/{self.inv_a2.public_id}/items/{self.item_a1.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_get_cross_tenant_item_returns_404(self):
        """item_b pertenece a org_b. Admin de org_a no debe verlo."""
        r = self.client.get(
            f"/api/billing/invoices/{self.inv_a1.public_id}/items/{self.item_b.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_patch_item_under_wrong_parent_returns_404(self):
        r = self.client.patch(
            f"/api/billing/invoices/{self.inv_a2.public_id}/items/{self.item_a1.id}/",
            {"quantity": "5"}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)

    def test_delete_item_under_wrong_parent_returns_404(self):
        r = self.client.delete(
            f"/api/billing/invoices/{self.inv_a2.public_id}/items/{self.item_a1.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        # item_a1 sigue existiendo
        self.assertTrue(InvoiceItem.objects.filter(pk=self.item_a1.id).exists())


class MedicalRecordServiceSubresourceTests(APITestCase):
    """Cross-parent y cross-tenant invariants para MedicalRecordService."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="MRS Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="MRS Org B", timezone="UTC")
        cls.admin_a = _make_admin("admin_mrs_a", cls.org_a)
        _seed_admin_role(cls.org_b)

        owner_a = Owner.objects.create(
            organization=cls.org_a, name="OwA", phone="5511110000"
        )
        cls.pet_a = Pet.objects.create(
            organization=cls.org_a, owner=owner_a, name="PetA",
            species="perro", birth_date="2020-01-01",
        )
        cls.vet_a = User.objects.create_user(
            username="vet_mrs_a", password="pass",
            organization=cls.org_a, role="VET",
        )

        cls.mr_a1 = MedicalRecord.objects.create(
            organization=cls.org_a, pet=cls.pet_a, veterinarian=cls.vet_a,
            consultation_type="general", diagnosis="dx1", treatment="tx1",
        )
        cls.mr_a2 = MedicalRecord.objects.create(
            organization=cls.org_a, pet=cls.pet_a, veterinarian=cls.vet_a,
            consultation_type="general", diagnosis="dx2", treatment="tx2",
        )

        svc_a = Service.objects.create(
            organization=cls.org_a, name="MRS Svc A", base_price="100.00",
        )
        cls.mrs_a1 = MedicalRecordService.objects.create(
            organization=cls.org_a, medical_record=cls.mr_a1, service=svc_a,
            quantity="1",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin_a)

    def test_delete_mrs_under_wrong_parent_returns_404(self):
        """mrs_a1 pertenece a mr_a1, no a mr_a2."""
        r = self.client.delete(
            f"/api/medical-records/{self.mr_a2.public_id}/services/{self.mrs_a1.id}/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        # mrs_a1 sigue existiendo
        self.assertTrue(MedicalRecordService.objects.filter(pk=self.mrs_a1.id).exists())
