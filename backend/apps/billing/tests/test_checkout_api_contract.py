import uuid
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.billing.checkout_services import add_checkout_item, create_direct_sale_checkout, post_checkout
from apps.billing.models import Checkout, Invoice, Service
from apps.billing.serializers import InvoiceItemSerializer, InvoiceSerializer
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class CheckoutApiContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='API Checkout', timezone='UTC')
        cls.other_org = Organization.objects.create(name='API Other', timezone='UTC')
        cls.admin = User.objects.create_user(
            username='api-checkout-admin', password='x', organization=cls.org, role='ADMIN',
        )
        cls.vet = User.objects.create_user(
            username='api-checkout-vet', password='x', organization=cls.org, role='VET',
        )
        cls.owner = Owner.objects.create(
            name='API Owner', phone='5551110000', organization=cls.org,
        )
        cls.other_owner = Owner.objects.create(
            name='Other Owner', phone='5552220000', organization=cls.other_org,
        )
        cls.service = Service.objects.create(
            name='API Service', base_price=Decimal('80.00'), organization=cls.org,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_invoice_collection_is_read_only(self):
        response = self.client.post('/api/billing/invoices/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_invoice_detail_is_read_only(self):
        for method in ('patch', 'put', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    f'/api/billing/invoices/{uuid.uuid4()}/', {'notes': 'x'}, format='json')
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_checkout_creation_is_tenant_scoped(self):
        response = self.client.post('/api/billing/checkouts/direct-sale/', {
            'owner': str(self.other_owner.public_id),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Checkout.objects.filter(organization=self.org).exists())

    def test_checkout_detail_cannot_cross_tenants(self):
        foreign_user = User.objects.create_user(
            username='foreign-checkout-admin', password='x',
            organization=self.other_org, role='ADMIN',
        )
        foreign = create_direct_sale_checkout(
            organization=self.other_org, customer=self.other_owner,
            pet=None, user=foreign_user,
        )
        response = self.client.get(f'/api/billing/checkouts/{foreign.public_id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_checkout_detail_exposes_derived_readiness_and_actions(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.admin,
        )
        empty = self.client.get(f'/api/billing/checkouts/{checkout.public_id}/')
        self.assertEqual(empty.status_code, status.HTTP_200_OK)
        self.assertFalse(empty.data['preparation_readiness']['ready'])
        self.assertIn(
            'empty_checkout',
            {row['code'] for row in empty.data['preparation_readiness']['blockers']},
        )
        self.assertTrue(empty.data['actions']['abandon']['allowed'])

        add_checkout_item(checkout, self.admin, service=self.service)
        ready = self.client.get(f'/api/billing/checkouts/{checkout.public_id}/')
        self.assertEqual(ready.status_code, status.HTTP_200_OK)
        self.assertTrue(ready.data['preparation_readiness']['ready'])
        self.assertTrue(ready.data['actions']['pay']['allowed'])
        self.assertFalse(ready.data['actions']['post_unpaid']['allowed'])
        self.assertIn(
            'credit_disabled',
            {row['code'] for row in ready.data['actions']['post_unpaid']['blockers']},
        )
        self.assertIn(
            'payment_lines',
            {row['name'] for row in ready.data['actions']['pay']['required_inputs']},
        )

    def test_version_conflict_is_reported_without_financial_side_effect(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.admin,
        )
        add_checkout_item(checkout, self.admin, service=self.service)
        checkout.refresh_from_db()
        response = self.client.post(
            f'/api/billing/checkouts/{checkout.public_id}/pay/',
            {'payment_method': 'cash', 'expected_version': checkout.version - 1},
            format='json', HTTP_X_IDEMPOTENCY_KEY='api-stale-version',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(Invoice.objects.exists())

    def test_vet_cannot_collect_but_admin_can(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.admin,
        )
        add_checkout_item(checkout, self.admin, service=self.service)
        checkout.refresh_from_db()
        self.client.force_authenticate(self.vet)
        denied = self.client.post(
            f'/api/billing/checkouts/{checkout.public_id}/pay/',
            {'payment_method': 'cash', 'expected_version': checkout.version},
            format='json', HTTP_X_IDEMPOTENCY_KEY='vet-cannot-pay',
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.admin)
        paid = self.client.post(
            f'/api/billing/checkouts/{checkout.public_id}/pay/',
            {'payment_method': 'cash', 'expected_version': checkout.version},
            format='json', HTTP_X_IDEMPOTENCY_KEY='admin-can-pay',
        )
        self.assertEqual(paid.status_code, status.HTTP_201_CREATED, paid.data)
        self.assertEqual(paid.data['status'], 'paid')

    def test_invoice_detail_rejects_patch_after_post(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.admin,
        )
        add_checkout_item(checkout, self.admin, service=self.service)
        checkout.refresh_from_db()
        invoice = post_checkout(
            checkout, self.admin, payment_method='cash',
            expected_version=checkout.version, idempotency_key='api-paid-document',
        )
        response = self.client.patch(
            f'/api/billing/invoices/{invoice.public_id}/', {'notes': 'rewrite'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class InvoiceSerializersAreReadOnly(SimpleTestCase):
    """C2 (orden 6): las Invoice nacen al postear un Checkout (ADR p62). Sus
    serializers solo proyectan; no puede volver a ellos validación de escritura."""

    def test_no_field_is_writable(self):
        for serializer_class in (InvoiceSerializer, InvoiceItemSerializer):
            with self.subTest(serializer=serializer_class.__name__):
                writable = [name for name, field in serializer_class().fields.items()
                            if not field.read_only]
                self.assertEqual(writable, [])

    def test_no_write_validation_is_declared(self):
        for serializer_class in (InvoiceSerializer, InvoiceItemSerializer):
            with self.subTest(serializer=serializer_class.__name__):
                declared = [name for name in vars(serializer_class)
                            if name == 'validate' or name.startswith('validate_')]
                self.assertEqual(declared, [])
