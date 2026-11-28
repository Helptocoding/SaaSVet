from django.db.models.deletion import ProtectedError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.billing.models import Checkout, Invoice, InvoiceAuditLog
from apps.inventory.models import Product, Presentation, StockMovement
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization, OrganizationConfigEvent
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription


class ConservationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Clínica aislada')
        self.owner = Owner.objects.create(organization=self.org, name='Cliente sintético')
        self.pet = Pet.objects.create(organization=self.org, owner=self.owner, name='Paciente sintético')

    def test_invoice_audit_protects_document_and_stores_public_id(self):
        checkout = Checkout.objects.create(
            organization=self.org, customer=self.owner,
            origin='direct_sale', kind='direct_sale',
        )
        invoice = Invoice.objects.create(
            organization=self.org, checkout=checkout, owner=self.owner,
            invoice_type='direct_sale',
        )
        audit = InvoiceAuditLog.objects.create(invoice=invoice, new_status='posted')
        self.assertEqual(audit.invoice_public_id, invoice.public_id)
        with self.assertRaises(ProtectedError):
            invoice.delete()
        self.assertTrue(InvoiceAuditLog.objects.filter(pk=audit.pk).exists())

    def test_prescription_protects_record_via_instance_and_queryset(self):
        record = MedicalRecord.objects.create(organization=self.org, pet=self.pet)
        rx = Prescription.objects.create(organization=self.org, medical_record=record, pet=self.pet)
        with self.assertRaises(ProtectedError):
            record.delete()
        with self.assertRaises(ProtectedError):
            MedicalRecord.all_objects.filter(pk=record.pk).delete()
        self.assertTrue(Prescription.all_objects.filter(pk=rx.pk).exists())

    def test_product_and_presentation_keep_stock_ledger(self):
        product = Product.objects.create(organization=self.org, name='Producto', internal_code='P-ORD2')
        presentation = Presentation.objects.create(
            organization=self.org, product=product, name='Pieza', base_unit='unit', sale_price='10',
        )
        movement = StockMovement.objects.create(
            organization=self.org, product=product, presentation=presentation,
            movement_type='in', quantity='2',
        )
        with self.assertRaises(ProtectedError):
            presentation.delete()
        with self.assertRaises(ProtectedError):
            Product.all_objects.filter(pk=product.pk).delete()
        self.assertTrue(StockMovement.all_objects.filter(pk=movement.pk).exists())

    def test_config_history_protects_tenant(self):
        # ADR p70 D9: el historial de Configuración absorbió al de la zona horaria.
        event = OrganizationConfigEvent.objects.create(
            organization=self.org, kind=OrganizationConfigEvent.KIND_TIMEZONE_CHANGED,
            changes={'timezone': ['UTC', 'America/Mexico_City']},
        )
        with self.assertRaises(ProtectedError):
            self.org.delete()
        self.assertTrue(OrganizationConfigEvent.objects.filter(pk=event.pk).exists())

    def test_invoice_and_checkout_cross_tenant_bypass_and_parent_reparent_rejected(self):
        other = Organization.objects.create(name='Otra clínica')
        foreign = Owner.objects.create(organization=other, name='Ajeno')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Checkout.all_objects.bulk_create([Checkout(
                organization=self.org, customer=foreign,
                origin='direct_sale', kind='direct_sale',
            )])
        checkout = Checkout.objects.create(organization=self.org, customer=self.owner,
                                           origin='direct_sale', kind='direct_sale')
        invoice = Invoice.objects.create(organization=self.org, checkout=checkout,
                                         owner=self.owner, invoice_type='direct_sale')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.all_objects.filter(pk=invoice.pk).update(owner=foreign)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE billing_invoice SET owner_id=%s WHERE id=%s',
                               [foreign.pk, invoice.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('UPDATE billing_checkout SET organization_id=%s WHERE id=%s',
                               [other.pk, checkout.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Owner.all_objects.filter(pk=self.owner.pk).update(organization=other)
        self.assertEqual(Invoice.all_objects.get(pk=invoice.pk).organization_id, self.org.pk)

    def test_checkout_insert_rejects_archived_customer_even_via_bulk(self):
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Checkout.all_objects.bulk_create([Checkout(
                organization=self.org, customer=self.owner,
                origin='direct_sale', kind='direct_sale',
            )])
