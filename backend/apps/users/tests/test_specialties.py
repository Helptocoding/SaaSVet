"""ADR p68: especialidad estructurada.

- Un catálogo cerrado, el mismo para integrantes (varias) y servicios (una), con
  copia en el frontend que debe coincidir.
- El alta y la edición de un integrante aceptan solo códigos del catálogo y los
  guardan sin repetir y en su orden; la API devuelve también la etiqueta.
- El texto libre anterior se traduce al catálogo al migrar.
"""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.users.models import StaffAccessEvent
from apps.users.specialties import (
    SPECIALTIES, normalize_specialties, specialties_display, specialties_from_free_text,
)

User = get_user_model()
FRONTEND_CATALOG = (Path(__file__).resolve().parents[4] / 'frontend' / 'src' / 'features'
                    / 'staff' / 'specialties.json')
FAST = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


class CatalogTests(SimpleTestCase):
    def test_frontend_copy_matches_the_backend_catalog(self):
        frontend = json.loads(FRONTEND_CATALOG.read_text(encoding='utf-8'))
        self.assertEqual([tuple(item) for item in frontend], list(SPECIALTIES))

    def test_normalize_orders_dedupes_and_rejects_unknown(self):
        self.assertEqual(normalize_specialties(['surgery', 'general_medicine', 'surgery']),
                         ['general_medicine', 'surgery'])
        with self.assertRaises(ValueError):
            normalize_specialties(['surgery', 'astrologia'])
        self.assertEqual(specialties_display(['general_medicine', 'surgery']),
                         'Medicina general, Cirugía')

    def test_free_text_is_mapped_to_the_catalog(self):
        self.assertEqual(specialties_from_free_text('Cirugía'), ['surgery'])
        self.assertEqual(specialties_from_free_text('Medicina General y Dermatología'),
                         ['general_medicine', 'dermatology'])
        self.assertEqual(specialties_from_free_text('Cirujano / Ortopedia'),
                         ['surgery', 'orthopedics'])
        self.assertEqual(specialties_from_free_text('Ortopedia y traumatología'), ['orthopedics'])
        self.assertEqual(specialties_from_free_text('Etología (comportamiento)'), ['behavior'])
        self.assertEqual(specialties_from_free_text('Acupuntura'), [])
        self.assertEqual(specialties_from_free_text(''), [])


@FAST
class StaffSpecialtiesTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Especialidades', timezone='UTC')
        self.admin = User.objects.create_user(username='sp_admin', password='x',
                                              organization=self.org, role='ADMIN')
        self.client.force_authenticate(self.admin)

    def create(self, **extra):
        return self.client.post('/api/staff/create/', {
            'username': 'sp_vet', 'email': 'sp_vet@example.com', 'first_name': 'Eva',
            'role': 'VET', 'license_number': '1234567', **extra}, format='json')

    def test_create_stores_codes_in_catalog_order_and_exposes_the_label(self):
        res = self.create(specialties=['surgery', 'general_medicine', 'surgery'])
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        member = res.data['member']
        self.assertEqual(member['specialties'], ['general_medicine', 'surgery'])
        self.assertEqual(member['specialty_label'], 'Medicina general, Cirugía')

    def test_unknown_or_free_text_specialties_are_rejected(self):
        for value in (['astrologia'], 'Cirugía'):
            res = self.create(specialties=value)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (value, res.content))
            self.assertIn('specialties', res.data.get('errors', res.data), res.data)
        self.assertFalse(User.objects.filter(username='sp_vet').exists())

    def test_edit_replaces_the_list_and_records_the_field_name(self):
        vet_id = self.create(specialties=['surgery']).data['member']['public_id']
        res = self.client.patch(f'/api/staff/{vet_id}/', {'specialties': ['dermatology']},
                                format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data['specialties'], ['dermatology'])
        event = StaffAccessEvent.objects.get(kind='profile_updated')
        self.assertEqual(event.changes, {'fields': ['specialties']})
        res = self.client.patch(f'/api/staff/{vet_id}/', {'specialties': []}, format='json')
        self.assertEqual(res.data['specialties'], [])


@FAST
class ServiceSpecialtyTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        self.org = Organization.objects.create(name='Clinica Servicios', timezone='UTC')
        self.admin = User.objects.create_user(username='sv_admin', password='x',
                                              organization=self.org, role='ADMIN')
        self.client.force_authenticate(self.admin)

    def test_service_takes_one_specialty_from_the_catalog(self):
        res = self.client.post('/api/billing/services/', {
            'name': 'Consulta dermatológica', 'base_price': '450.00',
            'specialty': 'dermatology'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data['specialty'], 'dermatology')
        res = self.client.post('/api/billing/services/', {
            'name': 'Corte de uñas', 'base_price': '80.00'}, format='json')
        self.assertEqual(res.data['specialty'], '')
        res = self.client.post('/api/billing/services/', {
            'name': 'Astrología', 'base_price': '80.00', 'specialty': 'astrologia'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
