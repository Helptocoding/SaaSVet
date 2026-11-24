"""ADR p67: ausencias de integrantes por días completos.

- Registrar (``staff.manage_absences``, solo ADMIN), validar fechas y cruces,
  responder las citas afectadas sin moverlas y cancelar sin borrar.
- Una ausencia vigente BLOQUEA crear, mover, reactivar y atender sin cita a ese
  veterinario esos días (decisión del PO), para recepción y para el agente.
- La agenda lee las ausencias con ``staff.list``, sin el tipo ni quién la
  registró.
- Una cita y una ausencia concurrentes sobre el mismo veterinario se serializan
  por la fila ``User`` (interleaving forzado).
"""
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone as dt_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.appointments.creation import AppointmentCommand, CreationRejected, create_appointment
from apps.appointments.models import Appointment
from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users import absences as absence_service
from apps.users import services as user_services
from apps.users.models import StaffAbsence, StaffAccessEvent

User = get_user_model()

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name=username.title(), **extra)


def _day(offset):
    return timezone.now().date() + timedelta(days=offset)


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Ausencias', timezone='UTC')
        self.admin = _user(self.org, 'ab_admin', 'ADMIN')
        self.vet = _user(self.org, 'ab_vet', 'VET', license_number='1234567', attends_patients=True)
        self.vet2 = _user(self.org, 'ab_vet2', 'VET', license_number='7654321', attends_patients=True)
        self.assistant = _user(self.org, 'ab_asis', 'ASSISTANT')
        self.owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511116666')
        self.pet = Pet.objects.create(organization=self.org, owner=self.owner, name='Luna',
                                      species='perro', birth_date='2021-01-01')
        self.client.force_authenticate(self.admin)

    def appointment(self, *, day, hour=10, vet=None, status_='scheduled'):
        start = datetime.combine(day, dt_time(hour, 0), tzinfo=dt_tz.utc)
        set_current_user(None)
        return Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=vet or self.vet,
            date=day, start_time=start.time(), end_time=(start + timedelta(minutes=30)).time(),
            start_datetime=start, end_datetime=start + timedelta(minutes=30),
            reason='vacuna', status=status_,
        )

    def absence(self, member=None, start=2, end=4, kind='vacation'):
        return StaffAbsence.objects.create(
            organization=self.org, member=member or self.vet, start_date=_day(start),
            end_date=_day(end), kind=kind, created_by=self.admin)

    def register(self, member=None, **body):
        member = member or self.vet
        return self.client.post(f'/api/staff/{member.public_id}/absences/', body, format='json')


class RegisterAbsenceTests(_Fixtures):
    def test_registers_and_lists_affected_appointments_without_moving_them(self):
        inside = self.appointment(day=_day(3))
        self.appointment(day=_day(6))                       # fuera del rango
        self.appointment(day=_day(3), hour=12, status_='canceled')
        res = self.register(start_date=str(_day(2)), end_date=str(_day(4)), kind='training')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data['absence']['kind'], 'training')
        self.assertEqual([a['public_id'] for a in res.data['affected_appointments']],
                         [str(inside.public_id)])
        affected = res.data['affected_appointments'][0]
        self.assertEqual(affected['expected_state'],
                         {'status': 'scheduled', 'date': str(_day(3)), 'start_time': '10:00'})
        self.assertEqual(Appointment.objects.get(pk=inside.pk).veterinarian_id, self.vet.pk)
        event = StaffAccessEvent.objects.get(member=self.vet)
        self.assertEqual((event.kind, event.changes), ('absence_added', {
            'start_date': str(_day(2)), 'end_date': str(_day(4)), 'kind': 'training'}))

    def test_single_day_absence_starting_today_is_valid(self):
        res = self.register(start_date=str(_day(0)), end_date=str(_day(0)))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(res.data['absence']['kind'], 'other')

    def test_rejects_invalid_dates(self):
        for body in (
            {'start_date': str(_day(4)), 'end_date': str(_day(2))},     # al revés
            {'start_date': str(_day(-5)), 'end_date': str(_day(-1))},   # ya terminó
            {'start_date': str(_day(1)), 'end_date': str(_day(400))},   # más de un año
            {'start_date': str(_day(1)), 'end_date': str(_day(2)), 'kind': 'enfermedad'},
        ):
            res = self.register(**body)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (body, res.content))
        self.assertFalse(StaffAbsence.objects.exists())

    def test_overlapping_absence_is_a_conflict_but_adjacent_or_cancelled_ones_are_not(self):
        self.absence(start=2, end=4)
        res = self.register(start_date=str(_day(4)), end_date=str(_day(6)))
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.content)
        self.assertEqual(res.data['code'], 'absence_overlap')
        res = self.register(start_date=str(_day(5)), end_date=str(_day(6)))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        cancelled = self.absence(member=self.vet2, start=2, end=4)
        cancelled.cancelled_at, cancelled.cancelled_by = timezone.now(), self.admin
        cancelled.save()
        res = self.register(member=self.vet2, start_date=str(_day(3)), end_date=str(_day(3)))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

    def test_only_absence_managers_and_only_active_members_of_the_clinic(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        res = client.post(f'/api/staff/{self.vet2.public_id}/absences/',
                          {'start_date': str(_day(1)), 'end_date': str(_day(1))}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        foreign = _user(Organization.objects.create(name='Otra', timezone='UTC'), 'ab_foreign', 'VET')
        self.assertEqual(self.register(member=foreign, start_date=str(_day(1)),
                                       end_date=str(_day(1))).status_code, status.HTTP_404_NOT_FOUND)
        inactive = _user(self.org, 'ab_inactive', 'VET', is_active=False)
        self.assertEqual(self.register(member=inactive, start_date=str(_day(1)),
                                       end_date=str(_day(1))).status_code, status.HTTP_404_NOT_FOUND)

    def test_an_admin_can_register_their_own_absence(self):
        res = self.register(member=self.admin, start_date=str(_day(1)), end_date=str(_day(1)))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

    def test_only_admin_has_the_permission(self):
        from apps.core.permissions_codes import PERMISSIONS, SENSITIVE_CODES
        self.assertIn('staff.manage_absences', SENSITIVE_CODES)
        self.assertIn('staff.manage_absences', PERMISSIONS['ADMIN'])
        for role in ('VET', 'ASSISTANT', 'AGENT'):
            self.assertNotIn('staff.manage_absences', PERMISSIONS[role])


class CancelAbsenceTests(_Fixtures):
    def test_cancel_keeps_the_row_and_is_idempotent(self):
        absence = self.absence()
        url = f'/api/staff/absences/{absence.public_id}/'
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        absence.refresh_from_db()
        self.assertIsNotNone(absence.cancelled_at)
        self.assertEqual(absence.cancelled_by, self.admin)
        first_cancel = absence.cancelled_at
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_200_OK)
        absence.refresh_from_db()
        self.assertEqual(absence.cancelled_at, first_cancel)
        self.assertEqual(StaffAccessEvent.objects.filter(kind='absence_cancelled').count(), 1)

    def test_only_managers_and_only_their_clinic(self):
        absence = self.absence()
        client = APIClient()
        client.force_authenticate(self.assistant)
        self.assertEqual(client.delete(f'/api/staff/absences/{absence.public_id}/').status_code,
                         status.HTTP_403_FORBIDDEN)
        other = Organization.objects.create(name='Otra C', timezone='UTC')
        other_admin = _user(other, 'ab_other_admin', 'ADMIN')
        other_absence = StaffAbsence.objects.create(
            organization=other, member=other_admin, start_date=_day(1), end_date=_day(1),
            created_by=other_admin)
        self.assertEqual(self.client.delete(f'/api/staff/absences/{other_absence.public_id}/')
                         .status_code, status.HTTP_404_NOT_FOUND)


class ListAbsencesTests(_Fixtures):
    def test_default_range_is_from_today_and_cancelled_ones_are_hidden(self):
        past = self.absence(start=-5, end=-3)
        current = self.absence(start=-1, end=1)
        future = self.absence(member=self.vet2, start=10, end=12)
        cancelled = self.absence(member=self.vet2, start=3, end=4)
        cancelled.cancelled_at, cancelled.cancelled_by = timezone.now(), self.admin
        cancelled.save()
        ids = [a['public_id'] for a in self.client.get('/api/staff/absences/').data]
        self.assertEqual(ids, [str(current.public_id), str(future.public_id)])
        self.assertNotIn(str(past.public_id), ids)

    def test_range_and_member_filters(self):
        self.absence(start=2, end=4)
        b = self.absence(member=self.vet2, start=8, end=9)
        res = self.client.get('/api/staff/absences/', {'from': str(_day(5)), 'to': str(_day(8))})
        self.assertEqual([a['public_id'] for a in res.data], [str(b.public_id)])
        res = self.client.get('/api/staff/absences/', {'member': str(self.vet2.public_id)})
        self.assertEqual([a['public_id'] for a in res.data], [str(b.public_id)])
        bad = self.client.get('/api/staff/absences/', {'from': '24-11-2026'})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reception_sees_who_and_when_but_not_the_kind(self):
        self.absence(kind='leave')
        client = APIClient()
        client.force_authenticate(self.assistant)
        res = client.get('/api/staff/absences/')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(set(res.data[0]), {'public_id', 'member', 'member_public_id',
                                            'start_date', 'end_date'})
        self.assertEqual(res.data[0]['member'], self.vet.pk)
        self.assertEqual(self.client.get('/api/staff/absences/').data[0]['kind_label'], 'Permiso')


class AbsenceBlocksSchedulingTests(_Fixtures):
    """La ausencia bloquea en todas las vías de la agenda humana (PO)."""

    def setUp(self):
        super().setUp()
        self.absence(start=2, end=4)

    def create(self, day, vet=None, hour=10):
        return self.client.post('/api/appointments/', {
            'pet': self.pet.pk, 'veterinarian': (vet or self.vet).pk, 'date': str(day),
            'start_time': f'{hour:02d}:00', 'end_time': f'{hour:02d}:30', 'reason': 'consulta',
        }, format='json')

    def test_create_is_blocked_only_on_absent_days(self):
        res = self.create(_day(3))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'veterinarian_absent')
        self.assertIn('ausencia', res.data['errors']['error'][0])
        self.assertEqual(self.create(_day(5)).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.create(_day(3), vet=self.vet2).status_code, status.HTTP_201_CREATED)

    def test_create_with_patient_is_blocked_and_leaves_no_client_or_pet(self):
        owners, pets = Owner.objects.count(), Pet.objects.count()
        res = self.client.post('/api/appointments/create-with-patient/', {
            'owner_name': 'Nuevo Cliente', 'owner_phone': '5522223333', 'pet_name': 'Max',
            'pet_species': 'canino', 'veterinarian': self.vet.pk, 'date': str(_day(3)),
            'start_time': '10:00', 'end_time': '10:30', 'reason': 'consulta',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data.get('code'), 'veterinarian_absent', res.data)
        self.assertEqual((Owner.objects.count(), Pet.objects.count()), (owners, pets))

    def patch(self, appointment, **changes):
        from apps.appointments.services import current_state
        return self.client.patch(f'/api/appointments/{appointment.public_id}/', {
            **changes, 'expected_state': current_state(appointment)}, format='json')

    def test_moving_into_an_absent_day_or_vet_is_blocked(self):
        appointment = self.appointment(day=_day(6))
        res = self.patch(appointment, date=str(_day(3)))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'veterinarian_absent')
        other = self.appointment(day=_day(3), vet=self.vet2)
        res = self.patch(other, veterinarian=self.vet.pk)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(Appointment.objects.get(pk=other.pk).veterinarian_id, self.vet2.pk)

    def test_editing_an_existing_appointment_on_that_day_without_moving_it_is_allowed(self):
        appointment = self.appointment(day=_day(3))
        res = self.patch(appointment, reason='Cambio de motivo')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    def test_reactivating_on_an_absent_day_is_blocked(self):
        from apps.appointments.services import current_state
        appointment = self.appointment(day=_day(3), status_='canceled')
        res = self.client.patch(f'/api/appointments/{appointment.public_id}/status/', {
            'status': 'scheduled', 'expected_state': current_state(appointment)}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'veterinarian_absent')
        self.assertEqual(Appointment.objects.get(pk=appointment.pk).status, 'canceled')

    def test_walk_in_on_an_absent_day_is_blocked(self):
        self.absence(member=self.vet2, start=0, end=0)
        res = self.client.post('/api/appointments/walk-in/', {
            'veterinarian': self.vet2.pk, 'pet': self.pet.pk, 'reason': 'urgencia'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'veterinarian_absent')
        self.assertFalse(Appointment.objects.filter(veterinarian=self.vet2).exists())

    def test_cancelling_the_absence_unblocks(self):
        absence = StaffAbsence.objects.get(member=self.vet)
        self.client.delete(f'/api/staff/absences/{absence.public_id}/')
        self.assertEqual(self.create(_day(3)).status_code, status.HTTP_201_CREATED)

    def test_agent_creation_command_is_blocked_too(self):
        from django.db import transaction
        command = AppointmentCommand(
            organization_id=self.org.pk, pet_id=self.pet.pk, veterinarian_id=self.vet.pk,
            date=_day(3), start_time=dt_time(10, 0), end_time=dt_time(10, 30), reason='consulta')
        with self.assertRaises(CreationRejected) as ctx, transaction.atomic():
            create_appointment(command)
        self.assertEqual(ctx.exception.reason, 'veterinarian_absent')

    def test_agent_does_not_offer_absent_vets(self):
        from apps.agent.tools import _present_vets
        self.assertEqual(_present_vets(self.org, [self.vet, self.vet2], _day(3)), [self.vet2])
        self.assertEqual(_present_vets(self.org, [self.vet, self.vet2], _day(5)),
                         [self.vet, self.vet2])


class AbsenceVersusAppointmentLockTests(TransactionTestCase):
    """Interleaving forzado: la ausencia se detiene DENTRO de su transacción, ya
    con la fila del veterinario bloqueada. La cita concurrente espera ese
    bloqueo (``pg_stat_activity``) y, al confirmarse la ausencia, la rechaza."""

    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica Ausencia Carrera', timezone='UTC')
        self.admin = User.objects.create(username='alk_admin', organization=self.org, role='ADMIN')
        self.vet = User.objects.create(username='alk_vet', organization=self.org, role='VET',
                                       license_number='1234567', attends_patients=True)
        owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511117777')
        self.pet = Pet.objects.create(organization=self.org, owner=owner, name='Luna',
                                      species='perro', birth_date='2021-01-01')

    def _wait_for_a_lock_waiter(self, timeout=10):
        deadline = time.monotonic() + timeout
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
                if cursor.fetchone()[0] >= 1:
                    return True
                time.sleep(0.05)
        return False

    def test_an_appointment_waits_for_the_absence_and_is_rejected(self):
        from django.db import transaction
        day = _day(3)
        entered, release = threading.Event(), threading.Event()
        real_record = user_services.record_staff_event

        def held_record(**kwargs):
            entered.set()
            release.wait(timeout=20)
            return real_record(**kwargs)

        outcomes = {}

        def run_absence():
            try:
                absence_service.create_absence(
                    actor=User.objects.get(pk=self.admin.pk), member=User.objects.get(pk=self.vet.pk),
                    start_date=day, end_date=day, kind='vacation')
                outcomes['absence'] = 'ok'
            except Exception as exc:
                outcomes['absence'] = exc
            finally:
                connection.close()

        def run_appointment():
            try:
                with transaction.atomic():
                    create_appointment(AppointmentCommand(
                        organization_id=self.org.pk, pet_id=self.pet.pk,
                        veterinarian_id=self.vet.pk, date=day, start_time=dt_time(10, 0),
                        end_time=dt_time(10, 30), reason='consulta'))
                outcomes['appointment'] = 'ok'
            except Exception as exc:
                outcomes['appointment'] = exc
            finally:
                connection.close()

        with mock.patch.object(user_services, 'record_staff_event', held_record):
            t1 = threading.Thread(target=run_absence)
            t2 = threading.Thread(target=run_appointment)
            try:
                t1.start()
                self.assertTrue(entered.wait(timeout=10), 'la ausencia no llegó al bloqueo')
                t2.start()
                waited = self._wait_for_a_lock_waiter()
                still_running = t2.is_alive()
            finally:
                release.set()
                t1.join(timeout=30)
                t2.join(timeout=30)
        self.assertTrue(waited, 'la cita no esperó ningún bloqueo')
        self.assertTrue(still_running, 'la cita terminó sin esperar a la ausencia')
        self.assertEqual(outcomes['absence'], 'ok')
        self.assertIsInstance(outcomes['appointment'], CreationRejected)
        self.assertEqual(outcomes['appointment'].reason, 'veterinarian_absent')
        self.assertFalse(Appointment.objects.filter(veterinarian=self.vet).exists())
