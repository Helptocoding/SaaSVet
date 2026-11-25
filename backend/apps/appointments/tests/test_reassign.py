"""ADR p67: reasignación en bloque de citas por atender a otro veterinario.

Decisión del PO: un destino para todas; cada cita se mueve si el destino está
libre ese día y hora. Las que no se pueden mover se quedan como estaban y se
devuelven con su motivo. Nunca se cambia la fecha ni la hora.
"""
from datetime import datetime, time as dt_time, timedelta, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.appointments.services import current_state
from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import StaffAbsence, StaffAccessEvent

User = get_user_model()
URL = '/api/appointments/reassign/'


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name=username.title(), **extra)


def _day(offset):
    return timezone.now().date() + timedelta(days=offset)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReassignTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        self.org = Organization.objects.create(name='Clinica Reasignar', timezone='UTC')
        self.admin = _user(self.org, 'ra_admin', 'ADMIN')
        self.source = _user(self.org, 'ra_source', 'VET', license_number='1234567',
                            attends_patients=True)
        self.target = _user(self.org, 'ra_target', 'VET', license_number='7654321',
                            attends_patients=True)
        owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511118888')
        self.pet = Pet.objects.create(organization=self.org, owner=owner, name='Luna',
                                      species='perro', birth_date='2021-01-01')
        self.client.force_authenticate(self.admin)

    def appointment(self, *, day=3, hour=10, vet=None, status_='scheduled', org=None, pet=None):
        start = datetime.combine(_day(day), dt_time(hour, 0), tzinfo=dt_tz.utc)
        set_current_user(None)
        return Appointment.objects.create(
            organization=org or self.org, pet=pet or self.pet, veterinarian=vet or self.source,
            date=start.date(), start_time=start.time(),
            end_time=(start + timedelta(minutes=30)).time(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason='vacuna', status=status_,
        )

    def item(self, appointment, **override):
        return {'public_id': str(appointment.public_id),
                'expected_state': {**current_state(appointment), **override}}

    def reassign(self, *appointments, items=None, target=None, source=None, client=None):
        return (client or self.client).post(URL, {
            'source_public_id': str((source or self.source).public_id),
            'target_public_id': str((target or self.target).public_id),
            'appointments': items if items is not None else [self.item(a) for a in appointments],
        }, format='json')

    def vet_of(self, appointment):
        return Appointment.objects.get(pk=appointment.pk).veterinarian_id

    def test_moves_every_free_appointment_keeping_date_and_time(self):
        a = self.appointment(day=2)
        b = self.appointment(day=3, status_='confirmed', hour=12)
        res = self.reassign(a, b)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data, {'moved': [str(a.public_id), str(b.public_id)], 'skipped': []})
        for appt in (a, b):
            row = Appointment.objects.get(pk=appt.pk)
            self.assertEqual((row.veterinarian_id, row.date, row.start_time, row.status),
                             (self.target.pk, appt.date, appt.start_time, appt.status))
        change = AppointmentStatusChange.objects.get(appointment=a)
        self.assertEqual((change.from_status, change.to_status, change.changed_by),
                         ('scheduled', 'scheduled', self.admin))
        self.assertIn('reasignado', change.reason)
        event = StaffAccessEvent.objects.get(member=self.source)
        self.assertEqual((event.kind, event.changes['moved'], event.changes['skipped']),
                         ('appointments_reassigned', 2, 0))

    def test_each_blocked_appointment_is_skipped_with_its_reason(self):
        free = self.appointment(day=2)
        busy = self.appointment(day=3, hour=10)
        self.appointment(day=3, hour=10, vet=self.target)           # ocupa al destino
        absent = self.appointment(day=5)
        StaffAbsence.objects.create(organization=self.org, member=self.target,
                                    start_date=_day(5), end_date=_day(5), created_by=self.admin)
        changed = self.appointment(day=6)
        past = self.appointment(day=-1)
        canceled = self.appointment(day=7, status_='canceled')
        foreign_org = Organization.objects.create(name='Otra R', timezone='UTC')
        foreign = self.appointment(day=8, org=foreign_org, vet=_user(foreign_org, 'ra_f', 'VET'),
                                   pet=Pet.objects.create(
                                       organization=foreign_org, name='Max', species='perro',
                                       birth_date='2020-01-01', owner=Owner.objects.create(
                                           organization=foreign_org, name='B', phone='5599990000')))
        res = self.reassign(items=[
            self.item(free), self.item(busy), self.item(absent),
            self.item(changed, start_time='11:00'), self.item(past), self.item(canceled),
            self.item(foreign),
        ])
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data['moved'], [str(free.public_id)])
        self.assertEqual({s['public_id']: s['code'] for s in res.data['skipped']}, {
            str(busy.public_id): 'slot_taken',
            str(absent.public_id): 'veterinarian_absent',
            str(changed.public_id): 'appointment_changed',
            str(past.public_id): 'not_reassignable',
            str(canceled.public_id): 'not_reassignable',
            str(foreign.public_id): 'not_found',
        })
        for appt in (busy, absent, changed, past, canceled):
            self.assertEqual(self.vet_of(appt), self.source.pk)
        self.assertTrue(all(s['message'] for s in res.data['skipped']))

    def test_an_appointment_already_moved_to_someone_else_counts_as_changed(self):
        appt = self.appointment()
        other = _user(self.org, 'ra_other', 'VET', license_number='1112223', attends_patients=True)
        Appointment.objects.filter(pk=appt.pk).update(veterinarian=other)
        res = self.reassign(appt)
        self.assertEqual(res.data['skipped'][0]['code'], 'appointment_changed')
        self.assertEqual(self.vet_of(appt), other.pk)
        self.assertFalse(StaffAccessEvent.objects.exists())

    def test_repeating_the_request_moves_nothing_twice(self):
        appt = self.appointment()
        body_items = [self.item(appt)]
        self.reassign(items=body_items)
        res = self.reassign(items=body_items)
        self.assertEqual(res.data['moved'], [])
        self.assertEqual(res.data['skipped'][0]['code'], 'appointment_changed')
        self.assertEqual(AppointmentStatusChange.objects.filter(appointment=appt).count(), 1)

    def test_works_for_an_inactive_source(self):
        appt = self.appointment()
        User.objects.filter(pk=self.source.pk).update(is_active=False)
        res = self.reassign(appt)
        self.assertEqual(res.data['moved'], [str(appt.public_id)])

    def test_every_item_needs_its_precondition(self):
        appt = self.appointment()
        res = self.reassign(items=[{'public_id': str(appt.public_id)}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'precondition_required')
        self.assertEqual(self.vet_of(appt), self.source.pk)

    def test_rejects_invalid_requests_without_moving_anything(self):
        appt = self.appointment()
        assistant = _user(self.org, 'ra_asis', 'ASSISTANT')
        inactive = _user(self.org, 'ra_inactive', 'VET', license_number='3334445',
                         attends_patients=True, is_active=False)
        admin_not_clinician = _user(self.org, 'ra_admin2', 'ADMIN')
        for kwargs in (
            {'target': self.source},
            {'target': assistant},
            {'target': inactive},
            {'target': admin_not_clinician},
            {'items': []},
            {'items': [self.item(appt), self.item(appt)]},
            {'items': [self.item(appt)] * 0 + [{'public_id': 'x', 'expected_state': {}}]},
        ):
            res = self.reassign(appt, **kwargs) if 'items' not in kwargs else self.reassign(**kwargs)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (kwargs, res.content))
        self.assertEqual(self.vet_of(appt), self.source.pk)

    def test_caps_the_batch(self):
        from apps.appointments.reassignment import MAX_REASSIGN
        appt = self.appointment()
        items = [self.item(appt)] + [
            {'public_id': f'00000000-0000-4000-8000-{i:012d}',
             'expected_state': current_state(appt)} for i in range(MAX_REASSIGN)]
        res = self.reassign(items=items)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)

    def test_foreign_source_is_not_found_and_the_agent_cannot_reassign(self):
        appt = self.appointment()
        foreign_vet = _user(Organization.objects.create(name='Otra S', timezone='UTC'),
                            'ra_fs', 'VET')
        self.assertEqual(self.reassign(appt, source=foreign_vet).status_code,
                         status.HTTP_404_NOT_FOUND)
        agent = User.objects.create_user(username='ra_agent', password='x', organization=self.org,
                                         role='AGENT', is_service_account=True)
        client = APIClient()
        client.force_authenticate(agent)
        self.assertEqual(self.reassign(appt, client=client).status_code,
                         status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.vet_of(appt), self.source.pk)

    def test_reception_can_reassign(self):
        appt = self.appointment()
        client = APIClient()
        client.force_authenticate(_user(self.org, 'ra_recep', 'ASSISTANT'))
        res = self.reassign(appt, client=client)
        self.assertEqual(res.data['moved'], [str(appt.public_id)])
