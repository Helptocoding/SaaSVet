"""
ADR p29 — dual-expose de revenue net-of-refunds en el dashboard financiero.

Invariante CI: revenue_paid_net == revenue_paid (gross) + Σ MetricAdjustment del
día. El gross NO cambia (dual-window; charts migran a net tras validación).
"""
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.billing.models import InvoiceItem, Service
from apps.billing.services import process_refund
from apps.billing.tests.factories import build_direct_sale_checkout, pay_checkout_for_test
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    out = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        out[name] = role
    return out


class RevenueNetTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Net Org", timezone="UTC")
        cls.admin = User.objects.create_user(username="net_admin", password="x", organization=cls.org, role="ADMIN")
        roles = _seed_roles(cls.org)
        UserRole.objects.get_or_create(user=cls.admin, role=roles["ADMIN"])
        cls.owner = Owner.objects.create(name="O", phone="5551117000", organization=cls.org)
        cls.pet = Pet.objects.create(name="P", species="dog", owner=cls.owner, organization=cls.org)
        cls.service = Service.objects.create(name="Svc", base_price=Decimal("100.00"), organization=cls.org)

    def test_revenue_net_equals_gross_plus_adjustments(self):
        # Venta pagada hoy → today.revenue_paid (gross) = 100.
        checkout = build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.admin, service=self.service,
        )
        inv = pay_checkout_for_test(checkout, user=self.admin, payment_method='cash')

        # Reembolso parcial de 30 hoy → MetricAdjustment(-30) en revenue_paid de hoy.
        item = InvoiceItem.all_objects.filter(invoice=inv).first()
        process_refund(
            inv, user=self.admin,
            credit_lines=[{'invoice_item': item.pk, 'quantity': '1', 'amount': '30.00', 'disposition': 'discard'}],
            refund_lines=[{'method': 'cash', 'amount': '30.00'}],
            reason_code='pricing_error',
            idempotency_key='revenue-net-refund',
        )

        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/v1/dashboard/financial/series/?include_today=true')
        self.assertEqual(r.status_code, 200, msg=r.data)
        today = r.data['today']
        self.assertIsNotNone(today)
        m = today['metrics']
        gross = Decimal(m['revenue_paid'])        # legacy, sin cambio
        net = Decimal(m['revenue_paid_net'])       # nuevo (dual-expose)
        self.assertEqual(gross, Decimal("100.00"))
        # Invariante: net == gross + Σ adjustments (= 100 − 30).
        self.assertEqual(net, gross - Decimal("30.00"))
        self.assertEqual(net, Decimal("70.00"))

    def test_revenue_net_present_without_refunds_equals_gross(self):
        checkout = build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.admin, service=self.service,
        )
        pay_checkout_for_test(checkout, user=self.admin, payment_method='cash')

        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/v1/dashboard/financial/series/?include_today=true')
        self.assertEqual(r.status_code, 200, msg=r.data)
        m = r.data['today']['metrics']
        # Sin ajustes: net == gross.
        self.assertEqual(Decimal(m['revenue_paid_net']), Decimal(m['revenue_paid']))
