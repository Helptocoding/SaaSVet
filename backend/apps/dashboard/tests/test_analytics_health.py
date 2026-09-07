"""
Tests for /api/internal/analytics-health/ — ADMIN_SAAS-only endpoint that
exposes anchor provenance distribution, invariant violations, decay alerts,
and per-anchor trust score.
"""
from decimal import Decimal

from rest_framework.test import APIClient, APITestCase

from apps.billing.models import Service
from apps.billing.tests.factories import build_direct_sale_checkout, pay_checkout_for_test
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class AnalyticsHealthTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="AH Org", timezone="UTC")
        cls.platform_admin = User.objects.create_user(
            username="ah_platform", password="x", role="ADMIN_SAAS",
        )
        cls.org_admin = User.objects.create_user(
            username="ah_org_admin", password="x", organization=cls.org, role="ADMIN",
        )
        cls.owner = Owner.objects.create(
            name="AH Owner", phone="5550008888", organization=cls.org,
        )
        cls.pet = Pet.objects.create(
            name="AH Pet", species="dog", owner=cls.owner, organization=cls.org,
        )
        cls.service = Service.objects.create(
            name="AH Servicio", base_price=Decimal("100.00"), organization=cls.org,
        )

    def _make_paid_invoice(self):
        checkout = build_direct_sale_checkout(
            organization=self.org, owner=self.owner, pet=self.pet,
            user=self.org_admin, service=self.service,
        )
        return pay_checkout_for_test(checkout, user=self.org_admin, payment_method='cash')

    def test_org_admin_is_forbidden(self):
        client = APIClient()
        client.force_authenticate(user=self.org_admin)
        r = client.get('/api/internal/analytics-health/')
        self.assertEqual(r.status_code, 403)

    def test_anonymous_is_forbidden(self):
        r = APIClient().get('/api/internal/analytics-health/')
        self.assertIn(r.status_code, (401, 403))

    def test_platform_admin_gets_payload(self):
        self._make_paid_invoice()
        client = APIClient()
        client.force_authenticate(user=self.platform_admin)
        r = client.get('/api/internal/analytics-health/')
        self.assertEqual(r.status_code, 200)
        data = r.data
        self.assertIn('anchors', data)
        self.assertIn('invariant_violations', data)
        self.assertIn('legacy_decay_alerts', data)
        self.assertIn('fallback_warnings', data)
        self.assertIn('trust_score_per_anchor', data)

        # All invariants must be 0 on a clean DB.
        for k, v in data['invariant_violations'].items():
            self.assertEqual(v, 0, msg=f"{k}={v}")

        # Service-written invoice should land in 'service' bucket.
        paid_dist = data['anchors']['invoice.paid_at']
        self.assertGreaterEqual(paid_dist.get('service', 0), 1)

        # Trust score on a clean DB with only service writes must be 'A'.
        self.assertEqual(data['trust_score_per_anchor']['invoice.paid_at'], 'A')

    def test_org_filter_param(self):
        self._make_paid_invoice()
        client = APIClient()
        client.force_authenticate(user=self.platform_admin)
        r = client.get(f'/api/internal/analytics-health/?org={self.org.pk}')
        self.assertEqual(r.status_code, 200)
        # With explicit org filter, paid_at distribution should still show our row.
        self.assertGreaterEqual(r.data['anchors']['invoice.paid_at'].get('service', 0), 1)
