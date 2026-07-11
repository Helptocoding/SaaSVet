"""
Tests de B1 — recepción de mercancía multi-lote (receive_stock + endpoint).

Cubre: una compra con varios lotes entra en una sola operación y queda trazada;
find-or-create por (product, lot_number, expiry); conversión por conversion_factor;
bloqueo en productos sin tracks_lots.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product, StockLot, StockMovement
from apps.inventory.services import receive_stock
from apps.organizations.models import Organization
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
            name=name, organization=org, defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map]
        )
        roles[name] = role
    return roles


class ReceptionSetupMixin:
    def setUp(self):
        self.org = Organization.objects.create(
            name='Org Recep', timezone='UTC', tax_rate=Decimal('0'),
        )
        self.roles = _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='admin_rc', password='pass1234!', organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=self.roles['ADMIN'])
        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='VAC-RC', organization=self.org,
            base_unit='vial', tracks_lots=True, manufacturer='Zoetis',
        )
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial',
            quantity=Decimal('1'), conversion_factor=Decimal('1'),
            sale_price=Decimal('120.00'), stock=Decimal('0'), organization=self.org,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _receive_url(self):
        return f'/api/inventory/presentations/{self.presentation.public_id}/receive/'


class ReceiveServiceTests(ReceptionSetupMixin, TestCase):
    def test_two_lots_one_operation(self):
        with transaction.atomic():
            affected = receive_stock(
                self.presentation,
                lots=[
                    {'lot_number': 'A123', 'expiry_date': '2027-05-01', 'quantity': Decimal('10')},
                    {'lot_number': 'A124', 'expiry_date': '2028-01-01', 'quantity': Decimal('5')},
                ],
                organization=self.org, supplier_name='Distribuidora X',
                created_by=self.admin,
            )
        self.assertEqual(len(affected), 2)
        self.assertEqual(StockLot.objects.filter(product=self.product).count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('15'))
        a123 = StockLot.objects.get(product=self.product, lot_number='A123')
        self.assertEqual(a123.quantity_on_hand, Decimal('10'))
        self.assertEqual(a123.supplier_name, 'Distribuidora X')
        # cada lote generó un movimiento 'in' con la traza del lote
        self.assertEqual(
            StockMovement.objects.filter(product=self.product, movement_type='in').count(), 2
        )

    def test_find_or_create_accumulates_same_lot(self):
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[{'lot_number': 'B1', 'expiry_date': '2027-05-01', 'quantity': Decimal('10')}],
                organization=self.org, created_by=self.admin,
            )
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[{'lot_number': 'B1', 'expiry_date': '2027-05-01', 'quantity': Decimal('4')}],
                organization=self.org, created_by=self.admin,
            )
        self.assertEqual(StockLot.objects.filter(product=self.product, lot_number='B1').count(), 1)
        lot = StockLot.objects.get(product=self.product, lot_number='B1')
        self.assertEqual(lot.quantity_on_hand, Decimal('14'))

    def test_conversion_factor_applied(self):
        # Presentación "Caja de 5 viales" (cf=5): recibir 2 cajas = 10 viales base.
        box = Presentation.objects.create(
            product=self.product, name='Caja 5', base_unit='vial',
            quantity=Decimal('5'), conversion_factor=Decimal('5'),
            sale_price=Decimal('500.00'), stock=Decimal('0'), organization=self.org,
        )
        with transaction.atomic():
            receive_stock(
                box,
                lots=[{'lot_number': 'C1', 'expiry_date': '2027-05-01', 'quantity': Decimal('2')}],
                organization=self.org, created_by=self.admin,
            )
        lot = StockLot.objects.get(product=self.product, lot_number='C1')
        self.assertEqual(lot.quantity_on_hand, Decimal('10'))  # 2 × cf 5

    def test_rejects_non_lot_product(self):
        plain = Product.objects.create(
            name='Shampoo', internal_code='SH-RC', organization=self.org,
            base_unit='piece', tracks_lots=False,
        )
        pres = Presentation.objects.create(
            product=plain, name='Pieza', base_unit='piece', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('50'), stock=Decimal('0'),
            organization=self.org,
        )
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                receive_stock(
                    pres,
                    lots=[{'lot_number': 'X', 'expiry_date': None, 'quantity': Decimal('1')}],
                    organization=self.org, created_by=self.admin,
                )


class ReceiveEndpointTests(ReceptionSetupMixin, TestCase):
    def test_post_receive_two_lots(self):
        resp = self.client.post(self._receive_url(), {
            'supplier_name': 'Dist X',
            'lots': [
                {'lot_number': 'A123', 'expiry_date': '2027-05-01', 'quantity': '10'},
                {'lot_number': 'A124', 'expiry_date': '2028-01-01', 'quantity': '5'},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data['lots']), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('15'))

    def test_post_receive_requires_lot_number(self):
        resp = self.client.post(self._receive_url(), {
            'lots': [{'lot_number': '', 'expiry_date': '2027-05-01', 'quantity': '10'}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_post_receive_empty_lots_rejected(self):
        resp = self.client.post(self._receive_url(), {'lots': []}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_post_receive_non_lot_product_400(self):
        plain = Product.objects.create(
            name='Collar', internal_code='CO-RC', organization=self.org,
            base_unit='piece', tracks_lots=False,
        )
        pres = Presentation.objects.create(
            product=plain, name='Pieza', base_unit='piece', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('80'), stock=Decimal('0'),
            organization=self.org,
        )
        resp = self.client.post(
            f'/api/inventory/presentations/{pres.public_id}/receive/',
            {'lots': [{'lot_number': 'A', 'quantity': '1'}]}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data.get('code'), 'validation_error')

    def test_lots_listed_via_product_endpoint(self):
        self.client.post(self._receive_url(), {
            'lots': [{'lot_number': 'A123', 'expiry_date': '2027-05-01', 'quantity': '10'}],
        }, format='json')
        resp = self.client.get(f'/api/inventory/products/{self.product.public_id}/lots/')
        self.assertEqual(resp.status_code, 200)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        self.assertTrue(any(r['lot_number'] == 'A123' for r in rows))
