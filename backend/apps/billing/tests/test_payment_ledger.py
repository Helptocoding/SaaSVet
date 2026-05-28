"""
Tests del ledger de pagos (ADR p27 / docs/financial-event-model-contract.md §8).

Cubre: Payment append-only, split, pago parcial, idempotencia (replay sin
doble-cobro), overpago rechazado, venta directa exige total exacto, cancelación
con pagos bloqueada, y el comando audit_payment_ledger_integrity.
"""
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceItem, Payment, Service
from apps.billing.services import (
    cancel_invoice, confirm_invoice, pay_direct_sale, pay_invoice,
)
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class PaymentLedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="PL Org", timezone="UTC")
        cls.user = User.objects.create_user(
            username="pl_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.owner = Owner.objects.create(
            name="PL Owner", phone="5551110000", organization=cls.org,
        )
        cls.pet = Pet.objects.create(
            name="PL Pet", species="dog", owner=cls.owner, organization=cls.org,
        )
        cls.service = Service.objects.create(
            name="PL Svc", base_price=Decimal("100.00"), organization=cls.org,
        )

    # --- helpers --------------------------------------------------------------

    def _draft_direct_sale(self):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )
        InvoiceItem.objects.create(
            invoice=inv, service=self.service, description=self.service.name,
            quantity=1, unit_price=self.service.base_price, organization=self.org,
        )
        inv.refresh_from_db()
        return inv

    def _confirmed_consultation(self):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='consultation',
        )
        InvoiceItem.objects.create(
            invoice=inv, service=self.service, description=self.service.name,
            quantity=1, unit_price=self.service.base_price, organization=self.org,
        )
        confirm_invoice(inv, user=self.user)
        inv.refresh_from_db()
        return inv

    # --- direct sale ----------------------------------------------------------

    def test_direct_pay_records_payment_and_marks_paid(self):
        inv = self._draft_direct_sale()
        pay_direct_sale(inv, user=self.user, payment_method='cash')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')
        self.assertEqual(inv.payment_method, 'cash')
        self.assertEqual(inv.remaining_balance, Decimal('0.00'))
        payments = Payment.all_objects.filter(invoice=inv)
        self.assertEqual(payments.count(), 1)
        p = payments.first()
        self.assertEqual(p.amount, Decimal('100.00'))
        self.assertEqual(p.provenance, 'service')
        self.assertEqual(p.actor_id, self.user.pk)

    def test_split_payment_marks_paid_method_mixed_is_null(self):
        inv = self._draft_direct_sale()  # total 100
        pay_direct_sale(inv, user=self.user, payment_lines=[
            {'method': 'cash', 'amount': '60.00'},
            {'method': 'card', 'amount': '40.00'},
        ])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')
        self.assertIsNone(inv.payment_method)  # mixto → NULL (deprecado)
        self.assertEqual(inv.remaining_balance, Decimal('0.00'))
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 2)

    def test_direct_pay_rejects_partial_amount(self):
        inv = self._draft_direct_sale()
        with self.assertRaises(ValidationError):
            pay_direct_sale(inv, user=self.user, payment_lines=[
                {'method': 'cash', 'amount': '60.00'},
            ])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'draft')  # rollback atómico
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 0)

    # --- pago parcial (consulta) ----------------------------------------------

    def test_partial_payment_keeps_confirmed_then_completes(self):
        inv = self._confirmed_consultation()  # total 100, confirmed
        pay_invoice(inv, user=self.user, payment_lines=[{'method': 'cash', 'amount': '40.00'}])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')
        self.assertEqual(inv.remaining_balance, Decimal('60.00'))
        self.assertIsNone(inv.paid_at)

        pay_invoice(inv, user=self.user, payment_lines=[{'method': 'card', 'amount': '60.00'}])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')
        self.assertEqual(inv.remaining_balance, Decimal('0.00'))
        self.assertIsNotNone(inv.paid_at)
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 2)

    def test_overpayment_rejected(self):
        inv = self._confirmed_consultation()
        with self.assertRaises(ValidationError):
            pay_invoice(inv, user=self.user, payment_lines=[{'method': 'cash', 'amount': '150.00'}])
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 0)

    # --- idempotencia ---------------------------------------------------------

    def test_idempotent_replay_does_not_double_charge_direct_sale(self):
        inv = self._draft_direct_sale()
        pay_direct_sale(inv, user=self.user, payment_method='cash', idempotency_key='abc123')
        # replay con la misma key → no-op, sin excepción, sin segundo Payment
        pay_direct_sale(inv, user=self.user, payment_method='cash', idempotency_key='abc123')
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 1)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')

    def test_idempotent_replay_pay_invoice(self):
        inv = self._confirmed_consultation()
        pay_invoice(inv, user=self.user, payment_method='cash', idempotency_key='k-1')
        pay_invoice(inv, user=self.user, payment_method='cash', idempotency_key='k-1')
        self.assertEqual(Payment.all_objects.filter(invoice=inv).count(), 1)

    # --- cancelación con pagos ------------------------------------------------

    def test_cancel_with_payments_blocked(self):
        inv = self._confirmed_consultation()
        pay_invoice(inv, user=self.user, payment_lines=[{'method': 'cash', 'amount': '40.00'}])
        with self.assertRaises(ValidationError):
            cancel_invoice(inv, user=self.user)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')  # no cancelada

    # --- comando de auditoría -------------------------------------------------

    def test_audit_command_clean(self):
        inv = self._draft_direct_sale()
        pay_direct_sale(inv, user=self.user, payment_method='cash')
        out = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command('audit_payment_ledger_integrity', '--json', stdout=out)
        self.assertEqual(cm.exception.code, 0)

    def test_audit_command_detects_paid_without_payments(self):
        inv = Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )
        InvoiceItem.objects.create(
            invoice=inv, service=self.service, description='x',
            quantity=1, unit_price=Decimal('100.00'), organization=self.org,
        )
        # Forzar paid SIN pagos (bypass simulado). Setear ambos anchors para no
        # violar los CHECK de event-authority.
        now = timezone.now()
        Invoice.all_objects.filter(pk=inv.pk).update(
            status='paid', paid_at=now, confirmed_at=now,
        )
        out = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command('audit_payment_ledger_integrity', '--json', stdout=out)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('paid_remaining_nonzero', out.getvalue())
