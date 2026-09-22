"""B8B domain contract, written before the real adapter."""
from dataclasses import replace
from datetime import date, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments.creation import (
    AppointmentCommand, CreationRejected, create_appointment, schedule_windows,
)
from apps.appointments.models import Appointment
from apps.organizations.models import OrganizationSchedule
from .test_no_overlap import _seed


class CreationDomainTests(TestCase):
    def setUp(self):
        self.org, self.admin, self.vet, self.luna, self.max = _seed('B8B domain', 'b8b')
        self.day = (timezone.now() + timedelta(days=3)).date()
        self.schedule, _ = OrganizationSchedule.objects.update_or_create(
            organization=self.org, weekday=self.day.isoweekday(), defaults={
                'is_closed': False, 'opens_at': time(8), 'closes_at': time(20),
                'has_break': False})
        self.command = AppointmentCommand(self.org.pk, self.luna.pk, self.vet.pk,
            self.day, time(10), time(10, 45), 'Consulta exacta')

    def create(self, **overrides):
        return create_appointment(replace(self.command, **overrides), require_schedule=True)

    def rejected(self, reason, **overrides):
        with self.assertRaises(CreationRejected) as caught:
            self.create(**overrides)
        self.assertEqual(caught.exception.reason, reason)

    def test_exact_interval_defaults_and_utc(self):
        appt = self.create()
        self.assertEqual((appt.pet_id, appt.veterinarian_id, appt.organization_id),
                         (self.luna.pk, self.vet.pk, self.org.pk))
        self.assertEqual((appt.status, appt.reason, appt.walk_in),
                         ('scheduled', 'Consulta exacta', False))
        self.assertEqual(appt.end_datetime - appt.start_datetime, timedelta(minutes=45))
        self.assertEqual(appt.start_datetime.hour, 10)

    def test_partial_overlap_both_directions_same_start_and_adjacency(self):
        self.create()
        for start, end in ((time(9, 45), time(10, 15)), (time(10, 30), time(11)),
                           (time(10), time(10, 30)), (time(9), time(12))):
            with self.subTest(start=start):
                self.rejected('slot_unavailable', pet_id=self.max.pk, start_time=start, end_time=end)
        self.create(pet_id=self.max.pk, start_time=time(10, 45), end_time=time(11))

    def test_blocking_statuses_are_the_existing_domain_contract(self):
        for status in ('scheduled', 'confirmed', 'in_progress', 'done', 'canceled', 'no_show'):
            with self.subTest(status=status):
                appt = self.create()
                Appointment.all_objects.filter(pk=appt.pk).update(status=status)
                if status in ('scheduled', 'confirmed', 'in_progress'):
                    self.rejected('slot_unavailable', pet_id=self.max.pk)
                else:
                    other = self.create(pet_id=self.max.pk)
                    Appointment.all_objects.filter(pk=other.pk).update(status='canceled')
                Appointment.all_objects.filter(pk=appt.pk).update(status='canceled')

    def test_schedule_closed_missing_outside_and_break(self):
        self.rejected('schedule_closed', start_time=time(7), end_time=time(8))
        self.rejected('schedule_closed', start_time=time(19, 45), end_time=time(20, 15))
        self.schedule.has_break = True
        self.schedule.break_start, self.schedule.break_end = time(10, 30), time(11)
        self.schedule.save()
        self.rejected('schedule_closed')
        self.assertEqual(schedule_windows(self.schedule), ((time(8), time(10, 30)), (time(11), time(20))))
        self.schedule.is_closed = True
        self.schedule.save()
        self.rejected('schedule_closed')
        self.schedule.delete()
        self.rejected('schedule_closed')

    def test_no_vet_retains_human_nullable_resource_semantics(self):
        self.create(veterinarian_id=None)
        self.create(veterinarian_id=None, pet_id=self.max.pk)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_timezone_conversion_and_dst_fail_closed(self):
        self.org.timezone = 'America/Mexico_City'
        self.org.save()
        self.assertEqual(self.create().start_datetime.hour, 16)
        self.org.timezone = 'America/New_York'
        self.org.save()
        for day, start in ((date(2030, 3, 10), time(2, 15)), (date(2030, 11, 3), time(1, 15))):
            with self.subTest(day=day):
                self.rejected('invalid_local_time', date=day, start_time=start,
                              end_time=start.replace(minute=45))

    def test_human_endpoint_still_creates_without_operation_and_preserves_manual_hours(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post('/api/appointments/', dict(pet=self.luna.pk,
            veterinarian=self.vet.pk, date=self.day.isoformat(), start_time='21:00',
            end_time='21:30', reason='Manual'), format='json')
        self.assertEqual(response.status_code, 201, response.content)
        appt = Appointment.objects.get(public_id=response.data['public_id'])
        self.assertIsNone(appt.source_operation_id)
        self.assertNotIn('source_operation', response.data)
