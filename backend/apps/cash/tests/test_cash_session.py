"""
Tests de turno de caja / cierre Z (ADR p28).

Cubre: apertura, doble-apertura bloqueada, cálculo del Z (expected/counted/
difference), efectivo vs tarjeta, snapshot legal congelado, CHECK del anchor
closed_at, y la integración con el flujo de pago (require_open_cash_session:
rechazo sin caja, attach del cash_session, rechazo tras cierre).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.billing.models import Payment, Service
from apps.billing.tests.factories import build_direct_sale_checkout, pay_checkout_for_test
from apps.cash.models import CashSession
from apps.cash.services import close_cash_session, get_open_session, open_cash_session
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class CashSessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Caja Org", timezone="UTC")
        cls.user = User.objects.create_user(
            username="caja_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.owner = Owner.objects.create(name="Caja Owner", phone="5551112000", organization=cls.org)
        cls.pet = Pet.objects.create(name="Caja Pet", species="dog", owner=cls.owner, organization=cls.org)
        cls.service = Service.objects.create(name="Caja Svc", base_price=Decimal("100.00"), organization=cls.org)

    def _enable_required_cash(self):
        s = self.org.settings
        s.require_open_cash_session = True
        s.save()

    def _open_direct_sale(self):
        return build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.user, service=self.service,
        )

    # --- apertura -------------------------------------------------------------

    def test_open_creates_session(self):
        s = open_cash_session(self.user, opening_float=Decimal("500.00"))
        self.assertEqual(s.status, 'open')
        self.assertEqual(s.opening_float, Decimal("500.00"))
        self.assertEqual(get_open_session(self.user).pk, s.pk)

    def test_double_open_blocked(self):
        open_cash_session(self.user, opening_float=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            open_cash_session(self.user, opening_float=Decimal("0.00"))

    # --- cierre Z -------------------------------------------------------------

    def test_close_computes_expected_and_difference(self):
        s = open_cash_session(self.user, opening_float=Decimal("500.00"))
        self._enable_required_cash()
        checkout = self._open_direct_sale()  # total 100
        pay_checkout_for_test(checkout, user=self.user, payment_method='cash')
        closed = close_cash_session(s, user=self.user, counted_cash=Decimal("590.00"))
        self.assertEqual(closed.status, 'closed')
        self.assertEqual(closed.expected_cash, Decimal("600.00"))   # 500 + 100 cash
        self.assertEqual(closed.counted_cash, Decimal("590.00"))
        self.assertEqual(closed.difference, Decimal("-10.00"))
        self.assertIsNotNone(closed.closed_at)
        self.assertEqual(closed.closed_snapshot['report_schema_version'], 3)
        self.assertEqual(closed.closed_snapshot['operations'], 1)

    def test_card_payment_not_counted_in_cash(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        self._enable_required_cash()
        checkout = self._open_direct_sale()
        pay_checkout_for_test(checkout, user=self.user, payment_lines=[{'method': 'card', 'amount': '100.00'}])
        closed = close_cash_session(s, user=self.user, counted_cash=Decimal("0.00"))
        self.assertEqual(closed.expected_cash, Decimal("0.00"))  # tarjeta no es efectivo
        self.assertEqual(closed.difference, Decimal("0.00"))
        self.assertEqual(closed.closed_snapshot['totals_by_method'].get('card'), '100.00')

    def test_close_already_closed_rejected(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        close_cash_session(s, user=self.user, counted_cash=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            close_cash_session(s, user=self.user, counted_cash=Decimal("0.00"))

    def test_check_blocks_closed_without_closed_at(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.all_objects.filter(pk=s.pk).update(status='closed', closed_at=None)

    # --- integración con el flujo de pago -------------------------------------

    def test_pay_requires_open_session_when_enabled(self):
        self._enable_required_cash()
        checkout = self._open_direct_sale()
        with self.assertRaises(ValidationError):
            pay_checkout_for_test(checkout, user=self.user, payment_method='cash')
        checkout.refresh_from_db()
        self.assertEqual(checkout.lifecycle, 'open')  # nada cobrado

    def test_pay_after_close_rejected_when_enabled(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        self._enable_required_cash()
        close_cash_session(s, user=self.user, counted_cash=Decimal("0.00"))
        checkout = self._open_direct_sale()
        with self.assertRaises(ValidationError):
            pay_checkout_for_test(checkout, user=self.user, payment_method='cash')

    def test_pay_attaches_cash_session_when_enabled(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        self._enable_required_cash()
        checkout = self._open_direct_sale()
        invoice = pay_checkout_for_test(checkout, user=self.user, payment_method='cash')
        p = Payment.all_objects.filter(invoice=invoice).first()
        self.assertEqual(p.cash_session_id, s.pk)

    def test_toggle_off_pay_without_session(self):
        # default toggle off → cobro sin caja permitido; Payment.cash_session NULL.
        checkout = self._open_direct_sale()
        invoice = pay_checkout_for_test(checkout, user=self.user, payment_method='cash')
        self.assertEqual(invoice.status, 'paid')
        p = Payment.all_objects.filter(invoice=invoice).first()
        self.assertIsNone(p.cash_session_id)

    def test_pay_attaches_session_even_when_toggle_off(self):
        # ADR p39: asociación ≠ obligatoriedad. Con caja abierta el pago se
        # asocia SIEMPRE, aunque el toggle esté apagado (antes quedaba NULL y
        # el Z reportaba $0 ventas → diferencias falsas).
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        checkout = self._open_direct_sale()
        invoice = pay_checkout_for_test(checkout, user=self.user, payment_method='cash')
        p = Payment.all_objects.filter(invoice=invoice).first()
        self.assertEqual(p.cash_session_id, s.pk)
        closed = close_cash_session(s, user=self.user, counted_cash=Decimal("100.00"))
        self.assertEqual(closed.expected_cash, Decimal("100.00"))
        self.assertEqual(closed.difference, Decimal("0.00"))


class CashSessionAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Caja API Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="caja_api_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.other_org = Organization.objects.create(name="Caja Other Org", timezone="UTC")
        cls.other_admin = User.objects.create_user(
            username="caja_other_admin", password="x", organization=cls.other_org, role="ADMIN",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_open_then_current(self):
        r = self.client.post('/api/cash/sessions/open/', {'opening_float': '300.00'}, format='json')
        self.assertEqual(r.status_code, 201, msg=r.data)
        self.assertEqual(r.data['status'], 'open')
        pid = r.data['public_id']
        rc = self.client.get('/api/cash/sessions/current/')
        self.assertEqual(rc.status_code, 200)
        self.assertEqual(rc.data['public_id'], pid)

    def test_double_open_returns_400(self):
        self.client.post('/api/cash/sessions/open/', {'opening_float': '0'}, format='json')
        r = self.client.post('/api/cash/sessions/open/', {'opening_float': '0'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_close_flow(self):
        r = self.client.post('/api/cash/sessions/open/', {'opening_float': '100.00'}, format='json')
        pid = r.data['public_id']
        rc = self.client.post(f'/api/cash/sessions/{pid}/close/', {'counted_cash': '100.00'}, format='json')
        self.assertEqual(rc.status_code, 200, msg=rc.data)
        self.assertEqual(rc.data['status'], 'closed')
        self.assertEqual(rc.data['difference'], '0.00')

    def test_close_requires_counted_cash(self):
        r = self.client.post('/api/cash/sessions/open/', {'opening_float': '0'}, format='json')
        pid = r.data['public_id']
        rc = self.client.post(f'/api/cash/sessions/{pid}/close/', {}, format='json')
        self.assertEqual(rc.status_code, 400)

    def test_current_when_none(self):
        r = self.client.get('/api/cash/sessions/current/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data.get('session'))

    def test_cross_tenant_close_returns_404(self):
        r = self.client.post('/api/cash/sessions/open/', {'opening_float': '0'}, format='json')
        pid = r.data['public_id']
        self.client.force_authenticate(self.other_admin)
        rc = self.client.post(f'/api/cash/sessions/{pid}/close/', {'counted_cash': '0'}, format='json')
        self.assertEqual(rc.status_code, 404)

    def test_list_ok(self):
        self.client.post('/api/cash/sessions/open/', {'opening_float': '0'}, format='json')
        r = self.client.get('/api/cash/sessions/')
        self.assertEqual(r.status_code, 200)
