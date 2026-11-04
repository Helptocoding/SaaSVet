from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import Checkout, CommandReceipt
from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class CloseAtomicityTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.org = Organization.objects.create(name='Cierre concurrente')
        self.owner = Owner.objects.create(organization=self.org, name='Cliente cierre')
        self.pet = Pet.objects.create(organization=self.org, owner=self.owner, name='Mascota cierre')
        self.vet = User.objects.create_user(username='order2_close_vet', password='synthetic',
            role='VET', organization=self.org, first_name='Vet', last_name='Prueba')
        self.record = MedicalRecord.objects.create(organization=self.org, pet=self.pet,
            veterinarian=self.vet, diagnosis='Diagnóstico', treatment='Tratamiento')
        self.url = f'/api/medical-records/{self.record.public_id}/close/'

    def _client(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        return client

    def test_double_close_concurrent_same_key_materializes_one_checkout(self):
        barrier = Barrier(2)

        def close():
            close_old_connections()
            barrier.wait(timeout=15)
            try:
                response = self._client().post(self.url, {}, format='json',
                                               HTTP_X_IDEMPOTENCY_KEY='close-concurrent-order2')
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(close) for _ in range(2)]
            statuses = [future.result(timeout=30) for future in futures]
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(Checkout.all_objects.filter(medical_record=self.record,
                         kind='primary_consultation').count(), 1)
        self.assertEqual(CommandReceipt.all_objects.filter(organization=self.org,
                         command_kind='close_medical_record').count(), 1)
        self.record.refresh_from_db()
        self.assertEqual(self.record.vet_snapshot_source, 'captured')

    def test_failure_after_anchor_and_snapshot_rolls_back_receipt_and_checkout(self):
        appointment = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=(timezone.now() + timedelta(days=1)).date(),
            start_time=time(9), end_time=time(9, 30), reason='Atención sintética',
            status='in_progress',
        )
        self.record.appointment = appointment
        self.record.save(update_fields=['appointment'])
        with patch('apps.billing.checkout_services.get_or_create_primary_checkout_for_medical_record',
                   side_effect=RuntimeError('synthetic failure')):
            response = self._client().post(self.url, {}, format='json')
        self.assertEqual(response.status_code, 500)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'open')
        self.assertIsNone(self.record.closed_at)
        self.assertEqual(self.record.vet_snapshot_source, 'unknown')
        self.assertIsNone(self.record.vet_snapshot_recorded_at)
        self.assertFalse(Checkout.all_objects.filter(medical_record=self.record).exists())
        self.assertFalse(CommandReceipt.all_objects.filter(organization=self.org,
                         command_kind='close_medical_record').exists())
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'in_progress')
        self.assertFalse(AppointmentStatusChange.objects.filter(
            appointment=appointment, to_status='done').exists())
