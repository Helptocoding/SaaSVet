"""
Dispensación de receta interna hacia la MISMA factura de consulta (ADR p30).

Invariantes cubiertos:
  - Dispensar agrega `InvoiceItem`(s) a la factura de consulta (no crea otra
    factura) y NO mueve stock al dispensar.
  - El descuento de stock corre por la ÚNICA ruta (`_confirm_locked_invoice`):
    al confirmar la consulta se descuenta SOLO el ítem dispensado; un insumo
    de consulta (ítem con presentación pero sin FK de receta) NO se vuelve a
    descontar (lo hizo MedicalRecordProduct al consumirse).
  - Cancelar una consulta confirmada revierte el stock del ítem dispensado y
    deja intacto el insumo.
  - Producto `requires_prescription` exige permiso billing.rx_dispense.
  - Una presentación ya presente como insumo (sin FK) no se mezcla con la
    dispensación.
"""
from decimal import Decimal

from rest_framework.test import APITestCase

from apps.billing.models import Invoice, InvoiceItem
from apps.billing.services import get_or_create_invoice_for_medical_record
from apps.inventory.models import Presentation, Product
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.users.models import User


class PrescriptionDispenseTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Disp Org", timezone="UTC")
        cls.admin = User.objects.create_user(
            username="disp_admin", password="x", organization=cls.org, role="ADMIN",
        )
        # ASSISTANT (rol estático) no incluye billing.rx_dispense.
        cls.assistant = User.objects.create_user(
            username="disp_assistant", password="x", organization=cls.org, role="ASSISTANT",
        )
        cls.owner = Owner.objects.create(name="Disp Owner", phone="5551119000", organization=cls.org)
        cls.pet = Pet.objects.create(name="Disp Pet", species="dog", owner=cls.owner, organization=cls.org)

        # Producto insumo (consumido en consulta) y producto a llevar.
        cls.prod_insumo = Product.objects.create(
            name="Insumo", internal_code="INS-1", category="medication", organization=cls.org,
        )
        cls.pres_insumo = Presentation.objects.create(
            product=cls.prod_insumo, name="Vial", base_unit="vial",
            stock=Decimal("10"), sale_price=Decimal("30.00"), organization=cls.org,
        )
        cls.prod_take = Product.objects.create(
            name="ParaLlevar", internal_code="TK-1", category="medication", organization=cls.org,
        )
        cls.pres_take = Presentation.objects.create(
            product=cls.prod_take, name="Caja", base_unit="unit",
            stock=Decimal("10"), sale_price=Decimal("50.00"), organization=cls.org,
        )
        cls.prod_rx = Product.objects.create(
            name="Controlado", internal_code="RX-1", category="medication",
            requires_prescription=True, organization=cls.org,
        )
        cls.pres_rx = Presentation.objects.create(
            product=cls.prod_rx, name="Frasco", base_unit="bottle",
            stock=Decimal("10"), sale_price=Decimal("90.00"), organization=cls.org,
        )
        # ADR p31: Product.stock_quantity es fuente autoritativa (conv_factor=1 → stock_qty=pres.stock)
        Product.objects.filter(pk=cls.prod_insumo.pk).update(base_unit='vial', stock_quantity=Decimal('10'))
        Product.objects.filter(pk=cls.prod_take.pk).update(base_unit='unit', stock_quantity=Decimal('10'))
        Product.objects.filter(pk=cls.prod_rx.pk).update(base_unit='bottle', stock_quantity=Decimal('10'))

    def setUp(self):
        # Cada test parte de una consulta + receta frescas (estado mutable).
        self.mr = MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.admin, organization=self.org,
            status=MedicalRecord.Status.OPEN,
        )
        self.rx = Prescription.objects.create(
            medical_record=self.mr, pet=self.pet, veterinarian=self.admin, organization=self.org,
        )
        self.item_take = PrescriptionItem.objects.create(
            prescription=self.rx, product=self.prod_take, dose="1 c/12h",
            quantity=Decimal("2"), organization=self.org,
        )
        self.item_rx = PrescriptionItem.objects.create(
            prescription=self.rx, product=self.prod_rx, dose="1 c/24h",
            quantity=Decimal("1"), organization=self.org,
        )

    def _dispense(self, lines):
        return self.client.post(
            f'/api/billing/prescriptions/{self.rx.public_id}/dispense/',
            {'lines': lines}, format='json',
        )

    def _stock(self, pres):
        pres.refresh_from_db()
        return pres.stock

    def test_dispense_adds_to_consultation_invoice_without_moving_stock(self):
        self.client.force_authenticate(self.admin)
        r = self._dispense([{
            'presentation': self.pres_take.pk, 'quantity': 2,
            'prescription_item': self.item_take.pk,
        }])
        self.assertEqual(r.status_code, 200, msg=r.data)
        # Misma factura de consulta — no se creó una venta directa.
        self.assertEqual(r.data['invoice_type'], 'consultation')
        self.assertEqual(Invoice.all_objects.filter(invoice_type='direct_sale').count(), 0)
        self.assertEqual(str(r.data['medical_record_public_id']), str(self.mr.public_id))
        # La línea quedó marcada como dispensada y NO descontó stock todavía.
        items = [i for i in r.data['items'] if i['presentation'] == self.pres_take.pk]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['dispensed'])
        self.assertEqual(self._stock(self.pres_take), Decimal("10"))

    def test_confirm_decrements_only_dispensed_not_consult_insumo(self):
        self.client.force_authenticate(self.admin)
        invoice = get_or_create_invoice_for_medical_record(self.mr)
        # Insumo de consulta: ítem con presentación SIN FK de receta. Simula la
        # línea sincronizada desde MedicalRecordProduct (stock ya descontado al
        # consumirse → aquí dejamos el stock como si ya hubiera bajado a 9).
        self.pres_insumo.stock = Decimal("9")
        self.pres_insumo.save(update_fields=['stock'])
        InvoiceItem.objects.create(
            invoice=invoice, presentation=self.pres_insumo, description=str(self.pres_insumo),
            quantity=Decimal("1"), unit_price=self.pres_insumo.sale_price, organization=self.org,
        )
        # Dispensar el producto a llevar.
        self._dispense([{
            'presentation': self.pres_take.pk, 'quantity': 2,
            'prescription_item': self.item_take.pk,
        }])

        rc = self.client.patch(f'/api/billing/invoices/{invoice.public_id}/confirm/', {}, format='json')
        self.assertEqual(rc.status_code, 200, msg=rc.data)
        # El dispensado descuenta (10 → 8); el insumo NO se vuelve a descontar.
        self.assertEqual(self._stock(self.pres_take), Decimal("8"))
        self.assertEqual(self._stock(self.pres_insumo), Decimal("9"))

    def test_cancel_reverts_dispensed_and_leaves_insumo(self):
        self.client.force_authenticate(self.admin)
        invoice = get_or_create_invoice_for_medical_record(self.mr)
        self.pres_insumo.stock = Decimal("9")
        self.pres_insumo.save(update_fields=['stock'])
        InvoiceItem.objects.create(
            invoice=invoice, presentation=self.pres_insumo, description=str(self.pres_insumo),
            quantity=Decimal("1"), unit_price=self.pres_insumo.sale_price, organization=self.org,
        )
        self._dispense([{
            'presentation': self.pres_take.pk, 'quantity': 2,
            'prescription_item': self.item_take.pk,
        }])
        self.client.patch(f'/api/billing/invoices/{invoice.public_id}/confirm/', {}, format='json')
        self.assertEqual(self._stock(self.pres_take), Decimal("8"))

        rcancel = self.client.patch(f'/api/billing/invoices/{invoice.public_id}/cancel/', {}, format='json')
        self.assertEqual(rcancel.status_code, 200, msg=rcancel.data)
        # Dispensado revertido (8 → 10); insumo intacto (lo revierte el MRP, no el cobro).
        self.assertEqual(self._stock(self.pres_take), Decimal("10"))
        self.assertEqual(self._stock(self.pres_insumo), Decimal("9"))

    def test_rx_product_requires_dispense_permission(self):
        self.client.force_authenticate(self.assistant)
        r = self._dispense([{
            'presentation': self.pres_rx.pk, 'quantity': 1,
            'prescription_item': self.item_rx.pk,
        }])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(InvoiceItem.all_objects.filter(presentation=self.pres_rx).count(), 0)

        self.client.force_authenticate(self.admin)
        r2 = self._dispense([{
            'presentation': self.pres_rx.pk, 'quantity': 1,
            'prescription_item': self.item_rx.pk,
        }])
        self.assertEqual(r2.status_code, 200, msg=r2.data)
        self.assertEqual(InvoiceItem.all_objects.filter(presentation=self.pres_rx).count(), 1)

    def test_dispense_rejected_when_presentation_already_non_dispensed_insumo(self):
        self.client.force_authenticate(self.admin)
        invoice = get_or_create_invoice_for_medical_record(self.mr)
        # El producto a llevar también se usó como insumo (misma presentación,
        # sin FK). unique_together impide dos líneas → recepción lo ajusta a mano.
        InvoiceItem.objects.create(
            invoice=invoice, presentation=self.pres_take, description=str(self.pres_take),
            quantity=Decimal("1"), unit_price=self.pres_take.sale_price, organization=self.org,
        )
        r = self._dispense([{
            'presentation': self.pres_take.pk, 'quantity': 2,
            'prescription_item': self.item_take.pk,
        }])
        self.assertEqual(r.status_code, 400)
        self.assertIn('insumo', str(r.data).lower())
