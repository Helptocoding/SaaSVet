"""H-3: una sola validación de pertenencia, con el mismo contrato en todas las apps.

Cada caso recorre el validador real de cada serializer. Lo que se fija: el rechazo
entre clínicas, el mensaje y la forma de error de cada campo (no debían cambiar), el
registro del intento, y que un actor sin organización se rechace en todas por igual.
"""
from pathlib import Path
import re
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.appointments.serializers import AppointmentSerializer
from apps.billing.serializers import InvoiceSerializer
from apps.core.tenant_validation import require_same_organization, same_organization
from apps.inventory.serializers import MedicalRecordProductSerializer
from apps.medical_records.serializers import MedicalRecordSerializer, VaccineRecordSerializer
from apps.medical_records.tests.test_pdf import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.serializers import PrescriptionSerializer

ACCESS = 'Acceso inválido.'
LOGGER = 'apps.tenant_validation'
EVENT = 'TENANT_VALIDATION_REJECTED'
APPS = Path(__file__).resolve().parents[2]


def resource(org_id, pk=99):
    return SimpleNamespace(organization_id=org_id, pk=pk)


def actor_request(org_id):
    return SimpleNamespace(
        user=SimpleNamespace(organization_id=org_id, pk=1), path='/x/', method='POST')


# (serializer, validador, campo registrado, mensaje que el campo ya devolvía)
FIELD_VALIDATORS = [
    (AppointmentSerializer, 'validate_pet', 'pet', 'Mascota fuera de tu organización'),
    (AppointmentSerializer, 'validate_veterinarian', 'veterinarian', 'Veterinario fuera de tu organización'),
    (MedicalRecordProductSerializer, 'validate_presentation', 'presentation', ACCESS),
    (MedicalRecordProductSerializer, 'validate_lot', 'lot', 'Lote fuera de tu organización.'),
    (MedicalRecordSerializer, 'validate_pet', 'pet', ACCESS),
    (MedicalRecordSerializer, 'validate_appointment', 'appointment', ACCESS),
    (MedicalRecordSerializer, 'validate_veterinarian', 'veterinarian', ACCESS),
    (VaccineRecordSerializer, 'validate_pet', 'pet', ACCESS),
    (VaccineRecordSerializer, 'validate_medical_record', 'medical_record', ACCESS),
    (PrescriptionSerializer, 'validate_medical_record', 'medical_record', ACCESS),
    (PrescriptionSerializer, 'validate_pet', 'pet', ACCESS),
    (InvoiceSerializer, 'validate_owner', 'owner', ACCESS),
    (InvoiceSerializer, 'validate_pet', 'pet', ACCESS),
    (InvoiceSerializer, 'validate_appointment', 'appointment', ACCESS),
]


class SameContractInEveryApp(SimpleTestCase):
    def _call(self, serializer_class, method, request, value):
        return getattr(serializer_class(context={'request': request}), method)(value)

    def test_other_tenant_is_rejected_with_its_message_and_logged(self):
        for serializer_class, method, field, message in FIELD_VALIDATORS:
            with self.subTest(serializer=serializer_class.__name__, method=method):
                with self.assertLogs(LOGGER, 'WARNING') as logs:
                    with self.assertRaises(serializers.ValidationError) as caught:
                        self._call(serializer_class, method, actor_request(1), resource(2))
                self.assertEqual(caught.exception.detail[0], message)
                record = logs.records[0]
                self.assertEqual(record.getMessage(), EVENT)
                self.assertEqual(record.serializer, serializer_class.__name__)
                self.assertEqual(record.field, field)
                self.assertEqual((record.user_org_id, record.resource_org_id), (1, 2))

    def test_own_tenant_passes_without_logging(self):
        for serializer_class, method, _field, _message in FIELD_VALIDATORS:
            with self.subTest(serializer=serializer_class.__name__, method=method):
                value = resource(1)
                with self.assertNoLogs(LOGGER, 'WARNING'):
                    self.assertIs(self._call(serializer_class, method, actor_request(1), value), value)

    def test_actor_without_organization_is_rejected_everywhere(self):
        for serializer_class, method, _field, message in FIELD_VALIDATORS:
            with self.subTest(serializer=serializer_class.__name__, method=method):
                with self.assertLogs(LOGGER, 'WARNING'):
                    with self.assertRaises(serializers.ValidationError) as caught:
                        self._call(serializer_class, method, actor_request(None), resource(2))
                self.assertEqual(caught.exception.detail[0], message)


class HelperContract(SimpleTestCase):
    def test_missing_optional_reference_is_not_checked(self):
        with self.assertNoLogs(LOGGER, 'WARNING'):
            self.assertIsNone(require_same_organization(None, actor_request(1), field='f', serializer='S'))

    def test_resource_without_organization_is_rejected(self):
        with self.assertLogs(LOGGER, 'WARNING'):
            self.assertFalse(same_organization(resource(None), actor_request(1), field='f', serializer='S'))

    def test_two_missing_organizations_are_not_a_match(self):
        with self.assertLogs(LOGGER, 'WARNING'):
            self.assertFalse(same_organization(resource(None), actor_request(None), field='f', serializer='S'))

    def test_missing_request_is_a_programming_error(self):
        with self.assertRaises(AssertionError):
            same_organization(resource(1), None, field='f', serializer='S')


class RejectionThroughTheRealApi(TestCase):
    """Mismo estado HTTP y misma forma de error que antes, y ahora con registro."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica A', timezone='UTC')
        other = Organization.objects.create(name='Clinica B', timezone='UTC')
        cls.vet = _make_user('vet_tenant', cls.org, 'VET')
        cls.foreign_vet = _make_user('vet_foreign', other, 'VET')
        owner = Owner.objects.create(name='Ana', phone='5512345678', organization=cls.org)
        cls.pet = Pet.objects.create(name='Luna', species='cat', owner=owner, organization=cls.org,
                                     birth_date='2020-01-01')
        foreign_owner = Owner.objects.create(name='Eva', phone='5598765432', organization=other)
        cls.foreign_pet = Pet.objects.create(name='Kira', species='dog', owner=foreign_owner,
                                             organization=other, birth_date='2020-01-01')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.vet)

    def _assert_rejected(self, url, payload, field, message):
        with self.assertLogs(LOGGER, 'WARNING') as logs:
            response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data['errors'][field], [message])
        self.assertEqual(logs.records[0].getMessage(), EVENT)
        self.assertEqual(logs.records[0].field, field)

    def test_appointment_with_a_pet_of_another_clinic(self):
        self._assert_rejected('/api/appointments/', {
            'pet': self.foreign_pet.pk, 'veterinarian': self.vet.pk, 'date': '2030-01-15',
            'start_time': '10:00', 'end_time': '10:30', 'reason': 'x',
        }, 'pet', 'Mascota fuera de tu organización')

    def test_appointment_with_a_vet_of_another_clinic(self):
        self._assert_rejected('/api/appointments/', {
            'pet': self.pet.pk, 'veterinarian': self.foreign_vet.pk, 'date': '2030-01-15',
            'start_time': '10:00', 'end_time': '10:30', 'reason': 'x',
        }, 'veterinarian', 'Veterinario fuera de tu organización')

    def test_medical_record_with_a_pet_of_another_clinic(self):
        self._assert_rejected('/api/medical-records/', {
            'pet': self.foreign_pet.pk, 'veterinarian': self.vet.pk,
        }, 'pet', ACCESS)


class NoNewAdHocTenantChecks(SimpleTestCase):
    """Una comparación nueva a mano volvería a perder el registro del intento."""

    AD_HOC = re.compile(r"organization(?:_id)?\s*!=\s*[^\n]*\buser\b")

    def test_serializers_use_the_shared_validation(self):
        offenders = []
        for path in APPS.glob('*/serializers.py'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if self.AD_HOC.search(line):
                    offenders.append(f'{path.parent.name}/{path.name}:{number}: {line.strip()}')
        self.assertEqual(offenders, [])

    def test_local_copies_of_the_helper_are_gone(self):
        for app in ('billing', 'prescriptions'):
            with self.subTest(app=app):
                self.assertNotIn('_validate_same_org', (APPS / app / 'serializers.py').read_text(encoding='utf-8'))
