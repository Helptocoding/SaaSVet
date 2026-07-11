"""
Tests de B2b — consumo/reverso por lote en billing (venta directa).

confirm/cancel rutean por consume_product/restock_product sobre InvoiceItem.lot:
  - confirmar descuenta el lote del ítem
  - cancelar revierte al MISMO lote (P4)
Productos sin tracks_lots: item.lot None → path histórico (cubierto por la suite billing).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem
from apps.billing.services import confirm_invoice, cancel_invoice
from apps.inventory.models import Presentation, Product, StockLot
from apps.inventory.services import receive_stock
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class DirectSaleLotTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org DSLot', timezone='UTC', tax_rate=Decimal('0'))
        self.admin = User.objects.create_user(
            username='adm_dslot', password='pass1234!', organization=self.org, role='ADMIN')
        self.owner = Owner.objects.create(name='Cliente DS', phone='5550000010', organization=self.org)
        self.product = Product.objects.create(
            name='Vacuna Rabia', internal_code='V-DS', organization=self.org,
            base_unit='vial', tracks_lots=True, manufacturer='Zoetis')
        self.presentation = Presentation.objects.create(
            product=self.product, name='Vial', base_unit='vial', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('120.00'),
            stock=Decimal('0'), organization=self.org)
        today = timezone.localdate()
        with transaction.atomic():
            receive_stock(
                self.presentation,
                lots=[{'lot_number': 'FAR', 'expiry_date': today + timedelta(days=400), 'quantity': Decimal('10')}],
                organization=self.org, created_by=self.admin)
        self.far = StockLot.objects.get(product=self.product, lot_number='FAR')

    def _invoice_with_lot_item(self, qty):
        inv = Invoice.objects.create(
            owner=self.owner, organization=self.org, status='draft', invoice_type='direct_sale')
        InvoiceItem.objects.create(
            invoice=inv, presentation=self.presentation, description=str(self.presentation),
            quantity=qty, unit_price=self.presentation.sale_price, organization=self.org, lot=self.far)
        return inv

    def test_confirm_decrements_item_lot(self):
        inv = self._invoice_with_lot_item(Decimal('2'))
        confirm_invoice(inv, self.admin)
        self.far.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('8'))
        self.assertEqual(self.product.stock_quantity, Decimal('8'))

    def test_cancel_reverts_to_item_lot(self):
        inv = self._invoice_with_lot_item(Decimal('3'))
        confirm_invoice(inv, self.admin)
        self.far.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('7'))
        cancel_invoice(inv, self.admin)
        self.far.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(self.far.quantity_on_hand, Decimal('10'))  # reverso al mismo lote (P4)
        self.assertEqual(self.product.stock_quantity, Decimal('10'))
