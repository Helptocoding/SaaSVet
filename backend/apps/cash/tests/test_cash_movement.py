"""
Tests de movimientos manuales de caja (ADR p39): entrada / retiro / gasto.

Cubre: registro vía service (validaciones, caja requerida), efecto en el
cierre Z (manual_in/manual_out, snapshot v3), rechazo tras cierre, API
(crear/listar, cross-tenant) y CHECK constraint amount > 0.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import Service
from apps.billing.tests.factories import build_direct_sale_checkout, pay_checkout_for_test
from apps.cash.models import CashMovement
from apps.cash.services import (
    close_cash_session,
    open_cash_session,
    register_cash_movement,
)
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class CashMovementServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Mov Org", timezone="UTC")
        cls.user = User.objects.create_user(
            username="mov_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.owner = Owner.objects.create(name="Mov Owner", phone="5551113000", organization=cls.org)
        cls.pet = Pet.objects.create(name="Mov Pet", species="dog", owner=cls.owner, organization=cls.org)
        cls.service = Service.objects.create(name="Mov Svc", base_price=Decimal("3000.00"), organization=cls.org)

    def _paid_cash_sale(self):
        checkout = build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.user, service=self.service,
        )
        return pay_checkout_for_test(checkout, user=self.user, payment_method='cash')

    # --- registro ---------------------------------------------------------

    def test_register_requires_open_session(self):
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'withdrawal', Decimal("100.00"), "Retiro banco")

    def test_register_creates_movement(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        m = register_cash_movement(self.user, 'deposit', Decimal("50.00"), "Fondo extra")
        self.assertEqual(m.cash_session_id, s.pk)
        self.assertEqual(m.movement_type, 'deposit')
        self.assertEqual(m.amount, Decimal("50.00"))
        self.assertEqual(m.actor_id, self.user.pk)
        self.assertIsNotNone(m.occurred_at)

    def test_register_validations(self):
        open_cash_session(self.user, opening_float=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'invalid_type', Decimal("10.00"), "x")
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'expense', Decimal("0.00"), "x")
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'expense', Decimal("-5.00"), "x")
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'expense', Decimal("10.00"), "   ")

    def test_register_after_close_rejected(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        close_cash_session(s, user=self.user, counted_cash=Decimal("0.00"))
        with self.assertRaises(ValidationError):
            register_cash_movement(self.user, 'withdrawal', Decimal("10.00"), "Tarde")

    def test_check_blocks_non_positive_amount(self):
        s = open_cash_session(self.user, opening_float=Decimal("0.00"))
        # save() valida el constraint vía full_clean (ValidationError)…
        with self.assertRaises(ValidationError):
            CashMovement.all_objects.create(
                organization=self.org, cash_session=s, movement_type='expense',
                amount=Decimal("0.00"), reason="x",
                occurred_at=timezone.now(), actor=self.user,
            )
        # …y el CHECK en DB bloquea aunque se bypasse save() (bulk_create).
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashMovement.all_objects.bulk_create([CashMovement(
                    organization=self.org, cash_session=s, movement_type='expense',
                    amount=Decimal("0.00"), reason="x",
                    occurred_at=timezone.now(), actor=self.user,
                )])

    # --- cierre Z ---------------------------------------------------------

    def test_close_includes_movements_in_expected(self):
        """Escenario de la auditoría: 1000 fondo + 3000 ventas − 2000 retiro = 2000."""
        s = open_cash_session(self.user, opening_float=Decimal("1000.00"))
        self._paid_cash_sale()  # +3000 efectivo
        register_cash_movement(self.user, 'withdrawal', Decimal("2000.00"), "Depósito a banco")
        closed = close_cash_session(s, user=self.user, counted_cash=Decimal("2000.00"))
        self.assertEqual(closed.expected_cash, Decimal("2000.00"))
        self.assertEqual(closed.difference, Decimal("0.00"))
        snap = closed.closed_snapshot
        self.assertEqual(snap['report_schema_version'], 3)
        self.assertEqual(snap['manual_in'], '0.00')
        self.assertEqual(snap['manual_out'], '2000.00')
        self.assertEqual(snap['movements_by_type'], {'withdrawal': '2000.00'})
        self.assertEqual(snap['movements_count'], 1)

    def test_close_mixes_deposit_and_expense(self):
        s = open_cash_session(self.user, opening_float=Decimal("100.00"))
        register_cash_movement(self.user, 'deposit', Decimal("200.00"), "Cambio extra")
        register_cash_movement(self.user, 'expense', Decimal("50.00"), "Garrafón de agua")
        closed = close_cash_session(s, user=self.user, counted_cash=Decimal("250.00"))
        # 100 + 200 - 50 = 250
        self.assertEqual(closed.expected_cash, Decimal("250.00"))
        self.assertEqual(closed.difference, Decimal("0.00"))
        self.assertEqual(closed.closed_snapshot['manual_in'], '200.00')
        self.assertEqual(closed.closed_snapshot['manual_out'], '50.00')


class CashMovementAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Mov API Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="mov_api_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.other_org = Organization.objects.create(name="Mov Other Org", timezone="UTC")
        cls.other_admin = User.objects.create_user(
            username="mov_other_admin", password="x", organization=cls.other_org, role="ADMIN",
        )

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _open(self):
        return open_cash_session(self.admin, opening_float=Decimal("0.00"))

    def test_create_movement(self):
        self._open()
        res = self.client.post('/api/cash/movements/', {
            'movement_type': 'withdrawal', 'amount': '300.00', 'reason': 'Retiro banco',
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['movement_type'], 'withdrawal')
        self.assertEqual(res.data['amount'], '300.00')
        self.assertEqual(res.data['reason'], 'Retiro banco')

    def test_create_without_session_400(self):
        res = self.client.post('/api/cash/movements/', {
            'movement_type': 'expense', 'amount': '10.00', 'reason': 'Café',
        })
        self.assertEqual(res.status_code, 400)

    def test_list_current_session_movements(self):
        self._open()
        self.client.post('/api/cash/movements/', {
            'movement_type': 'deposit', 'amount': '20.00', 'reason': 'Fondo',
        })
        res = self.client.get('/api/cash/movements/')
        self.assertEqual(res.status_code, 200)
        data = res.data if isinstance(res.data, list) else res.data.get('results', [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['movement_type'], 'deposit')

    def test_list_by_session_cross_tenant_404(self):
        session = self._open()
        self.client.force_authenticate(self.other_admin)
        res = self.client.get('/api/cash/movements/', {'session': str(session.public_id)})
        self.assertEqual(res.status_code, 404)
