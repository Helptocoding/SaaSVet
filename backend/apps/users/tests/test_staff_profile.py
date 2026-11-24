"""ADR p67: ficha del integrante — datos y citas por atender.

- ``GET /api/staff/<uuid>/profile/``: los datos del integrante, también si está
  inactivo. Solo para quien gestiona personal.
- ``GET /api/staff/<uuid>/appointments/``: citas programadas o confirmadas aún
  no empezadas, con su ``expected_state`` (INV-A) para reasignarlas.
"""
from datetime import datetime, time as dt_time, timedelta, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.models import Appointment
from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name=username.title(), **extra)


def _day(offset):
    return timezone.now().date() + timedelta(days=offset)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StaffProfileTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        self.org = Organization.objects.create(name='Clinica Ficha', timezone='UTC')
        self.admin = _user(self.org, 'fi_admin', 'ADMIN')
        self.vet = _user(self.org, 'fi_vet', 'VET', license_number='1234567', attends_patients=True)
        owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511119999')
        self.pet = Pet.objects.create(organization=self.org, owner=owner, name='Luna',
                                      species='perro', birth_date='2021-01-01')
        self.client.force_authenticate(self.admin)

    def appointment(self, day, hour=10, status_='scheduled'):
        start = datetime.combine(_day(day), dt_time(hour, 0), tzinfo=dt_tz.utc)
        set_current_user(None)
        return Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet, date=start.date(),
            start_time=start.time(), end_time=(start + timedelta(minutes=30)).time(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason='vacuna', status=status_)

    def test_profile_includes_inactive_members(self):
        User.objects.filter(pk=self.vet.pk).update(is_active=False)
        res = self.client.get(f'/api/staff/{self.vet.public_id}/profile/')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual((res.data['public_id'], res.data['is_active'], res.data['attends_patients']),
                         (str(self.vet.public_id), False, True))
        self.assertIn('access', res.data)

    def test_upcoming_appointments_with_their_precondition(self):
        later = self.appointment(4)
        sooner = self.appointment(2, status_='confirmed')
        self.appointment(3, status_='canceled')
        self.appointment(-2)
        res = self.client.get(f'/api/staff/{self.vet.public_id}/appointments/')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual([a['public_id'] for a in res.data],
                         [str(sooner.public_id), str(later.public_id)])
        first = res.data[0]
        self.assertEqual((first['pet_name'], first['owner_name'], first['start_time']),
                         ('Luna', 'Ana', '10:00'))
        self.assertEqual(first['expected_state'],
                         {'status': 'confirmed', 'date': str(_day(2)), 'start_time': '10:00'})
        ranged = self.client.get(f'/api/staff/{self.vet.public_id}/appointments/',
                                 {'from': str(_day(3)), 'to': str(_day(5))})
        self.assertEqual([a['public_id'] for a in ranged.data], [str(later.public_id)])
        bad = self.client.get(f'/api/staff/{self.vet.public_id}/appointments/',
                              {'from': str(_day(5)), 'to': str(_day(3))})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_staff_managers_and_only_their_clinic(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        for path in ('profile', 'appointments'):
            self.assertEqual(client.get(f'/api/staff/{self.admin.public_id}/{path}/').status_code,
                             status.HTTP_403_FORBIDDEN)
        foreign = _user(Organization.objects.create(name='Otra F', timezone='UTC'), 'fi_f', 'VET')
        for path in ('profile', 'appointments'):
            self.assertEqual(self.client.get(f'/api/staff/{foreign.public_id}/{path}/').status_code,
                             status.HTTP_404_NOT_FOUND)
