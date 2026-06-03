"""
Tests para MedicalRecordProduct.cost_behavior (ADR p32).

cost_behavior='charge'   → descuenta stock + crea InvoiceItem
cost_behavior='included' → descuenta stock + NO crea InvoiceItem
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.models import Invoice, InvoiceItem
from apps.billing.services import confirm_invoice, cancel_invoice
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import MedicalRecordProduct, Presentation, Product
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {
        code: Permission.objects.get_or_create(code=code)[0]
        for code in PERMISSION_CODES
    }
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name,
            organization=org,
            defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


class CostBehaviorSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org CostBehavior',
            timezone='UTC',
            tax_rate=Decimal('0'),
        )
        self.roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='admin_cb',
            password='pass1234!',
            organization=self.org,
            role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])

        self.owner = Owner.objects.create(
            name='Owner CB', phone='5550000001', organization=self.org,
        )
        self.pet = Pet.objects.create(
            name='Perro CB', species='dog', owner=self.owner, organization=self.org,
        )
        self.medical_record = MedicalRecord.objects.create(
            pet=self.pet,
            veterinarian=self.admin,
            organization=self.org,
        )
        self.product = Product.objects.create(
            name='Jeringa 5ml',
            internal_code='JER-001',
            organization=self.org,
        )
        self.presentation = Presentation.objects.create(
            product=self.product,
            name='Unidad',
            base_unit='piece',
            quantity=Decimal('1'),
            conversion_factor=Decimal('1'),
            sale_price=Decimal('5.00'),
            stock=Decimal('500'),
            organization=self.org,
        )
        # ADR p31: Product.stock_quantity = stock real en base_units
        # Presentation.conversion_factor=1 → 1 presentación = 1 pieza
        # stock_quantity = 500 piezas
        Product.objects.filter(pk=self.product.pk).update(
            base_unit='piece',
            stock_quantity=Decimal('500'),
        )
        self.product.refresh_from_db()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _mrp_url(self):
        return f'/api/medical-records/{self.medical_record.public_id}/products/'

    def _mrp_delete_url(self, mrp_id):
        return f'/api/medical-records/{self.medical_record.public_id}/products/{mrp_id}/'


class CostBehaviorChargeTests(CostBehaviorSetupMixin, TestCase):
    """cost_behavior='charge' (default) — comportamiento existente sin regresión."""

    def test_charge_creates_invoice_item(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '2',
            'cost_behavior': 'charge',
        })
        self.assertEqual(resp.status_code, 201, resp.data)

        invoice = Invoice.objects.get(medical_record=self.medical_record)
        item = InvoiceItem.objects.filter(
            invoice=invoice, presentation=self.presentation, is_active=True,
        ).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.quantity, Decimal('2'))
        self.assertEqual(item.unit_price, Decimal('5.00'))

    def test_charge_deducts_stock(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '3',
            'cost_behavior': 'charge',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        # ADR p31: 3 presentaciones × conv_factor=1 = 3 piezas descontadas
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('497'))

    def test_default_is_charge(self):
        # sin enviar cost_behavior → 'charge'
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '1',
        })
        mrp = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        )
        self.assertEqual(mrp.cost_behavior, 'charge')

    def test_charge_serializer_exposes_cost_behavior(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '1',
            'cost_behavior': 'charge',
        })
        self.assertEqual(resp.data['cost_behavior'], 'charge')

    def test_charge_delete_removes_invoice_item(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '2',
            'cost_behavior': 'charge',
        })
        mrp_id = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        ).pk

        self.client.delete(self._mrp_delete_url(mrp_id))

        invoice = Invoice.objects.get(medical_record=self.medical_record)
        item = InvoiceItem.objects.filter(
            invoice=invoice, presentation=self.presentation, is_active=True,
        ).first()
        self.assertIsNone(item)

    def test_charge_delete_reverts_stock(self):
        initial = self.product.stock_quantity
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '5',
            'cost_behavior': 'charge',
        })
        mrp_id = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        ).pk

        self.client.delete(self._mrp_delete_url(mrp_id))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial)


class CostBehaviorIncludedTests(CostBehaviorSetupMixin, TestCase):
    """cost_behavior='included' — no InvoiceItem, sí descuento de stock."""

    def test_included_does_not_create_invoice_item(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '3',
            'cost_behavior': 'included',
        })
        self.assertEqual(resp.status_code, 201, resp.data)

        invoice = Invoice.objects.filter(medical_record=self.medical_record).first()
        if invoice:
            item = InvoiceItem.objects.filter(
                invoice=invoice, presentation=self.presentation, is_active=True,
            ).first()
            self.assertIsNone(item)

    def test_included_deducts_stock(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '10',
            'cost_behavior': 'included',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        # 10 presentaciones × conv_factor=1 = 10 piezas descontadas
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('490'))

    def test_included_serializer_exposes_cost_behavior(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '1',
            'cost_behavior': 'included',
        })
        self.assertEqual(resp.data['cost_behavior'], 'included')

    def test_included_delete_reverts_stock_no_invoice_item(self):
        initial = self.product.stock_quantity
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '7',
            'cost_behavior': 'included',
        })
        mrp_id = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        ).pk

        self.client.delete(self._mrp_delete_url(mrp_id))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, initial)

        invoice = Invoice.objects.filter(medical_record=self.medical_record).first()
        if invoice:
            item = InvoiceItem.objects.filter(
                invoice=invoice, presentation=self.presentation, is_active=True,
            ).first()
            self.assertIsNone(item)


class CostBehaviorImmutabilityTests(CostBehaviorSetupMixin, TestCase):
    """cost_behavior es inmutable tras la creación; incrementos de cantidad lo preservan."""

    def test_quantity_increment_preserves_included(self):
        # Primer POST: included → sin InvoiceItem
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '2',
            'cost_behavior': 'included',
        })
        # Segundo POST (misma presentación): intenta 'charge', debe usar 'included'
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '3',
            'cost_behavior': 'charge',
        })
        mrp = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        )
        self.assertEqual(mrp.cost_behavior, 'included')
        self.assertEqual(mrp.quantity, Decimal('5'))

        # Ningún InvoiceItem creado para esta presentación
        invoice = Invoice.objects.filter(medical_record=self.medical_record).first()
        if invoice:
            item = InvoiceItem.objects.filter(
                invoice=invoice, presentation=self.presentation, is_active=True,
            ).first()
            self.assertIsNone(item)

    def test_quantity_increment_preserves_charge(self):
        # Primer POST: charge → con InvoiceItem
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '2',
            'cost_behavior': 'charge',
        })
        # Segundo POST (misma presentación): intenta 'included', debe usar 'charge'
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '3',
            'cost_behavior': 'included',
        })
        mrp = MedicalRecordProduct.objects.get(
            medical_record=self.medical_record, presentation=self.presentation,
        )
        self.assertEqual(mrp.cost_behavior, 'charge')
        self.assertEqual(mrp.quantity, Decimal('5'))

        # InvoiceItem acumula ambas cantidades
        invoice = Invoice.objects.get(medical_record=self.medical_record)
        item = InvoiceItem.objects.get(
            invoice=invoice, presentation=self.presentation, is_active=True,
        )
        self.assertEqual(item.quantity, Decimal('5'))

    def test_stock_deducts_on_both_increments_regardless_of_behavior(self):
        # Stock descuenta siempre, independiente del cost_behavior
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '4',
            'cost_behavior': 'included',
        })
        self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '6',
        })
        # (4+6) presentaciones × conv_factor=1 = 10 piezas
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('490'))


class CostBehaviorValidationTests(CostBehaviorSetupMixin, TestCase):
    """Rechazar cost_behavior con valores inválidos."""

    def test_invalid_cost_behavior_rejected(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '1',
            'cost_behavior': 'free',
        })
        self.assertEqual(resp.status_code, 400)

    def test_empty_cost_behavior_uses_default(self):
        resp = self.client.post(self._mrp_url(), {
            'presentation': self.presentation.pk,
            'quantity': '1',
            'cost_behavior': '',
        })
        # Vacío → field choice validation fallará o usará default
        # Aceptamos 201 con default 'charge' o 400 por elección inválida
        # Lo importante: nunca 500
        self.assertIn(resp.status_code, [201, 400])
        if resp.status_code == 201:
            mrp = MedicalRecordProduct.objects.get(
                medical_record=self.medical_record, presentation=self.presentation,
            )
            self.assertEqual(mrp.cost_behavior, 'charge')
