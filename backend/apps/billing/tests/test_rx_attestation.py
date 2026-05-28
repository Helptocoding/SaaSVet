"""
Tests de atestación de receta externa en venta directa (ADR p26).

Gate: vender un producto `requires_prescription` en una `direct_sale` exige
(a) permiso `billing.rx_dispense` y (b) atestación explícita (cliente presentó
receta + médico). La atestación es un registro legal append-only.
"""
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.billing.models import (
    ExternalPrescriptionAttestation, Invoice, InvoiceItem,
)
from apps.inventory.models import Presentation, Product
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class RxAttestationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Rx Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="rx_admin", password="x", organization=cls.org, role="ADMIN",
        )
        # ASSISTANT sin rol en DB → fallback estático (no incluye billing.rx_dispense).
        cls.assistant = User.objects.create_user(
            username="rx_assistant", password="x", organization=cls.org, role="ASSISTANT",
        )
        cls.owner = Owner.objects.create(name="Rx Owner", phone="5551114000", organization=cls.org)
        cls.pet = Pet.objects.create(name="Rx Pet", species="dog", owner=cls.owner, organization=cls.org)

        cls.rx_product = Product.objects.create(
            name="Controlado", internal_code="RX-001", category="medication",
            requires_prescription=True, organization=cls.org,
        )
        cls.rx_pres = Presentation.objects.create(
            product=cls.rx_product, name="Caja", base_unit="unit",
            stock=Decimal("10"), sale_price=Decimal("80.00"), organization=cls.org,
        )
        cls.normal_product = Product.objects.create(
            name="Alimento", internal_code="AL-001", category="food",
            requires_prescription=False, organization=cls.org,
        )
        cls.normal_pres = Presentation.objects.create(
            product=cls.normal_product, name="Bolsa", base_unit="bag",
            stock=Decimal("10"), sale_price=Decimal("50.00"), organization=cls.org,
        )

    def _draft_direct_sale(self):
        return Invoice.objects.create(
            owner=self.owner, pet=self.pet, organization=self.org,
            status='draft', invoice_type='direct_sale',
        )

    def _add_item(self, inv, payload):
        return self.client.post(
            f'/api/billing/invoices/{inv.public_id}/items/', payload, format='json',
        )

    def test_rx_product_without_attestation_returns_400(self):
        self.client.force_authenticate(self.admin)
        inv = self._draft_direct_sale()
        r = self._add_item(inv, {'presentation': self.rx_pres.pk, 'quantity': '1'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('prescription_required', str(r.data))
        self.assertEqual(InvoiceItem.all_objects.filter(invoice=inv).count(), 0)
        self.assertEqual(ExternalPrescriptionAttestation.all_objects.filter(invoice=inv).count(), 0)

    def test_rx_product_with_attestation_succeeds(self):
        self.client.force_authenticate(self.admin)
        inv = self._draft_direct_sale()
        r = self._add_item(inv, {
            'presentation': self.rx_pres.pk, 'quantity': '2',
            'rx_attested': True, 'prescriber_name': 'Dr. Externo', 'prescription_folio': 'FOLIO-9',
        })
        self.assertEqual(r.status_code, 201, msg=r.data)
        atts = ExternalPrescriptionAttestation.all_objects.filter(invoice=inv)
        self.assertEqual(atts.count(), 1)
        a = atts.first()
        self.assertEqual(a.prescriber_name, 'Dr. Externo')
        self.assertEqual(a.prescription_folio, 'FOLIO-9')
        self.assertEqual(a.attested_by_id, self.admin.pk)
        self.assertEqual(a.presentation_id, self.rx_pres.pk)
        self.assertEqual(a.quantity, Decimal("2.00"))
        self.assertEqual(InvoiceItem.all_objects.filter(invoice=inv).count(), 1)

    def test_assistant_without_rx_dispense_returns_403(self):
        self.client.force_authenticate(self.assistant)
        inv = self._draft_direct_sale()
        r = self._add_item(inv, {
            'presentation': self.rx_pres.pk, 'quantity': '1',
            'rx_attested': True, 'prescriber_name': 'Dr. Externo',
        })
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ExternalPrescriptionAttestation.all_objects.filter(invoice=inv).count(), 0)
        self.assertEqual(InvoiceItem.all_objects.filter(invoice=inv).count(), 0)

    def test_attestation_survives_invoice_cancel(self):
        self.client.force_authenticate(self.admin)
        inv = self._draft_direct_sale()
        self._add_item(inv, {
            'presentation': self.rx_pres.pk, 'quantity': '1',
            'rx_attested': True, 'prescriber_name': 'Dr. Externo',
        })
        rc = self.client.patch(f'/api/billing/invoices/{inv.public_id}/cancel/', {}, format='json')
        self.assertEqual(rc.status_code, 200, msg=rc.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'cancelled')
        # El registro legal sobrevive a la cancelación (append-only).
        self.assertEqual(ExternalPrescriptionAttestation.all_objects.filter(invoice=inv).count(), 1)

    def test_non_rx_product_no_attestation_needed(self):
        self.client.force_authenticate(self.admin)
        inv = self._draft_direct_sale()
        r = self._add_item(inv, {'presentation': self.normal_pres.pk, 'quantity': '1'})
        self.assertEqual(r.status_code, 201, msg=r.data)
        self.assertEqual(ExternalPrescriptionAttestation.all_objects.filter(invoice=inv).count(), 0)
