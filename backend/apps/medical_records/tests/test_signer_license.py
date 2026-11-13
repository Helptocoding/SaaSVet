"""M01 (orden 7): quien firma una consulta o una receta necesita cédula.

El firmante es el veterinario de la consulta al cerrarla y quien emite la receta,
sea cual sea su rol. La cédula se congela al cierre y los PDF la muestran.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import Checkout
from apps.inventory.models import Presentation, Product
from apps.medical_records.models import MedicalRecord
from apps.medical_records.tests.test_vitals import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.prescriptions.tests.test_pdf import _extract_pdf_text


class SignerLicenseTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org Firma M01', timezone='UTC')
        cls.vet = _make_user('vet_firma_m01', cls.org, 'VET')
        cls.vet.first_name, cls.vet.last_name = 'Ana', 'Galeno'
        cls.vet.save(update_fields=['first_name', 'last_name'])
        cls.admin = _make_user('adm_firma_m01', cls.org, 'ADMIN')
        cls.admin.first_name, cls.admin.last_name = 'Luis', 'Mora'
        cls.admin.save(update_fields=['first_name', 'last_name'])
        owner = Owner.objects.create(name='Dueña', phone='5512345602', organization=cls.org)
        cls.pet = Pet.objects.create(name='Kira', species='dog', owner=owner, organization=cls.org)
        cls.product = Product.objects.create(
            name='Antibiotico Firma', internal_code='FIRMA1',
            requires_prescription=True, organization=cls.org,
        )
        Presentation.objects.create(
            product=cls.product, name='Frasco', base_unit='bottle',
            sale_price=Decimal('100'), stock=Decimal('20'), organization=cls.org,
        )

    def _set_license(self, user, value):
        user.license_number = value
        user.save(update_fields=['license_number'])

    def _record(self, veterinarian):
        return MedicalRecord.objects.create(
            organization=self.org, pet=self.pet, veterinarian=veterinarian,
            diagnosis='dx', treatment='tx',
        )

    def _close(self, record, actor):
        self.client.force_authenticate(actor)
        return self.client.post(f'/api/medical-records/{record.public_id}/close/')

    def _create_rx(self, record, actor):
        self.client.force_authenticate(actor)
        return self.client.post('/api/prescriptions/', {
            'medical_record': record.pk, 'pet': self.pet.pk, 'notes': 'rx',
            'items': [{'product': self.product.pk, 'dose': '1ml', 'quantity': '1.00'}],
        }, format='json')

    def test_vet_without_license_cannot_close(self):
        record = self._record(self.vet)
        r = self._close(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertIn('license_number', r.data['errors'])
        self.assertIn('Ana Galeno', str(r.data['errors']['license_number']))
        record.refresh_from_db()
        self.assertEqual(record.status, MedicalRecord.Status.OPEN)
        self.assertFalse(Checkout.objects.filter(medical_record=record).exists())

    def test_admin_cannot_close_for_a_vet_without_license(self):
        self._set_license(self.admin, '7654321')
        record = self._record(self.vet)
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        record.refresh_from_db()
        self.assertEqual(record.status, MedicalRecord.Status.OPEN)

    def test_admin_signing_needs_own_license(self):
        record = self._record(self.admin)
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self._set_license(self.admin, '7654321')
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_close_freezes_license_snapshot(self):
        self._set_license(self.vet, '1234567')
        record = self._record(self.vet)
        r = self._close(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        record.refresh_from_db()
        self.assertEqual(record.vet_license_at_close, '1234567')
        self._set_license(self.vet, '7777777')
        pdf = self.client.get(f'/api/medical-records/{record.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        text = _extract_pdf_text(pdf.content)
        self.assertIn('1234567', text)
        self.assertNotIn('7777777', text)

    def test_open_record_pdf_shows_live_license(self):
        self._set_license(self.vet, '2468024')
        record = self._record(self.vet)
        self.client.force_authenticate(self.vet)
        pdf = self.client.get(f'/api/medical-records/{record.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        self.assertIn('2468024', _extract_pdf_text(pdf.content))

    def test_prescription_requires_issuer_license(self):
        record = self._record(self.vet)
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertIn('license_number', r.data['errors'])
        self.assertFalse(Prescription.objects.filter(medical_record=record).exists())
        self.assertFalse(PrescriptionItem.objects.filter(product=self.product).exists())
        self._set_license(self.vet, '1234567')
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

    def test_prescription_pdf_signature_shows_license(self):
        self._set_license(self.vet, '1357913')
        record = self._record(self.vet)
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        rx = Prescription.objects.get(medical_record=record)
        pdf = self.client.get(f'/api/prescriptions/{rx.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        text = _extract_pdf_text(pdf.content)
        self.assertIn('Cédula profesional 1357913', text)
