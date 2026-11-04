"""Regresión audit run-1, fase 8.5: repreciar un cargo clínico solo mientras la
consulta está abierta.

Al cerrar, el ciclo de precio activo se congela en ClinicalChargeSnapshot y
CheckoutItem, y nada lo vuelve a materializar. `reprice` no lo comprobaba:
respondía con el precio nuevo mientras la cuenta seguía cobrando el viejo, y
una rematerialización habría dejado dos líneas para un solo servicio.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.checkout_services import (
    get_or_create_primary_checkout_for_medical_record,
    record_clinical_charge_delta,
    reprice_clinical_charge,
)
from apps.billing.models import ClinicalChargeEntry, CommandReceipt, Service
from apps.medical_records.models import MedicalRecord, MedicalRecordService
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class RepriceOpenRecordOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Reprice Org', timezone='UTC')
        cls.user = User.objects.create_user(
            username='reprice-admin', password='x', organization=cls.org, role='ADMIN',
        )
        owner = Owner.objects.create(name='Cliente Reprice', phone='5559000011',
                                     organization=cls.org)
        cls.pet = Pet.objects.create(name='Paciente Reprice', species='dog', owner=owner,
                                     organization=cls.org)
        cls.service = Service.objects.create(name='Consulta', base_price=Decimal('100.00'),
                                             organization=cls.org)

    def _record_with_service(self):
        record = MedicalRecord.objects.create(pet=self.pet, veterinarian=self.user,
                                              organization=self.org,
                                              status=MedicalRecord.Status.OPEN)
        used = MedicalRecordService.objects.create(medical_record=record, service=self.service,
                                                   quantity=Decimal('1'), organization=self.org)
        record_clinical_charge_delta(used, delta=Decimal('1'), user=self.user,
                                     mutation_key=f'reprice-test-{record.pk}')
        return record, used

    def _close(self, record):
        record.status = MedicalRecord.Status.CLOSED
        record.closed_at = timezone.now()
        record.save(update_fields=['status', 'closed_at', 'updated_at'])
        return get_or_create_primary_checkout_for_medical_record(record, owner=self.user)

    def _reprice(self, used, key):
        return reprice_clinical_charge(
            used, self.user, new_unit_price=Decimal('130.00'), reason='correction',
            expected_quantity=Decimal('1'), idempotency_key=key,
        )

    def test_reprice_after_close_is_rejected_with_zero_writes(self):
        record, used = self._record_with_service()
        checkout = self._close(record)

        with self.assertRaises(ValidationError):
            self._reprice(used, 'reprice-closed')

        entries = ClinicalChargeEntry.all_objects.filter(medical_record=record)
        self.assertEqual(list(entries.values_list('lifecycle', 'unit_price')),
                         [('active', Decimal('100.00'))])
        self.assertFalse(CommandReceipt.objects.filter(idempotency_key='reprice-closed').exists())
        checkout = get_or_create_primary_checkout_for_medical_record(record, owner=self.user)
        self.assertEqual([(i.quantity, i.unit_price) for i in checkout.items.all()],
                         [(Decimal('1.00'), Decimal('100.00'))])

    def test_reprice_while_open_still_governs_the_close_snapshot(self):
        record, used = self._record_with_service()
        successor = self._reprice(used, 'reprice-open')
        self.assertEqual(successor.unit_price, Decimal('130.00'))
        checkout = self._close(record)
        line = checkout.items.get()
        self.assertEqual((line.quantity, line.unit_price), (Decimal('1.00'), Decimal('130.00')))
