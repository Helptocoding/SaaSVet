"""
Concurrencia de caja (ADR p28) — Postgres + threads.

Verifica el invariante crítico: con `require_open_cash_session` activo, un pago
en vuelo y el cierre Z se serializan en el lock de la CashSession (cabeza del
orden global). Resultado: o el pago se cuenta en el Z, o se rechaza — NUNCA un
"pago fantasma" que entre al turno después del conteo.

No reordenar el lock de CashSession sin volver a correr esta suite.
"""
import threading
from decimal import Decimal

from django.db import close_old_connections
from django.db.models import Sum
from django.test import TransactionTestCase

from apps.billing.models import Invoice, Payment, Service
from apps.billing.tests.factories import build_direct_sale_checkout, pay_checkout_for_test
from apps.cash.services import close_cash_session, open_cash_session
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={'is_system_role': True},
        )
        role.permissions.set(
            [wildcard] if '*.*' in codes else [perms_map[c] for c in codes if c in perms_map]
        )


class CashSessionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.org = Organization.objects.create(name='Caja Conc', timezone='UTC')  # tax_rate default 0
        _seed_roles(self.org)
        self.admin = User.objects.create_user(
            username='caja_conc_admin', password='pass1234!', organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.admin, role=Role.objects.get(name='ADMIN', organization=self.org))
        # Requiere caja abierta para cobrar.
        s = self.org.settings
        s.require_open_cash_session = True
        s.save()
        self.owner = Owner.objects.create(name='Owner Conc', phone='5551230000', organization=self.org)
        self.pet = Pet.objects.create(name='Pet Conc', species='dog', owner=self.owner, organization=self.org)
        self.service = Service.objects.create(name='Svc Conc', base_price=Decimal('100.00'), organization=self.org)

    def _run_parallel(self, functions):
        barrier = threading.Barrier(len(functions))
        results = []

        def worker(name, fn):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                fn()
                results.append((name, 'ok'))
            except Exception as exc:
                results.append((name, exc))
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker, args=(n, f)) for n, f in functions]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        return results

    def _open_direct_sale(self):
        return build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.admin, service=self.service,
        )

    def test_close_vs_pay_no_phantom_payment(self):
        session = open_cash_session(self.admin, opening_float=Decimal('0.00'))
        checkout = self._open_direct_sale()  # total 100 (tax 0)

        self._run_parallel([
            ('close', lambda: close_cash_session(session, self.admin, counted_cash=Decimal('0.00'))),
            ('pay', lambda: pay_checkout_for_test(
                checkout, user=self.admin, payment_method='cash', idempotency_key='cash-race',
            )),
        ])

        session.refresh_from_db()
        checkout.refresh_from_db()
        self.assertIn(session.status, ('closed', 'force_closed'))

        cash_attached = (
            Payment.all_objects.filter(cash_session=session, method='cash')
            .aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        )
        # Invariante: lo que el Z esperó en efectivo == lo realmente atado al turno.
        # Si un pago se colara tras el conteo, esta igualdad se rompería.
        self.assertEqual(session.expected_cash - session.opening_float, cash_attached)

        # XOR: o se emitió la factura pagada (su pago fue contado) o el Checkout
        # sigue abierto porque el cobro fue rechazado por caja cerrada.
        invoice = Invoice.all_objects.filter(checkout=checkout).first()
        if invoice is not None:
            self.assertEqual(invoice.status, 'paid')
            self.assertEqual(cash_attached, invoice.total)
        else:
            self.assertEqual(checkout.lifecycle, 'open')
            self.assertEqual(cash_attached, Decimal('0.00'))
