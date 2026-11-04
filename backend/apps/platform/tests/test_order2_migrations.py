"""Upgrade from prior schema with synthetic documents, on PostgreSQL only."""
from importlib import import_module

from django.apps import apps as current_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class Order2UpgradeTests(TransactionTestCase):
    # Keep this isolated from the main suite: it reverses and reapplies the new
    # migrations, never the regular development DB.
    def test_upgrade_preserves_anchors_and_reconstructs_only_known_identities(self):
        self.assertEqual(connection.vendor, 'postgresql')
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [
            ('billing', '0035_unit_snapshots_and_multilot_returns'),
            ('medical_records', '0024_medicalrecord_originated_from'),
            ('prescriptions', '0006_alter_prescription_pet'),
            ('patients', '0019_pet_registration_effect'),
            ('organizations', '0012_remove_organizationsettings_auto_create_invoice_on_done_and_more'),
            ('inventory', '0026_medical_record_product_factor_snapshot'),
            ('appointments', '0018_confirm_attendance_effect'),
            ('users', '0011_user_is_service_account_alter_user_role'),
            ('platform', None),
        ]
        try:
            executor.migrate(previous)
            historical = executor.loader.project_state(
                [node for node in previous if node[1] is not None],
            ).apps
            Org = historical.get_model('organizations', 'Organization')
            Owner = historical.get_model('patients', 'Owner')
            Pet = historical.get_model('patients', 'Pet')
            User = historical.get_model('users', 'User')
            Record = historical.get_model('medical_records', 'MedicalRecord')
            Rx = historical.get_model('prescriptions', 'Prescription')
            Checkout = historical.get_model('billing', 'Checkout')
            Invoice = historical.get_model('billing', 'Invoice')
            Audit = historical.get_model('billing', 'InvoiceAuditLog')
            Payment = historical.get_model('billing', 'Payment')
            org = Org.objects.create(name='Upgrade sintético')
            owner = Owner.objects.create(organization=org, name='Titular de prueba')
            pet = Pet.objects.create(organization=org, owner=owner, name='Paciente previo')
            vet = User.objects.create(organization=org, username='upgrade_vet',
                                      first_name='Nombre actual', last_name='Reconstruido')
            now = timezone.now()
            record = Record.objects.create(organization=org, pet=pet, veterinarian=vet,
                status='closed', closed_at=now, diagnosis='Dato clínico sintético')
            Rx.objects.create(organization=org, medical_record=record, pet=pet)
            checkout = Checkout.objects.create(organization=org, customer=owner, pet=pet,
                medical_record=record, origin='consultation', kind='primary_consultation',
                lifecycle='completed', completion_kind='posted_paid')
            invoice = Invoice.objects.create(organization=org, owner=owner, pet=pet,
                checkout=checkout, medical_record=record, status='paid',
                posted_at=now, paid_at=now, subtotal='20.00', total='20.00')
            audit = Audit.objects.create(invoice=invoice, new_status='paid')
            Payment.objects.create(organization=org, invoice=invoice, amount='20.00',
                                   method='cash', occurred_at=now)
            owner_uuid, pet_uuid, vet_uuid = owner.public_id, pet.public_id, vet.public_id
            record_id, invoice_id, audit_id = record.pk, invoice.pk, audit.pk
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            from apps.billing.models import Invoice as CurrentInvoice, InvoiceAuditLog
            from apps.medical_records.models import MedicalRecord
            from apps.prescriptions.models import Prescription
            upgraded = CurrentInvoice.all_objects.get(pk=invoice_id)
            closed = MedicalRecord.all_objects.get(pk=record_id)
            self.assertEqual(upgraded.paid_at, now)
            self.assertEqual(upgraded.posted_at, now)
            self.assertEqual(closed.closed_at, now)
            self.assertEqual(upgraded.subject_snapshot['source'], 'reconstructed')
            self.assertEqual(upgraded.subject_snapshot['owner']['uuid'], str(owner_uuid))
            self.assertEqual(closed.subject_snapshot['pet']['uuid'], str(pet_uuid))
            self.assertEqual(closed.vet_public_id_at_close, vet_uuid)
            self.assertEqual(closed.vet_snapshot_source, 'reconstructed')
            self.assertGreaterEqual(closed.vet_snapshot_recorded_at, now)
            self.assertEqual(InvoiceAuditLog.objects.get(pk=audit_id).invoice_public_id,
                             upgraded.public_id)
            self.assertEqual(Prescription.all_objects.filter(medical_record_id=record_id).count(), 1)
            stamp = upgraded.subject_snapshot['recorded_at']
            backfill = import_module('apps.billing.migrations.0039_subject_snapshot_backfill').backfill
            backfill(current_apps, None)
            self.assertEqual(CurrentInvoice.all_objects.get(pk=invoice_id).subject_snapshot['recorded_at'], stamp)
        finally:
            MigrationExecutor(connection).migrate(latest)
