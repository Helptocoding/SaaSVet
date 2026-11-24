"""Recepción (ASSISTANT) agenda citas: contrato backend (Fase 1 Equipo, §7).

El frontend de Citas decidía «puede crear» por nombre de rol y dejaba a la
recepción en modo lectura, aunque el RBAC (ADR p63) le concede
``appointment.create``. Corregido allí con ``can()``. Estas pruebas fijan el lado
que de verdad autoriza:

- ASSISTANT crea citas (``POST /api/appointments/``) con sus permisos reales.
- Sin ``appointment.create`` no se crea nada (403), sea cual sea el rol.

La corrección es solo de interfaz: el backend no cambia. Nota del contrato
existente: la atención sin cita (``/walk-in/``) exige ``appointment.create`` a
quien llama y ``appointment.create_walkin`` al veterinario asignado, no a quien
llama; la interfaz la sigue ocultando a recepción (pendiente fuera de esta fase).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.appointments.models import Appointment
from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.core.permissions import user_has_permission_strict
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _slot(days=3):
    day = (timezone.now() + timedelta(days=days)).date().isoformat()
    return day, '10:00', '10:30'


class ReceptionSchedulingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        # Organization.create siembra los roles de sistema y create_user asigna
        # el UserRole por señal: son los permisos reales, no un comodín.
        cls.org = Organization.objects.create(name='Clinica Recepcion', timezone='UTC')
        cls.assistant = User.objects.create_user(
            username='rec_asst', password='x', organization=cls.org, role='ASSISTANT')
        cls.vet = User.objects.create_user(
            username='rec_vet', password='x', organization=cls.org, role='VET',
            license_number='1234567')
        owner = Owner.objects.create(organization=cls.org, name='Ana', phone='5511112222')
        cls.pet = Pet.objects.create(
            organization=cls.org, owner=owner, name='Luna', species='perro',
            birth_date='2021-01-01')

    def setUp(self):
        set_current_user(None)

    def _payload(self):
        date, start, end = _slot()
        return {
            'pet': self.pet.id, 'veterinarian': self.vet.id, 'date': date,
            'start_time': start, 'end_time': end, 'reason': 'vacuna',
        }

    def test_assistant_role_grants_scheduling(self):
        self.assertTrue(user_has_permission_strict(self.assistant, 'appointment.create'))

    def test_assistant_creates_an_appointment(self):
        self.client.force_authenticate(self.assistant)
        res = self.client.post('/api/appointments/', self._payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(Appointment.objects.filter(
            organization=self.org, pet=self.pet, veterinarian=self.vet).exists())

    def test_without_appointment_create_nothing_is_created(self):
        limited = User.objects.create_user(
            username='rec_limited', password='x', organization=self.org, role='ASSISTANT')
        role = Role.objects.create(name='SOLO_LECTURA_CITAS', organization=self.org)
        role.permissions.set([Permission.objects.get_or_create(code='appointment.list')[0]])
        UserRole.objects.filter(user=limited).delete()
        UserRole.objects.create(user=limited, role=role)

        self.client.force_authenticate(limited)
        res = self.client.post('/api/appointments/', self._payload(), format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertFalse(Appointment.objects.filter(organization=self.org, pet=self.pet).exists())
