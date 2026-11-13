"""
Tests A3 — protocolo Urgencia: materialización de EmergencyRecord al cerrar.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import EmergencyRecord, MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == 'ADMIN_SAAS':
            continue
        role, _ = Role.objects.get_or_create(
            name=name, organization=org, defaults={'is_system_role': True})
        role.permissions.set(
            [wildcard] if '*.*' in codes
            else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


VALID_EMERGENCY = {
    "arrived_at": "2026-07-11T10:00:00Z",
    "triage_at": "2026-07-11T10:05:00Z",
    "stabilized_at": None,
    "discharged_at": None,
    "triage_level": "orange",
    "airway_status": "normal",
    "breathing_status": "compromised",
    "circulation_status": "normal",
    "chief_complaint": "Dificultad respiratoria aguda",
    "stabilization_actions": "O2 por máscara, vía IV, fluidos",
    "response": "Mejora parcial",
    "discharge_status": "hospitalizacion",
    "reassessment_date": None,
}


class EmergencyMaterializationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org Emerg', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.vet = User.objects.create_user(
            username='vet_em', password='pass1234!', organization=self.org, role='VET',
            license_number='1234567')  # M01 (orden 7): firma la consulta
        UserRole.objects.get_or_create(user=self.vet, role=self.roles['VET'])
        self.owner = Owner.objects.create(name='Dueño E', phone='5550000040', organization=self.org)
        self.pet = Pet.objects.create(name='Toby', species='dog', owner=self.owner, organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(user=self.vet)

    def _make_mr(self, emergency_draft, diagnosis=''):
        return MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.vet, organization=self.org,
            consultation_type='emergency', diagnosis=diagnosis,
            consultation_draft={'emergency': emergency_draft})

    def _close(self, mr):
        return self.client.post(f'/api/medical-records/{mr.public_id}/close/')

    def test_close_materializes_emergency_record(self):
        mr = self._make_mr(VALID_EMERGENCY)   # sin diagnosis ni treatment
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)
        er = EmergencyRecord.objects.get(medical_record=mr)
        self.assertEqual(er.triage_level, 'orange')
        self.assertEqual(er.discharge_status, 'hospitalizacion')
        self.assertEqual(er.breathing_status, 'compromised')
        self.assertEqual(er.chief_complaint, 'Dificultad respiratoria aguda')
        self.assertEqual(er.attended_by_id, self.vet.id)   # server-side
        self.assertEqual(er.protocol_version, 1)

    def test_invalid_triage_before_arrival_rolls_back(self):
        bad = dict(VALID_EMERGENCY)
        bad['triage_at'] = "2026-07-11T09:55:00Z"   # antes de la llegada
        mr = self._make_mr(bad)
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(EmergencyRecord.objects.filter(medical_record=mr).exists())
        mr.refresh_from_db()
        self.assertEqual(mr.status, 'open')

    def test_missing_chief_complaint_rolls_back(self):
        bad = dict(VALID_EMERGENCY)
        bad['chief_complaint'] = ''
        mr = self._make_mr(bad)
        self.assertEqual(self._close(mr).status_code, 400)
        self.assertFalse(EmergencyRecord.objects.filter(medical_record=mr).exists())

    def test_empty_draft_closes_without_record(self):
        mr = self._make_mr({})
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(EmergencyRecord.objects.filter(medical_record=mr).exists())
