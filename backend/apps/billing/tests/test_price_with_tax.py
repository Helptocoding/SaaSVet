"""ADR p70 D4: el precio con IVA se calcula una sola vez, en backend.

El catálogo y las presentaciones entregan la tasa y el precio con IVA; ese
precio coincide con el total del cobro de un solo artículo, que es lo que el
agente cita al cliente.
"""
from decimal import Decimal

from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import Service
from apps.billing.money import invoice_totals, unit_price_with_tax
from apps.billing.tests.factories import build_direct_sale_checkout
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.inventory.models import Presentation, Product
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class UnitPriceWithTaxTests(SimpleTestCase):
    def test_rounding_matches_a_single_item_invoice(self):
        for amount, rate, expected in (
            ('500.00', '0.1600', '580.00'),
            ('500.00', '0.0800', '540.00'),
            ('500.00', '0.0000', '500.00'),
            ('333.33', '0.1600', '386.66'),      # 53.3328 → 53.33
            ('0.05', '0.1600', '0.06'),          # 0.008 → 0.01 (HALF_UP)
        ):
            with self.subTest(amount=amount, rate=rate):
                value = unit_price_with_tax(Decimal(amount), Decimal(rate))
                self.assertEqual(value, Decimal(expected))
                self.assertEqual(value, invoice_totals(Decimal(amount), Decimal(rate))[2])

    def test_missing_price_or_rate_is_none(self):
        self.assertIsNone(unit_price_with_tax(None, Decimal('0.16')))
        self.assertIsNone(unit_price_with_tax(Decimal('1'), None))


def _admin(org):
    perms = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    role, _ = Role.objects.get_or_create(name='ADMIN', organization=org,
                                         defaults={'is_system_role': True})
    role.permissions.set([perms[c] for c in PERMISSIONS['ADMIN']])
    user = User.objects.create_user(username=f'iva_{org.pk}', password='x',
                                    organization=org, role='ADMIN')
    UserRole.objects.get_or_create(user=user, role=role)
    return user


class PriceWithTaxApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='IVA', timezone='UTC',
                                              tax_rate=Decimal('0.1600'))
        cls.admin = _admin(cls.org)
        cls.service = Service.objects.create(organization=cls.org, name='Consulta',
                                             base_price=Decimal('500.00'))
        cls.product = Product.objects.create(organization=cls.org, name='Croqueta',
                                             internal_code='IVA-001', category='food',
                                             stock_quantity=10)
        cls.presentation = Presentation.objects.create(
            organization=cls.org, product=cls.product, name='Bolsa', base_unit='kg',
            sale_price=Decimal('250.00'), stock=10)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_service_list_exposes_rate_and_price_with_tax(self):
        r = self.client.get('/api/billing/services/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        row = next(s for s in r.data if s['public_id'] == str(self.service.public_id))
        self.assertEqual(row['base_price'], '500.00')
        self.assertEqual(row['tax_rate'], '0.1600')
        self.assertEqual(row['price_with_tax'], '580.00')

    def test_presentation_exposes_rate_and_sale_price_with_tax(self):
        r = self.client.get('/api/inventory/products/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        product = next(p for p in rows if p['public_id'] == str(self.product.public_id))
        presentation = product['presentations'][0]
        self.assertEqual(presentation['sale_price'], '250.00')
        self.assertEqual(presentation['tax_rate'], '0.1600')
        self.assertEqual(presentation['sale_price_with_tax'], '290.00')

    def test_me_exposes_the_rate_only_for_labels(self):
        r = self.client.get('/api/me/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(r.data['organization_tax_rate'], '0.1600')

    def test_the_quoted_price_equals_the_total_of_a_one_item_checkout(self):
        owner = Owner.objects.create(organization=self.org, name='Cliente', phone='5544332211')
        checkout = build_direct_sale_checkout(organization=self.org, owner=owner,
                                              user=self.admin, service=self.service)
        quoted = self.client.get('/api/billing/services/').data[0]['price_with_tax']
        self.assertEqual(Decimal(quoted), checkout.total)
