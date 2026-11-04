"""Regresión audit run-1, hallazgo 8.4: vincular el paciente real a una atención
sin cita debe funcionar también con la consulta ya abierta.

`assign-patient` movía `MedicalRecord.pet` con un `update()` sin tocar
`subject_snapshot`; el trigger de integridad `billing.0041` rechaza esa fila
(`snapshot_pet_mismatch`) y el endpoint respondía 500. Ningún test cubría la
combinación.
"""
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.appointments.tests.test_preconditions import PreconditionTestBase
from apps.medical_records.models import MedicalRecord
from apps.patients.utils import get_or_create_generic_patient
from apps.prescriptions.models import Prescription


class AssignPatientWithOpenRecordTests(PreconditionTestBase):
    def _walk_in_on_generic(self, days):
        _, generic_pet = get_or_create_generic_patient(self.org)
        appt = self._create_appt(days=days, hour=11)
        Appointment.objects.filter(pk=appt.pk).update(pet=generic_pet)
        appt.refresh_from_db()
        return appt, generic_pet

    def _assign(self, appt):
        return self.client.patch(
            f"/api/appointments/{appt.public_id}/assign-patient/",
            {"pet": self.pet.id, "expected_state": self._state_of(appt)},
            format="json",
        )

    def test_open_record_and_its_prescription_follow_the_real_patient(self):
        appt, generic_pet = self._walk_in_on_generic(days=5)
        record = MedicalRecord.objects.create(organization=self.org, pet=generic_pet,
                                              appointment=appt)
        rx = Prescription.objects.create(organization=self.org, medical_record=record,
                                         pet=generic_pet)
        self.assertEqual(record.subject_snapshot['pet']['uuid'], str(generic_pet.public_id))

        response = self._assign(appt)

        self.assertEqual(response.status_code, 200, response.content[:300])
        record.refresh_from_db()
        rx.refresh_from_db()
        for document in (record, rx):
            with self.subTest(document=type(document).__name__):
                self.assertEqual(document.pet_id, self.pet.pk)
                self.assertEqual(document.subject_snapshot['pet']['uuid'], str(self.pet.public_id))
                self.assertEqual(document.subject_snapshot['pet']['name'], self.pet.name)
                self.assertEqual(document.subject_snapshot['owner']['uuid'],
                                 str(self.pet.owner.public_id))

    def test_closed_record_is_left_untouched(self):
        appt, generic_pet = self._walk_in_on_generic(days=6)
        record = MedicalRecord.objects.create(organization=self.org, pet=generic_pet,
                                              appointment=appt)
        MedicalRecord.objects.filter(pk=record.pk).update(
            status=MedicalRecord.Status.CLOSED, closed_at=timezone.now())
        frozen = MedicalRecord.objects.get(pk=record.pk).subject_snapshot

        response = self._assign(appt)

        self.assertEqual(response.status_code, 200, response.content[:300])
        record.refresh_from_db()
        self.assertEqual(record.pet_id, generic_pet.pk)
        self.assertEqual(record.subject_snapshot, frozen)

    def test_without_record_still_links(self):
        appt, _ = self._walk_in_on_generic(days=7)
        self.assertEqual(self._assign(appt).status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.pet_id, self.pet.pk)


class GenericRelinkTriggerBoundaryTests(PreconditionTestBase):
    """billing.0043 abre UNA excepción a la inmutabilidad del snapshot. Estas
    pruebas escriben por debajo de la vista para comprobar que la base no
    permite nada más."""

    def _rewrite(self, record_pk, pet):
        from django.db import IntegrityError, transaction
        from apps.core.subject_history import snapshot
        try:
            with transaction.atomic():
                MedicalRecord.objects.filter(pk=record_pk).update(
                    pet=pet, subject_snapshot=snapshot(organization=self.org, pet=pet))
        except IntegrityError as exc:
            return str(exc).splitlines()[0]
        return 'ok'

    def test_real_identity_stays_immutable_even_on_an_open_record(self):
        from apps.patients.models import Pet
        record = MedicalRecord.objects.create(organization=self.org, pet=self.pet)
        other = Pet.objects.create(organization=self.org, owner=self.pet.owner,
                                   name='Otra', species='dog', birth_date='2020-01-01')
        self.assertIn('immutable_subject_snapshot', self._rewrite(record.pk, other))

    def test_generic_identity_on_a_closed_record_stays_immutable(self):
        _, generic_pet = get_or_create_generic_patient(self.org)
        record = MedicalRecord.objects.create(organization=self.org, pet=generic_pet)
        MedicalRecord.objects.filter(pk=record.pk).update(
            status=MedicalRecord.Status.CLOSED, closed_at=timezone.now())
        self.assertIn('immutable_subject_snapshot', self._rewrite(record.pk, self.pet))

    def test_generic_identity_on_an_open_record_may_be_relinked(self):
        _, generic_pet = get_or_create_generic_patient(self.org)
        record = MedicalRecord.objects.create(organization=self.org, pet=generic_pet)
        self.assertEqual(self._rewrite(record.pk, self.pet), 'ok')

    def test_relinked_snapshot_must_still_match_the_row_pet(self):
        from django.db import IntegrityError, transaction
        from apps.core.subject_history import snapshot
        _, generic_pet = get_or_create_generic_patient(self.org)
        record = MedicalRecord.objects.create(organization=self.org, pet=generic_pet)
        with self.assertRaisesMessage(IntegrityError, 'snapshot_pet_mismatch'):
            with transaction.atomic():
                MedicalRecord.objects.filter(pk=record.pk).update(
                    subject_snapshot=snapshot(organization=self.org, pet=self.pet))
