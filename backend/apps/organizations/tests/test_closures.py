"""Cierres excepcionales del horario (ADR p70 D6, plan F2.1).

- Un cierre vigente bloquea al agente: no ofrece huecos, no agenda ni reagenda
  y «¿abierto ahora?» responde que no. El personal solo recibe un aviso.
- Reglas como las ausencias de p67: hasta 366 días, no terminado, sin cruzarse
  (409 `closure_overlap`); cancelar no borra y reabre los días.
- Registrar un cierre y agendar con el agente ese día se serializan sobre la
  fila del horario (entrelazado forzado en los dos órdenes).
"""
import threading
import time as clock
import traceback
from datetime import time, timedelta
from unittest import mock

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.agent import clinic_context
from apps.agent.models import AgentSettings
from apps.agent.tier0 import T0_AFTER_HOURS_SUFFIX, render_first_reply
from apps.appointments import creation as appointment_creation
from apps.appointments.creation import AppointmentCommand, CreationRejected, create_appointment
from apps.appointments.models import Appointment
from apps.core.datetime_utils import org_today_local
from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.organizations import services as org_services
from apps.organizations.models import (
    Organization, OrganizationClosure, OrganizationConfigEvent, OrganizationSchedule,
)
from apps.organizations.services import cancel_closure, create_closure, is_closed_on
from apps.patients.models import Owner, Pet
from apps.users.models import User

URL = '/api/organizations/closures/'


def seed(name, suffix, *, codes=('*.*',)):
    org = Organization.objects.create(name=name, timezone='America/Mexico_City')
    role, _ = Role.objects.get_or_create(
        name=f'ROL {suffix}', organization=org, defaults={'is_system_role': False})
    role.permissions.set([Permission.objects.get_or_create(code=code)[0] for code in codes])
    admin = User.objects.create_user(username=f'cl_admin_{suffix}', password='p',
                                     organization=org, role='ADMIN')
    UserRole.objects.get_or_create(user=admin, role=role)
    UserRole.objects.filter(user=admin).exclude(role=role).delete()
    vet = User.objects.create_user(username=f'cl_vet_{suffix}', password='p',
                                   organization=org, role='VET')
    owner = Owner.objects.create(organization=org, name='Ana', phone='5511110004')
    pet = Pet.objects.create(organization=org, owner=owner, name='Luna',
                             species='perro', birth_date='2021-01-01')
    return org, admin, vet, pet


def open_all_day(org, day):
    OrganizationSchedule.objects.update_or_create(
        organization=org, weekday=day.isoweekday(), defaults={
            'is_closed': False, 'opens_at': time(0, 5), 'closes_at': time(23, 55),
            'has_break': False})


class ClosureApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin, cls.vet, cls.pet = seed('Cierres API', 'api')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.get(pk=self.admin.pk))
        self.today = org_today_local(self.org)

    def post(self, start, end, reason='Día festivo'):
        return self.client.post(URL, {'start_date': start.isoformat(), 'end_date': end.isoformat(),
                                      'reason': reason}, format='json')

    def test_registering_a_closure_records_it_and_counts_the_appointments_those_days(self):
        day = self.today + timedelta(days=5)
        Appointment.objects.create(organization=self.org, pet=self.pet, veterinarian=self.vet,
                                   date=day, start_time=time(10), end_time=time(10, 30),
                                   reason='consulta', status='scheduled')
        response = self.post(day, day + timedelta(days=1))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['affected_appointments'], 1)
        self.assertTrue(response.data['is_active'])
        self.assertTrue(is_closed_on(self.org.pk, day))
        event = OrganizationConfigEvent.objects.get(organization=self.org, kind='closure_added')
        self.assertEqual(event.changes['reason'], [None, 'Día festivo'])
        self.assertEqual(event.subject['public_id'], response.data['public_id'])
        # La cita no se movió: el cierre solo avisa al personal (D6 a).
        self.assertEqual(Appointment.objects.get().status, 'scheduled')
        listed = self.client.get(URL).data
        self.assertEqual([c['public_id'] for c in listed], [response.data['public_id']])

    def test_overlapping_closures_are_409(self):
        day = self.today + timedelta(days=3)
        self.assertEqual(self.post(day, day + timedelta(days=2)).status_code, 201)
        response = self.post(day + timedelta(days=1), day + timedelta(days=4))
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'closure_overlap')
        self.assertEqual(OrganizationClosure.objects.count(), 1)

    def test_invalid_dates_and_reason_are_400(self):
        yesterday = self.today - timedelta(days=1)
        cases = [
            (self.today + timedelta(days=2), self.today, 'Festivo', 'end_date'),
            (yesterday - timedelta(days=1), yesterday, 'Festivo', 'end_date'),
            (self.today, self.today + timedelta(days=366), 'Festivo', 'end_date'),
            (self.today, self.today, '   ', 'reason'),
        ]
        for start, end, reason, field in cases:
            response = self.post(start, end, reason)
            self.assertEqual(response.status_code, 400, (start, end, reason))
            self.assertIn(field, response.data['errors'])
        self.assertFalse(OrganizationClosure.objects.exists())

    def test_cancelling_reopens_the_days_and_does_not_delete(self):
        day = self.today + timedelta(days=4)
        public_id = self.post(day, day).data['public_id']
        response = self.client.post(f'{URL}{public_id}/cancel/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_active'])
        self.assertFalse(is_closed_on(self.org.pk, day))
        self.assertTrue(OrganizationClosure.objects.filter(public_id=public_id).exists())
        self.assertEqual(self.client.get(URL).data, [])
        # Repetir no cambia nada ni deja otro evento.
        self.client.post(f'{URL}{public_id}/cancel/')
        self.assertEqual(OrganizationConfigEvent.objects.filter(kind='closure_cancelled').count(), 1)

    def test_each_clinic_sees_and_cancels_only_its_own(self):
        other_org, other_admin, _, _ = seed('Cierres ajenos', 'other')
        other = APIClient()
        other.force_authenticate(other_admin)
        day = self.today + timedelta(days=6)
        public_id = self.post(day, day).data['public_id']
        self.assertEqual(other.get(URL).data, [])
        self.assertEqual(other.post(f'{URL}{public_id}/cancel/').status_code, 404)
        self.assertTrue(is_closed_on(self.org.pk, day))

    def test_only_who_can_edit_the_clinic_manages_closures(self):
        _, viewer, _, _ = seed('Cierres lectura', 'viewer', codes=('organization.retrieve',))
        User.objects.filter(pk=viewer.pk).update(role='VET')
        viewer.refresh_from_db()
        client = APIClient()
        client.force_authenticate(viewer)
        self.assertEqual(client.get(URL).status_code, 403)
        day = self.today + timedelta(days=2)
        response = client.post(URL, {'start_date': day.isoformat(), 'end_date': day.isoformat(),
                                     'reason': 'x'}, format='json')
        self.assertEqual(response.status_code, 403)


class ClosureBlocksTheAgentTests(TestCase):
    """D6 a: el agente no ofrece ni agenda un día cerrado; el personal sí puede."""

    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin, cls.vet, cls.pet = seed('Cierres agente', 'agent')

    def setUp(self):
        self.day = org_today_local(self.org) + timedelta(days=3)
        open_all_day(self.org, self.day)
        self.command = AppointmentCommand(self.org.pk, self.pet.pk, self.vet.pk, self.day,
                                          time(10), time(10, 30), 'Consulta')

    def close(self, start, end=None):
        with transaction.atomic():
            return create_closure(actor=self.admin, organization=self.org,
                                  start_date=start, end_date=end or start, reason='Festivo')[0]

    def test_the_agent_offers_no_slots_on_a_closed_day(self):
        self.assertTrue(clinic_context.day_ranges(self.org, self.day))
        closure = self.close(self.day)
        self.assertEqual(clinic_context.day_ranges(self.org, self.day), [])
        # El horario semanal no cambia: solo esa fecha.
        self.assertTrue(clinic_context.weekday_ranges(self.org, self.day.weekday()))
        with transaction.atomic():
            cancel_closure(actor=self.admin, closure=closure)
        self.assertTrue(clinic_context.day_ranges(self.org, self.day))

    def test_the_agent_cannot_book_a_closed_day_but_staff_can(self):
        self.close(self.day)
        with self.assertRaises(CreationRejected) as ctx:
            create_appointment(self.command, require_schedule=True)
        self.assertEqual(ctx.exception.default_code, 'schedule_closed')
        # El personal (sin `require_schedule`) agenda igual: solo se le avisa.
        create_appointment(self.command)
        self.assertEqual(Appointment.objects.filter(date=self.day).count(), 1)

    def test_a_closure_today_means_closed_now(self):
        today = org_today_local(self.org)
        open_all_day(self.org, today)
        settings = AgentSettings(organization=self.org, enabled=True)
        self.assertNotIn(T0_AFTER_HOURS_SUFFIX.strip(), render_first_reply(settings, self.org))
        self.close(today)
        self.assertTrue(clinic_context.closed_today(self.org))
        self.assertIn(T0_AFTER_HOURS_SUFFIX.strip(), render_first_reply(settings, self.org))


class ClosureConcurrencyTests(TransactionTestCase):
    """Entrelazado forzado: la primera transacción se detiene con su bloqueo y la
    segunda espera en `pg_stat_activity`."""

    TIMEOUT = 20

    def setUp(self):
        set_current_user(None)
        self.org, self.admin, self.vet, self.pet = seed('Cierres concurrencia', 'conc')
        self.day = org_today_local(self.org) + timedelta(days=3)
        open_all_day(self.org, self.day)

    def tearDown(self):
        connections.close_all()

    def _wait_for_a_lock_waiter(self, timeout=10):
        deadline = clock.monotonic() + timeout
        with connection.cursor() as cursor:
            while clock.monotonic() < deadline:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()")
                if cursor.fetchone()[0] >= 1:
                    return True
                clock.sleep(0.05)
        return False

    def interleave(self, first, second, *, module, attribute):
        entered, release = threading.Event(), threading.Event()
        claimed = threading.Lock()
        real = getattr(module, attribute)

        def held(*args, **kwargs):
            result = real(*args, **kwargs)
            if claimed.acquire(blocking=False):
                entered.set()
                release.wait(timeout=self.TIMEOUT)
            return result

        outcomes = {}

        def worker(label, call):
            try:
                outcomes[label] = call()
            except BaseException as exc:  # noqa: BLE001 — el resultado se comprueba
                outcomes[label] = exc if isinstance(exc, CreationRejected) else traceback.format_exc()
            finally:
                connections.close_all()

        with mock.patch.object(module, attribute, held):
            t1 = threading.Thread(target=worker, args=('first', first))
            t2 = threading.Thread(target=worker, args=('second', second))
            try:
                t1.start()
                self.assertTrue(entered.wait(timeout=10), 'la primera no llegó al bloqueo')
                t2.start()
                waited = self._wait_for_a_lock_waiter()
                second_still_running = t2.is_alive()
            finally:
                release.set()
                t1.join(timeout=30)
                t2.join(timeout=30)
        self.assertTrue(waited, 'la segunda transacción no esperó ningún bloqueo')
        self.assertTrue(second_still_running, 'la segunda terminó sin esperar a la primera')
        for label, value in outcomes.items():
            self.assertNotIsInstance(value, str, f'{label} falló:\n{value}')
        return outcomes['first'], outcomes['second']

    def agent_books(self):
        command = AppointmentCommand(self.org.pk, self.pet.pk, self.vet.pk, self.day,
                                     time(10), time(10, 30), 'Consulta')
        return lambda: create_appointment(command, require_schedule=True)

    def closes(self):
        admin = User.objects.get(pk=self.admin.pk)
        org = Organization.objects.get(pk=self.org.pk)
        return lambda: create_closure(actor=admin, organization=org, start_date=self.day,
                                      end_date=self.day, reason='Festivo')

    def test_closure_first_then_the_waiting_agent_is_rejected(self):
        (closure, _), booked = self.interleave(self.closes(), self.agent_books(),
                                               module=org_services,
                                               attribute='_lock_schedule_days')
        self.assertTrue(closure.is_active)
        self.assertIsInstance(booked, CreationRejected)
        self.assertEqual(booked.default_code, 'schedule_closed')
        self.assertFalse(Appointment.objects.exists())

    def test_agent_first_then_the_waiting_closure_counts_its_appointment(self):
        booked, (closure, affected) = self.interleave(self.agent_books(), self.closes(),
                                                      module=appointment_creation,
                                                      attribute='opening_windows')
        self.assertIsInstance(booked, Appointment)
        self.assertTrue(closure.is_active)
        self.assertEqual(affected, 1)
