"""
Tests — analítica por protocolo (versión LITE, agregación read-only al vuelo).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.medical_records.models import EmergencyRecord, SurgeryRecord, VaccineRecord
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


class ProtocolAnalyticsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Org PA', timezone='UTC', tax_rate=Decimal('0'))
        self.roles = _seed_roles(self.org)
        self.vet = User.objects.create_user(
            username='vet_pa', password='pass1234!', organization=self.org, role='VET')
        UserRole.objects.get_or_create(user=self.vet, role=self.roles['VET'])
        self.owner = Owner.objects.create(name='Dueño PA', phone='5550000050', organization=self.org)
        self.pet = Pet.objects.create(name='Max', species='dog', owner=self.owner, organization=self.org)
        self.client = APIClient()
        self.client.force_authenticate(user=self.vet)

        # 2 cirugías: una con complicaciones, otra "Ninguna".
        SurgeryRecord.objects.create(
            pet=self.pet, organization=self.org, surgery_type='programada', asa_class='II',
            anesthesia_type='general', procedure='Osteosíntesis', wound_class='limpia',
            complications='Ninguna', postop_instructions='Reposo')
        SurgeryRecord.objects.create(
            pet=self.pet, organization=self.org, surgery_type='emergencia', asa_class='III',
            anesthesia_type='general', procedure='Esplenectomía', wound_class='contaminada',
            complications='Hemorragia intraoperatoria', postop_instructions='Vigilancia')

        # 2 urgencias con tiempos.
        now = timezone.now()
        EmergencyRecord.objects.create(
            pet=self.pet, organization=self.org, arrived_at=now,
            triage_at=now + timedelta(minutes=5), discharged_at=now + timedelta(minutes=120),
            triage_level='orange', airway_status='normal', breathing_status='compromised',
            circulation_status='normal', chief_complaint='Disnea',
            stabilization_actions='O2', discharge_status='hospitalizacion')
        EmergencyRecord.objects.create(
            pet=self.pet, organization=self.org, arrived_at=now,
            triage_at=now + timedelta(minutes=15),
            triage_level='red', airway_status='critical', breathing_status='critical',
            circulation_status='critical', chief_complaint='Paro',
            stabilization_actions='RCP', discharge_status='fallecido')

        # 1 vacuna con refuerzo próximo.
        today = timezone.localdate()
        VaccineRecord.objects.create(
            pet=self.pet, organization=self.org, vaccine_name='Rabia',
            application_date=today, next_due_date=today + timedelta(days=20))

    def test_protocol_analytics(self):
        resp = self.client.get('/api/medical-records/protocol-analytics/')
        self.assertEqual(resp.status_code, 200, resp.data)
        d = resp.data

        self.assertEqual(d['surgery']['total'], 2)
        self.assertEqual(d['surgery']['complications_count'], 1)   # "Ninguna" no cuenta
        self.assertEqual(d['surgery']['complication_rate'], 0.5)
        self.assertEqual(d['surgery']['by_type'].get('programada'), 1)
        self.assertEqual(d['surgery']['by_type'].get('emergencia'), 1)

        self.assertEqual(d['emergency']['total'], 2)
        self.assertEqual(d['emergency']['by_triage_level'].get('orange'), 1)
        self.assertEqual(d['emergency']['by_discharge_status'].get('fallecido'), 1)
        self.assertEqual(d['emergency']['avg_door_to_triage_min'], 10.0)   # (5+15)/2
        self.assertEqual(d['emergency']['avg_length_of_stay_min'], 120.0)  # solo la que egresó

        self.assertEqual(d['vaccine']['total'], 1)
        self.assertEqual(d['vaccine']['upcoming_boosters_30d'], 1)

    def test_date_range_filters(self):
        # Rango en el pasado → sin registros.
        resp = self.client.get('/api/medical-records/protocol-analytics/?from=2020-01-01&to=2020-12-31')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['surgery']['total'], 0)
        self.assertEqual(resp.data['emergency']['total'], 0)
