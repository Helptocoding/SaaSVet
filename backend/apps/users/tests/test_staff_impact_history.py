"""ADR p66: impacto antes de desactivar e historial de accesos.

- ``GET /api/staff/<uuid>/impact/``: citas por atender, consultas abiertas y caja
  abierta, cada conteo desde su dominio. Solo para quien gestiona personal.
- Una caja abierta BLOQUEA la desactivación (decisión del PO): 409
  ``open_cash_session``, sin cambios ni evento.
- ``StaffAccessEvent``: alta, edición, cambio de rol, desactivación, reactivación
  y restablecimiento (también el de plataforma) dejan un evento en la misma
  transacción; nunca contraseñas ni correos. De solo inserción.
- ``GET /api/staff/<uuid>/history/``: del más reciente al más antiguo, también de
  inactivos, solo para quien gestiona personal y dentro de la clínica.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.models import Appointment
from apps.cash.services import close_cash_session, open_cash_session
from apps.core.models import set_current_user
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import StaffAccessEvent

User = get_user_model()

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name='Ana', **extra)


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Impacto', timezone='UTC')
        self.admin = _user(self.org, 'ih_admin', 'ADMIN')
        self.vet = _user(self.org, 'ih_vet', 'VET', license_number='1234567', attends_patients=True)
        owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511114444')
        self.pet = Pet.objects.create(organization=self.org, owner=owner, name='Luna',
                                      species='perro', birth_date='2021-01-01')
        self.client.force_authenticate(self.admin)

    def appointment(self, *, days, status_='scheduled', hour=10):
        start = (timezone.now() + timedelta(days=days)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        set_current_user(None)
        return Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet,
            date=start.date(), start_time=start.time(),
            end_time=(start + timedelta(minutes=30)).time(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason='vacuna', status=status_,
        )


class ImpactTests(_Fixtures):
    def url(self, member):
        return f'/api/staff/{member.public_id}/impact/'

    def test_counts_only_what_is_pending(self):
        self.appointment(days=2)
        self.appointment(days=3, status_='confirmed', hour=12)
        self.appointment(days=4, status_='canceled', hour=14)
        self.appointment(days=-2, hour=9)  # ya pasó
        MedicalRecord.objects.create(organization=self.org, pet=self.pet, veterinarian=self.vet)
        res = self.client.get(self.url(self.vet))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data, {
            'upcoming_appointments': 2, 'open_medical_records': 1, 'open_cash_session': False,
        })

    def test_reports_an_open_cash_session(self):
        open_cash_session(self.vet)
        self.assertTrue(self.client.get(self.url(self.vet)).data['open_cash_session'])

    def test_only_staff_managers_and_only_their_clinic(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        self.assertEqual(client.get(self.url(self.admin)).status_code, status.HTTP_403_FORBIDDEN)
        foreign = _user(Organization.objects.create(name='Otra', timezone='UTC'), 'ih_foreign', 'VET')
        self.assertEqual(self.client.get(self.url(foreign)).status_code, status.HTTP_404_NOT_FOUND)


class OpenCashBlocksDeactivationTests(_Fixtures):
    def test_open_cash_session_blocks_and_closing_it_unblocks(self):
        session = open_cash_session(self.vet)
        res = self.client.delete(f'/api/staff/{self.vet.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.content)
        self.assertEqual(res.data['code'], 'open_cash_session')
        self.assertTrue(User.objects.get(pk=self.vet.pk).is_active)
        self.assertFalse(StaffAccessEvent.objects.filter(member=self.vet, kind='deactivated').exists())

        close_cash_session(session, self.admin, counted_cash='0.00', force=True)
        res = self.client.delete(f'/api/staff/{self.vet.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT, res.content)

    def test_upcoming_appointments_only_warn(self):
        self.appointment(days=2)
        res = self.client.delete(f'/api/staff/{self.vet.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT, res.content)
        # La cita sigue asignada: la reasignación masiva es de la Fase 3.
        self.assertTrue(Appointment.objects.filter(veterinarian=self.vet).exists())


class HistoryTests(_Fixtures):
    def url(self, member):
        return f'/api/staff/{member.public_id}/history/'

    def kinds(self, member):
        return [e['kind'] for e in self.client.get(self.url(member)).data]

    def test_every_staff_operation_leaves_an_event_newest_first(self):
        res = self.client.post('/api/staff/create/', {
            'username': 'ih_new', 'email': 'ih_new@example.com', 'first_name': 'Nueva',
            'role': 'ASSISTANT'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        member = User.objects.get(username='ih_new')
        public_id = member.public_id
        steps = (
            ('patch', f'/api/staff/{public_id}/', {'last_name': 'Pérez'}),
            ('post', f'/api/staff/{public_id}/role/', {'role': 'ADMIN'}),
            ('post', f'/api/staff/{public_id}/reset-password/', {}),
            ('delete', f'/api/staff/{public_id}/', None),
            ('post', f'/api/staff/{public_id}/reactivate/', {}),
        )
        for method, url, body in steps:
            res = getattr(self.client, method)(url, body, format='json')
            self.assertLess(res.status_code, 300, (url, res.content))
        self.assertEqual(self.kinds(member), [
            'reactivated', 'deactivated', 'password_reset', 'role_changed',
            'profile_updated', 'created',
        ])
        created = StaffAccessEvent.objects.get(member=member, kind='created')
        self.assertEqual(created.changes, {'role': 'ASSISTANT', 'attends_patients': False})

    def test_events_carry_no_personal_values_or_secrets(self):
        self.client.patch(f'/api/staff/{self.vet.public_id}/', {'email': 'nuevo.correo@example.com'},
                          format='json')
        reset = self.client.post(f'/api/staff/{self.vet.public_id}/reset-password/')
        body = self.client.get(self.url(self.vet)).content.decode()
        self.assertNotIn('nuevo.correo', body)
        self.assertNotIn(reset.data['temp_password'], body)
        row = self.client.get(self.url(self.vet)).data[0]
        self.assertEqual(set(row), {'kind', 'kind_label', 'created_at', 'actor_name', 'changes'})
        self.assertEqual(row['actor_name'], 'Ana')

    def test_inactive_members_keep_their_history(self):
        self.client.delete(f'/api/staff/{self.vet.public_id}/')
        self.assertEqual(self.kinds(self.vet), ['deactivated'])

    def test_only_staff_managers_and_only_their_clinic(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        self.assertEqual(client.get(self.url(self.admin)).status_code, status.HTTP_403_FORBIDDEN)
        foreign = _user(Organization.objects.create(name='Otra H', timezone='UTC'), 'ih_foreign2', 'VET')
        self.assertEqual(self.client.get(self.url(foreign)).status_code, status.HTTP_404_NOT_FOUND)

    def test_a_rejected_operation_leaves_no_event(self):
        res = self.client.delete(f'/api/staff/{self.admin.public_id}/')  # a sí mismo
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(StaffAccessEvent.objects.exists())

    def test_events_are_append_only(self):
        self.client.delete(f'/api/staff/{self.vet.public_id}/')
        event = StaffAccessEvent.objects.get(member=self.vet)
        event.kind = 'created'
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()
        self.assertEqual(StaffAccessEvent.objects.get(member=self.vet).kind, 'deactivated')


@FAST_HASHER
class PlatformResetRecordsAnEventTests(APITestCase):
    def test_platform_reset_is_in_the_clinic_history(self):
        from apps.platform.services.platform_reset_password import platform_reset_password
        set_current_user(None)
        org = Organization.objects.create(name='Clinica Plataforma', timezone='UTC')
        member = _user(org, 'ih_plat', 'VET', license_number='1234567')
        operator = User.objects.create_user(username='ih_operator', password='x', role='ADMIN_SAAS',
                                            is_superuser=True, is_staff=True)
        platform_reset_password(actor=operator, target_user=member)
        event = StaffAccessEvent.objects.get(member=member)
        self.assertEqual((event.kind, event.actor, event.changes),
                         ('password_reset', operator, {'source': 'platform'}))
