from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from decimal import Decimal
from uuid import uuid4

from django.db import transaction, IntegrityError, close_old_connections
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import Checkout, Invoice, InvoiceItem, Payment, Service
from apps.inventory.models import Product
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.platform.models import PhysicalDeletionReceipt
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.users.models import User


class PhysicalDeletionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clínica sintética')
        cls.other = Organization.objects.create(name='Otra clínica sintética')
        cls.operator = User.objects.create_superuser(username='physical_operator',
            password='synthetic', role='ADMIN_SAAS')
        cls.second_operator = User.objects.create_superuser(username='physical_second',
            password='synthetic', role='ADMIN_SAAS')
        cls.admin = User.objects.create_user(username='physical_admin', password='synthetic',
            role='ADMIN', organization=cls.org)

    def setUp(self):
        self.client.force_authenticate(self.operator)
        self.owner = Owner.objects.create(organization=self.org, name='Persona de prueba')

    def _payload(self, target, kind='owner', organization=None):
        return {'organization_id': str((organization or self.org).public_id),
                'target_type': kind, 'target_id': str(target.public_id),
                'reason': 'Corrección sintética de duplicado'}

    def _preview(self, payload):
        response = self.client.post('/api/platform/physical-deletions/preview/',
                                    payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def _execute(self, payload, preview, key=None):
        return self.client.post('/api/platform/physical-deletions/execute/',
            {**payload, 'confirmation': preview['confirmation'],
             'idempotency_key': str(key or uuid4())}, format='json')

    def _paid_document(self, *, pet=None, record=None, paid=True):
        checkout = Checkout.objects.create(organization=self.org, customer=self.owner,
            pet=pet, medical_record=record,
            origin='consultation' if record else 'direct_sale',
            kind='primary_consultation' if record else 'direct_sale',
            lifecycle='completed', completion_kind='posted_paid' if paid else 'posted_unpaid')
        invoice = Invoice.objects.create(organization=self.org, checkout=checkout,
            owner=self.owner, pet=pet, medical_record=record,
            status='paid' if paid else 'posted', paid_at=timezone.now() if paid else None,
            invoice_type='consultation' if record else 'direct_sale')
        service = Service.objects.create(organization=self.org, name='Atención', base_price='50.00')
        InvoiceItem.objects.create(organization=self.org, invoice=invoice, service=service,
                                   description='Atención', quantity=Decimal('1'),
                                   unit_price=Decimal('50.00'))
        invoice.refresh_from_db()
        if paid:
            Payment.objects.create(organization=self.org, invoice=invoice,
                                   amount='50.00', method='cash', occurred_at=timezone.now())
        return invoice, checkout

    def test_existing_invoice_can_be_paid_after_archive_but_blocks_physical_delete(self):
        invoice, _ = self._paid_document(paid=False)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/owners/{self.owner.public_id}/archive/').status_code, 200)
        self.client.force_authenticate(self.operator)
        payload = self._payload(self.owner)
        self.assertIn('pending_payment', self._preview(payload)['blockers'])
        self.client.force_authenticate(self.admin)
        result = self.client.patch(f'/api/billing/invoices/{invoice.public_id}/pay/',
                                   {'payment_method': 'cash'}, format='json',
                                   HTTP_X_IDEMPOTENCY_KEY=str(uuid4()))
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(Invoice.all_objects.get(pk=invoice.pk).remaining_balance, 0)
        self.assertEqual(Payment.all_objects.filter(invoice=invoice).count(), 1)
        self.client.force_authenticate(self.operator)
        self.assertTrue(self._preview(payload)['eligible'])

    def test_paid_owner_document_survives_delete_and_replay(self):
        invoice, checkout = self._paid_document()
        previous_name = self.owner.name
        Owner.all_objects.filter(pk=self.owner.pk).update(name='Nombre posterior')
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        payload = self._payload(self.owner)
        preview = self._preview(payload)
        self.assertTrue(preview['eligible'], preview['blockers'])
        key = uuid4()
        first = self._execute(payload, preview, key)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertFalse(Owner.all_objects.filter(pk=self.owner.pk).exists())
        self.assertIsNone(Invoice.all_objects.get(pk=invoice.pk).owner_id)
        self.assertIsNone(Checkout.all_objects.get(pk=checkout.pk).customer_id)
        self.assertEqual(Invoice.all_objects.get(pk=invoice.pk).remaining_balance, 0)
        self.assertEqual(Payment.all_objects.filter(invoice=invoice).count(), 1)
        replay = self._execute(payload, preview, key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data['operation_id'], first.data['operation_id'])
        self.assertEqual(PhysicalDeletionReceipt.objects.count(), 1)
        self.client.force_authenticate(self.second_operator)
        self.assertEqual(self._execute(payload, preview, key).status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f'/api/billing/invoices/{invoice.public_id}/').status_code, 200)
        doc = self.client.get(f'/api/billing/invoices/{invoice.public_id}/')
        self.assertEqual(doc.data['owner_name'], previous_name)
        self.assertIsNone(doc.data['owner_public_id'])
        filtered = self.client.get('/api/billing/invoices/', {'owner': str(self.owner.public_id)})
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(str(invoice.public_id),
                      [str(row['public_id']) for row in filtered.data['results']])
        self.assertEqual(self.client.get(f'/api/billing/invoices/{invoice.public_id}/pdf/').status_code, 200)

    def test_pet_with_closed_record_prescription_paid_invoice_and_pdf_survives(self):
        pet = Pet.objects.create(organization=self.org, owner=self.owner,
                                 name='Mascota histórica', species='canino',
                                 sex='female', birth_date=date(2020, 1, 1))
        vet = self.admin
        vet.first_name = 'Veterinaria'
        vet.last_name = 'Prueba'
        vet.save(update_fields=['first_name', 'last_name'])
        record = MedicalRecord.objects.create(organization=self.org, pet=pet,
            veterinarian=vet, diagnosis='Diagnóstico de prueba', treatment='Tratamiento de prueba',
            status='closed', closed_at=timezone.now(),
            vet_public_id_at_close=vet.public_id, vet_name_at_close='Veterinaria Prueba',
            vet_snapshot_source='captured', vet_snapshot_recorded_at=timezone.now())
        rx = Prescription.objects.create(organization=self.org, medical_record=record,
                                          pet=pet, veterinarian=vet)
        product = Product.objects.create(organization=self.org, name='Medicamento',
                                          internal_code='P-RX')
        PrescriptionItem.objects.create(organization=self.org, prescription=rx,
                                         product=product, dose='Una vez', quantity='1')
        invoice, checkout = self._paid_document(pet=pet, record=record)
        Pet.all_objects.filter(pk=pet.pk).update(name='Nombre posterior')
        Pet.all_objects.filter(pk=pet.pk).update(is_active=False)
        payload = self._payload(pet, 'pet')
        preview = self._preview(payload)
        self.assertTrue(preview['eligible'], preview['blockers'])
        response = self._execute(payload, preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Pet.all_objects.filter(pk=pet.pk).exists())
        record.refresh_from_db()
        rx.refresh_from_db()
        invoice.refresh_from_db()
        self.assertIsNone(record.pet_id)
        self.assertIsNone(rx.pet_id)
        self.assertIsNone(invoice.pet_id)
        self.assertEqual(invoice.remaining_balance, 0)
        self.assertEqual(Payment.all_objects.filter(invoice=invoice).count(), 1)
        self.client.force_authenticate(self.admin)
        detail = self.client.get(f'/api/medical-records/{record.public_id}/')
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['pet_name'], 'Mascota histórica')
        self.assertEqual(detail.data['veterinarian_name'], 'Veterinaria Prueba')
        history = self.client.get('/api/medical-records/', {'pet': str(pet.public_id)})
        self.assertEqual(history.status_code, 200)
        self.assertIn(str(record.public_id),
                      [str(item['public_id']) for item in history.data['results']])
        prescriptions = self.client.get('/api/prescriptions/', {'pet': str(pet.public_id)})
        self.assertEqual(prescriptions.status_code, 200)
        self.assertIn(str(rx.public_id), [str(item['public_id']) for item in prescriptions.data])
        self.assertEqual(prescriptions.data[0]['pet_sex'], 'female')
        self.assertEqual(prescriptions.data[0]['pet_birth_date'], '2020-01-01')
        self.assertEqual(self.client.get(f'/api/medical-records/{record.public_id}/pdf/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/prescriptions/{rx.public_id}/pdf/').status_code, 200)

    def test_pending_payment_new_child_and_wrong_confirmation_block(self):
        invoice, _ = self._paid_document()
        Invoice.all_objects.filter(pk=invoice.pk).update(status='posted', paid_at=None)
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        payload = self._payload(self.owner)
        self.assertIn('pending_payment', self._preview(payload)['blockers'])
        Invoice.all_objects.filter(pk=invoice.pk).update(status='paid', paid_at=timezone.now())
        preview = self._preview(payload)
        self.assertTrue(preview['eligible'])
        Pet.objects.create(organization=self.org, owner=self.owner, name='Nuevo hijo')
        self.assertEqual(self._execute(payload, preview).status_code, 409)
        self.assertTrue(Owner.all_objects.filter(pk=self.owner.pk).exists())

    def test_platform_only_confirmation_and_receipt_rollback(self):
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        payload = self._payload(self.owner)
        preview = self._preview(payload)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self._execute(payload, preview).status_code, 403)
        self.client.force_authenticate(self.second_operator)
        self.assertEqual(self._execute(payload, preview).status_code, 409)
        self.client.force_authenticate(self.operator)
        with patch('apps.platform.services.physical_deletion.PhysicalDeletionReceipt.objects.create',
                   side_effect=RuntimeError('audit unavailable')):
            self.assertEqual(self._execute(payload, preview).status_code, 500)
        self.assertTrue(Owner.all_objects.filter(pk=self.owner.pk).exists())
        self.assertEqual(PhysicalDeletionReceipt.objects.count(), 0)
        key = uuid4()
        self.assertEqual(self._execute(payload, preview, key).status_code, 200)
        self.assertEqual(self._execute(payload, preview, uuid4()).status_code, 409)
        self.assertEqual(self._execute({**payload, 'reason': 'Motivo nuevo'}, preview, key).status_code, 409)

    def test_preview_rejects_incomplete_platform_predicates_and_wrong_tenant(self):
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        payload = self._payload(self.owner)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post('/api/platform/physical-deletions/preview/',
                                          payload, format='json').status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.post('/api/platform/physical-deletions/preview/',
                                       payload, format='json').status_code, (401, 403))
        incomplete = User.objects.create_user(username='physical_incomplete',
            password='synthetic', role='ADMIN_SAAS', is_staff=True)
        self.client.force_authenticate(incomplete)
        self.assertEqual(self.client.post('/api/platform/physical-deletions/preview/',
                                          payload, format='json').status_code, 403)
        self.client.force_authenticate(self.operator)
        wrong = self._payload(self.owner, organization=self.other)
        self.assertEqual(self.client.post('/api/platform/physical-deletions/preview/',
                                          wrong, format='json').status_code, 404)
        self.assertTrue(Owner.all_objects.filter(pk=self.owner.pk).exists())

    def test_empty_organization_only_and_direct_deletes_protected(self):
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.owner.delete()
        # Bypass signal de provisioning: un tenant realmente vacío/desactivado.
        empty = Organization(name='Nunca provisionada', is_active=False)
        Organization.objects.bulk_create([empty])
        payload = self._payload(empty, 'organization', organization=empty)
        preview = self._preview(payload)
        self.assertTrue(preview['eligible'], preview['blockers'])
        self.assertEqual(self._execute(payload, preview).status_code, 200)
        self.assertFalse(Organization.objects.filter(pk=empty.pk).exists())
        self.assertTrue(PhysicalDeletionReceipt.objects.filter(target_id=empty.public_id).exists())
        self.org.is_active = False
        self.org.save(update_fields=['is_active'])
        self.assertIn('unsupported_reference', self._preview(
            self._payload(self.org, 'organization'))['blockers'])

    def test_generic_subject_and_nonallowlisted_target_are_not_eligible(self):
        generic = Owner.all_objects.get(organization=self.org, is_generic=True)
        Owner.all_objects.filter(pk=generic.pk).update(is_active=False)
        observed = self._preview(self._payload(generic))
        self.assertIn('generic_resource', observed['blockers'])
        self.assertIsNone(observed['confirmation'])
        bad = self.client.post('/api/platform/physical-deletions/preview/', {
            'organization_id': str(self.org.public_id), 'target_type': 'invoice',
            'target_id': str(uuid4()), 'reason': 'Motivo no permitido',
        }, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_import_provenance_blocks_exceptional_physical_delete(self):
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False, legacy_id='IMPORT-1')
        observed = self._preview(self._payload(self.owner))
        self.assertIn('unsupported_import_provenance', observed['blockers'])
        self.assertIsNone(observed['confirmation'])

    def test_expired_confirmation_is_conflict_without_mutation(self):
        Owner.all_objects.filter(pk=self.owner.pk).update(is_active=False)
        payload = self._payload(self.owner)
        observed = self._preview(payload)
        with patch('apps.platform.services.physical_deletion.CONFIRM_TTL_SECONDS', -1):
            self.assertEqual(self._execute(payload, observed).status_code, 409)
        self.assertTrue(Owner.all_objects.filter(pk=self.owner.pk).exists())

    def test_mutating_snapshot_or_its_tenant_is_rejected_by_postgresql(self):
        invoice, _ = self._paid_document()
        other_uuid = str(self.other.public_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.all_objects.filter(pk=invoice.pk).update(subject_snapshot={
                **invoice.subject_snapshot, 'organization': other_uuid,
            })
        self.assertEqual(Invoice.all_objects.get(pk=invoice.pk).subject_snapshot['organization'],
                         str(self.org.public_id))


class PhysicalDeletionConcurrencyTests(TransactionTestCase):
    def test_two_executions_same_key_have_one_durable_receipt(self):
        from apps.platform.services.physical_deletion import preview, execute

        org = Organization.objects.create(name='Concurrencia física aislada')
        owner = Owner.objects.create(organization=org, name='Cliente carrera')
        Owner.all_objects.filter(pk=owner.pk).update(is_active=False)
        operator = User.objects.create_superuser(username='physical_concurrent',
                                                  password='synthetic', role='ADMIN_SAAS')
        payload = {'organization_id': org.public_id, 'target_type': 'owner',
                   'target_id': owner.public_id, 'reason': 'Corrección de carrera sintética'}
        signed = preview(actor=operator, **payload)['confirmation']
        key = uuid4()
        barrier = Barrier(2)

        def run():
            close_old_connections()
            barrier.wait(timeout=15)
            try:
                return execute(actor=operator, **payload, confirmation=signed,
                               idempotency_key=key)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            results = [f.result(timeout=30) for f in futures]
        self.assertEqual(results[0]['operation_id'], results[1]['operation_id'])
        self.assertEqual(PhysicalDeletionReceipt.objects.filter(idempotency_key=key).count(), 1)
        self.assertFalse(Owner.all_objects.filter(pk=owner.pk).exists())
