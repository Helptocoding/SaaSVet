"""
Tests A3 — protocolo Cirugía: materialización de SurgeryRecord al cerrar + registry.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import MedicalRecord, SurgeryRecord
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


VALID_SURGERY = {
    "preop_diagnosis": "Fractura de tibia",
    "surgery_type": "programada",
    "asa_class": "II",
    "asa_emergency": False,
    "anesthesia_type": "general",
    "procedure": "Osteosíntesis con placa",
    "wound_class": "limpia",
    "findings": "",
    "complications": "Ninguna",
    "postop_instructions": "Reposo 15 días, antibiótico c/12h, retiro de puntos en 12 días",
    "suture_removal_date": None,
}


class SurgeryMaterializationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org Surg', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.vet = User.objects.create_user(
            username='vet_surg', password='pass1234!', organization=self.org, role='VET')
        UserRole.objects.get_or_create(user=self.vet, role=self.roles['VET'])
        self.owner = Owner.objects.create(name='Dueño S', phone='5550000030', organization=self.org)
        self.pet = Pet.objects.create(name='Rex', species='dog', owner=self.owner, organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(user=self.vet)

    def _make_mr(self, surgery_draft):
        return MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.vet, organization=self.org,
            consultation_type='surgery', diagnosis='Fractura tibia',
            consultation_draft={'surgery': surgery_draft})

    def _close(self, mr):
        return self.client.post(f'/api/medical-records/{mr.public_id}/close/')

    def test_close_materializes_surgery_record(self):
        mr = self._make_mr(VALID_SURGERY)
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)
        sr = SurgeryRecord.objects.get(medical_record=mr)
        self.assertEqual(sr.surgery_type, 'programada')
        self.assertEqual(sr.asa_class, 'II')
        self.assertEqual(sr.anesthesia_type, 'general')
        self.assertEqual(sr.procedure, 'Osteosíntesis con placa')
        self.assertEqual(sr.wound_class, 'limpia')
        self.assertEqual(sr.surgeon_id, self.vet.id)   # server-side
        self.assertEqual(sr.protocol_version, 1)

    def test_close_without_treatment_ok(self):
        # Cirugía no exige MedicalRecord.treatment.
        mr = self._make_mr(VALID_SURGERY)
        mr.treatment = ''
        mr.save(update_fields=['treatment'])
        self.assertEqual(self._close(mr).status_code, 200)

    def test_invalid_draft_rolls_back_close(self):
        bad = dict(VALID_SURGERY)
        bad['procedure'] = ''   # obligatorio
        mr = self._make_mr(bad)
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(SurgeryRecord.objects.filter(medical_record=mr).exists())
        mr.refresh_from_db()
        self.assertEqual(mr.status, 'open')   # rollback del cierre

    def test_empty_draft_closes_without_record(self):
        # Cirugía "clásica" sin captura estructurada → cierra sin SurgeryRecord (fallback).
        mr = self._make_mr({})
        resp = self._close(mr)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(SurgeryRecord.objects.filter(medical_record=mr).exists())
