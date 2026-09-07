from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.billing.checkout_services import (
    add_checkout_item, create_direct_sale_checkout, issue_checkout_estimate, post_checkout,
)
from apps.billing.models import Service
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class CheckoutDocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Documents Org', timezone='UTC')
        cls.user = User.objects.create_user(
            username='documents-admin', password='x', organization=cls.org, role='ADMIN',
        )
        cls.owner = Owner.objects.create(
            name='Documents Owner', phone='5553330000', organization=cls.org,
        )
        cls.service = Service.objects.create(
            name='Documented Service', base_price=Decimal('75.00'), organization=cls.org,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _checkout(self):
        checkout = create_direct_sale_checkout(
            organization=self.org, customer=self.owner, pet=None, user=self.user,
        )
        add_checkout_item(checkout, self.user, service=self.service)
        checkout.refresh_from_db()
        return checkout

    def test_estimate_pdf_is_not_an_invoice(self):
        checkout = self._checkout()
        estimate = issue_checkout_estimate(
            checkout, self.user, expected_version=checkout.version,
            idempotency_key='document-estimate',
        )
        response = self.client.get(
            f'/api/billing/checkout-estimates/{estimate.public_id}/pdf/',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('estimado', response['Content-Disposition'].lower())

    def test_invoice_pdf_only_exists_after_post(self):
        checkout = self._checkout()
        invoice = post_checkout(
            checkout, self.user, payment_method='cash',
            expected_version=checkout.version, idempotency_key='document-paid',
        )
        response = self.client.get(f'/api/billing/invoices/{invoice.public_id}/pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('factura', response['Content-Disposition'].lower())
