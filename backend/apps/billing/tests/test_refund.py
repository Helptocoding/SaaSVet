"""
Tests de devoluciones / notas de crédito (ADR p29 — Sprint B).

process_refund: nota de crédito + reembolso sobre factura pagada; restock vs
discard; MetricAdjustment negativo (dual-window, snapshot frozen intacto);
over-refund bloqueado; idempotencia; RBAC billing.refund.
La factura original permanece `paid` (contrato §8.2).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from rest_framework.test import APITestCase

from apps.analytics.models import MetricAdjustment
from apps.billing.models import (
    CreditNote, CreditNoteItem, Invoice, InvoiceItem, Payment,
    RefundPayment, RefundReversal, Service,
)
from apps.billing.services import pay_direct_sale, process_refund, reverse_credit_note
from apps.inventory.models import Presentation, Product
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class RefundServiceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Refund Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="refund_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.owner = Owner.objects.create(name="Refund Owner", phone="5551115000", organization=cls.org)
        cls.pet = Pet.objects.create(name="Refund Pet", species="dog", owner=cls.owner, organization=cls.org)
        cls.product = Product.objects.create(
            name="Producto", internal_code="RF-001", category="food", organization=cls.org,
        )
        cls.pres = Presentation.objects.create(
            product=cls.product, name="Bolsa", base_unit="bag",
            stock=Decimal("10"), sale_price=Decimal("80.00"), organization=cls.org,
        )
        # ADR p31: Product.stock_quantity es la fuente autoritativa
        # (conv_factor=1 → stock_qty = pres.stock).
        Product.objects.filter(pk=cls.product.pk).update(
            base_unit='bag', stock_quantity=Decimal('10'),
        )

    def _paid_invoice_with_product(self, qty="1"):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )
        InvoiceItem.objects.create(
            invoice=inv, presentation=self.pres, description=str(self.pres),
            quantity=Decimal(qty), unit_price=self.pres.sale_price, organization=self.org,
        )
        pay_direct_sale(inv, user=self.admin, payment_method='cash')
        inv.refresh_from_db()
        return inv

    def _item(self, inv):
        return InvoiceItem.all_objects.filter(invoice=inv).first()

    def test_full_refund_restock(self):
        inv = self._paid_invoice_with_product()  # total 80, stock 10→9
        item = self._item(inv)
        self.pres.refresh_from_db()
        stock_after_sale = self.pres.stock  # 9
        cn = process_refund(
            inv, user=self.admin,
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'restock'}],
            refund_lines=[{'method': 'cash', 'amount': '80.00'}],
            reason_code='customer_return',
        )
        inv.refresh_from_db()
        self.pres.refresh_from_db()
        self.assertEqual(inv.status, 'paid')  # NO reabre
        self.assertEqual(cn.total_refunded, Decimal("80.00"))
        self.assertEqual(CreditNoteItem.all_objects.filter(credit_note=cn).count(), 1)
        self.assertEqual(RefundPayment.all_objects.filter(credit_note=cn).count(), 1)
        self.assertEqual(self.pres.stock, stock_after_sale + Decimal("1"))  # restock
        adj = MetricAdjustment.all_objects.filter(organization=self.org, metric_name='revenue_paid')
        self.assertEqual(adj.count(), 1)
        self.assertEqual(adj.first().delta, Decimal("-80.00"))

    def test_discard_no_restock(self):
        inv = self._paid_invoice_with_product()
        item = self._item(inv)
        self.pres.refresh_from_db()
        stock_after_sale = self.pres.stock
        process_refund(
            inv, user=self.admin,
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'discard'}],
            refund_lines=[{'method': 'cash', 'amount': '80.00'}],
            reason_code='damaged_product',
        )
        self.pres.refresh_from_db()
        self.assertEqual(self.pres.stock, stock_after_sale)  # descartado, sin restock
        # dinero igual se devolvió
        self.assertEqual(MetricAdjustment.all_objects.filter(organization=self.org).first().delta, Decimal("-80.00"))

    def test_partial_then_over_refund_blocked(self):
        inv = self._paid_invoice_with_product(qty="2")  # 2 × 80 = 160
        item = self._item(inv)
        process_refund(
            inv, user=self.admin,
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'restock'}],
            refund_lines=[{'method': 'cash', 'amount': '80.00'}],
            reason_code='customer_return',
        )
        # segunda devolución de 2 más excede lo disponible (solo queda 1)
        with self.assertRaises(ValidationError):
            process_refund(
                inv, user=self.admin,
                credit_lines=[{'invoice_item': item.pk, 'quantity': '2', 'amount': '160.00', 'disposition': 'restock'}],
                refund_lines=[{'method': 'cash', 'amount': '160.00'}],
                reason_code='customer_return',
            )

    def test_refund_sum_must_equal_total(self):
        inv = self._paid_invoice_with_product()
        item = self._item(inv)
        with self.assertRaises(ValidationError):
            process_refund(
                inv, user=self.admin,
                credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'restock'}],
                refund_lines=[{'method': 'cash', 'amount': '50.00'}],  # ≠ 80
                reason_code='customer_return',
            )

    def test_refund_non_paid_rejected(self):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )
        with self.assertRaises(ValidationError):
            process_refund(
                inv, user=self.admin,
                credit_lines=[{'invoice_item': 1, 'quantity': '1', 'amount': '1.00'}],
                refund_lines=[{'method': 'cash', 'amount': '1.00'}],
                reason_code='customer_return',
            )

    def test_invalid_reason_code_rejected(self):
        inv = self._paid_invoice_with_product()
        item = self._item(inv)
        with self.assertRaises(ValidationError):
            process_refund(
                inv, user=self.admin,
                credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00'}],
                refund_lines=[{'method': 'cash', 'amount': '80.00'}],
                reason_code='no_existe',
            )

    def test_idempotent_replay(self):
        inv = self._paid_invoice_with_product()
        item = self._item(inv)
        kw = dict(
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'discard'}],
            refund_lines=[{'method': 'cash', 'amount': '80.00'}],
            reason_code='customer_return', idempotency_key='ref-1',
        )
        process_refund(inv, user=self.admin, **kw)
        process_refund(inv, user=self.admin, **kw)  # replay
        self.assertEqual(CreditNote.all_objects.filter(original_invoice=inv).count(), 1)
        self.assertEqual(RefundPayment.all_objects.filter(organization=self.org).count(), 1)

    def _credit_note(self, inv):
        item = self._item(inv)
        return process_refund(
            inv, user=self.admin,
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '80.00', 'disposition': 'discard'}],
            refund_lines=[{'method': 'cash', 'amount': '80.00'}],
            reason_code='customer_return',
        )

    def test_reverse_credit_note_cancels_adjustment(self):
        inv = self._paid_invoice_with_product()
        cn = self._credit_note(inv)
        reverse_credit_note(cn, user=self.admin, reason_code='other', reason_notes='error de cajero')
        self.assertEqual(RefundReversal.all_objects.filter(reverses__credit_note=cn).count(), 1)
        # Neto del día vuelve a 0: -80 (refund) + 80 (reversal).
        net = MetricAdjustment.all_objects.filter(
            organization=self.org, metric_name='revenue_paid',
        ).aggregate(t=Sum('delta'))['t']
        self.assertEqual(net, Decimal("0.00"))

    def test_reverse_twice_blocked(self):
        inv = self._paid_invoice_with_product()
        cn = self._credit_note(inv)
        reverse_credit_note(cn, user=self.admin, reason_code='other')
        with self.assertRaises(ValidationError):
            reverse_credit_note(cn, user=self.admin, reason_code='other')


class RefundAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Refund API Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="rf_api_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.vet = User.objects.create_user(
            username="rf_api_vet", password="x", organization=cls.org, role="VET",
        )
        cls.owner = Owner.objects.create(name="O", phone="5551116000", organization=cls.org)
        cls.pet = Pet.objects.create(name="P", species="dog", owner=cls.owner, organization=cls.org)
        cls.service = Service.objects.create(name="Svc", base_price=Decimal("100.00"), organization=cls.org)

    def _paid_invoice(self):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )
        InvoiceItem.objects.create(
            invoice=inv, service=self.service, description=self.service.name,
            quantity=Decimal("1"), unit_price=self.service.base_price, organization=self.org,
        )
        pay_direct_sale(inv, user=self.admin, payment_method='cash')
        inv.refresh_from_db()
        return inv

    def test_admin_can_refund_via_api(self):
        self.client.force_authenticate(self.admin)
        inv = self._paid_invoice()
        item = InvoiceItem.all_objects.filter(invoice=inv).first()
        r = self.client.post(f'/api/billing/invoices/{inv.public_id}/refund/', {
            'credit_lines': [{'invoice_item': item.pk, 'quantity': '1', 'amount': '100.00', 'disposition': 'restock'}],
            'refund_lines': [{'method': 'cash', 'amount': '100.00'}],
            'reason_code': 'customer_return',
        }, format='json')
        self.assertEqual(r.status_code, 201, msg=r.data)
        self.assertEqual(r.data['total_refunded'], '100.00')
        self.assertIn('public_id', r.data)

    def test_vet_cannot_refund_returns_403(self):
        self.client.force_authenticate(self.vet)
        inv = self._paid_invoice()
        item = InvoiceItem.all_objects.filter(invoice=inv).first()
        r = self.client.post(f'/api/billing/invoices/{inv.public_id}/refund/', {
            'credit_lines': [{'invoice_item': item.pk, 'quantity': '1', 'amount': '100.00'}],
            'refund_lines': [{'method': 'cash', 'amount': '100.00'}],
            'reason_code': 'customer_return',
        }, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(CreditNote.all_objects.filter(original_invoice=inv).count(), 0)
