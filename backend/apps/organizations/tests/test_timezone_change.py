"""Zona horaria protegida (ADR p70 D1).

- La zona se elige de un catálogo cerrado de México; fuera de él, 400.
- Con citas futuras activas el cambio se rechaza (409) sin escribir nada.
- El cambio y toda escritura de cita que calcula instantes se serializan sobre la
  fila de la organización: la cita usa la zona nueva o el cambio ve la cita y se
  rechaza.
- Reactivar una cita cancelada o no presentada cuya zona ya no es la vigente se
  rechaza (409) y la cita sigue como estaba (decisión del PO, opción c). Las pruebas de concurrencia fuerzan los dos órdenes (la primera
  transacción se detiene con el bloqueo tomado y la segunda espera en
  `pg_stat_activity`) y comprueban el estado final en PostgreSQL.
"""
import importlib
import json
import threading
import time
import traceback
from datetime import time as dt_time, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments import services as appointment_services
from apps.appointments import views as appointment_views
from apps.appointments.models import Appointment, AppointmentStatusChange
from apps.appointments.services import current_state
from apps.core.datetime_utils import local_date_time_to_utc, org_today_local
from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.organizations.models import Organization, OrganizationConfigEvent
from apps.organizations.services import change_organization_timezone
from apps.organizations.timezones import MEXICO_TIMEZONES, TIMEZONE_CODES
from apps.patients.models import Owner, Pet
from apps.users.models import User

CENTRO = 'America/Mexico_City'   # UTC-6, sin horario de verano
SURESTE = 'America/Cancun'       # UTC-5: una hora distinta, para que los instantes difieran
ME_URL = '/api/organizations/me/'


def seed(name, suffix, tz=CENTRO):
    """Org con ADMIN (wildcard), un VET con wildcard y una mascota."""
    org = Organization.objects.create(name=name, timezone=tz)
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    role, _ = Role.objects.get_or_create(
        name='ADMIN', organization=org, defaults={'is_system_role': True})
    role.permissions.set([wildcard])
    admin = User.objects.create_user(
        username=f'tz_admin_{suffix}', password='p', organization=org, role='ADMIN')
    UserRole.objects.get_or_create(user=admin, role=role)
    vet = User.objects.create_user(
        username=f'tz_vet_{suffix}', password='p', organization=org, role='VET')
    UserRole.objects.get_or_create(user=vet, role=role)
    owner = Owner.objects.create(organization=org, name='Ana', phone='5511110002')
    pet = Pet.objects.create(organization=org, owner=owner, name='Luna',
                             species='perro', birth_date='2021-01-01')
    return org, admin, vet, pet


def make_appointment(org, vet, pet, *, day, start, end, status='scheduled'):
    return Appointment.objects.create(
        organization=org, pet=pet, veterinarian=vet, date=day,
        start_time=start, end_time=end,
        start_datetime=local_date_time_to_utc(org, day, start),
        end_datetime=local_date_time_to_utc(org, day, end),
        timezone_at_creation=org.timezone, reason='consulta', status=status,
    )


class CatalogTests(TestCase):
    def test_the_frontend_copy_matches_the_backend_catalog(self):
        path = (Path(settings.BASE_DIR).parent / 'frontend' / 'src' / 'features'
                / 'config' / 'timezones.json')
        frontend = [tuple(item) for item in json.loads(path.read_text(encoding='utf-8'))]
        self.assertEqual(frontend, list(MEXICO_TIMEZONES))

    def test_the_migration_copy_matches_the_catalog(self):
        migration = importlib.import_module(
            'apps.organizations.migrations.0017_normalize_timezones_to_catalog')
        self.assertEqual(set(migration.CATALOG), TIMEZONE_CODES)
        self.assertIn(migration.DEFAULT, TIMEZONE_CODES)

    def test_every_zone_of_the_catalog_exists(self):
        for code in TIMEZONE_CODES:
            ZoneInfo(code)


class TimezoneApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin, cls.vet, cls.pet = seed('TZ API', 'api')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.get(pk=self.admin.pk))
        self.today = org_today_local(self.org)

    def patch(self, **data):
        return self.client.patch(ME_URL, data, format='json')

    def test_without_appointments_the_zone_changes_and_is_audited(self):
        response = self.patch(timezone=SURESTE)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['timezone'], SURESTE)
        org = Organization.objects.get(pk=self.org.pk)
        self.assertEqual(org.timezone, SURESTE)
        self.assertIsNotNone(org.timezone_updated_at)
        event = OrganizationConfigEvent.objects.get(organization=org)
        self.assertEqual(event.kind, 'timezone_changed')
        self.assertEqual(event.changes, {'timezone': [CENTRO, SURESTE]})
        self.assertEqual(event.actor_id, self.admin.pk)

    def test_the_session_sees_the_new_zone(self):
        self.assertEqual(self.patch(timezone=SURESTE).status_code, 200)
        me = self.client.get('/api/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['organization_timezone'], SURESTE)

    def test_a_future_active_appointment_blocks_the_change_without_writing(self):
        tomorrow = self.today + timedelta(days=1)
        make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                         start=dt_time(10), end=dt_time(10, 30))
        response = self.patch(timezone=SURESTE, display_name='No debe guardarse')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'timezone_change_blocked')
        self.assertEqual(response.data['future_appointments'], 1)
        self.assertIn('1 cita por atender', response.data['message'])
        org = Organization.objects.get(pk=self.org.pk)
        self.assertEqual(org.timezone, CENTRO)
        self.assertIsNone(org.timezone_updated_at)
        self.assertNotEqual(org.display_name, 'No debe guardarse')
        self.assertFalse(OrganizationConfigEvent.objects.filter(kind='timezone_changed').exists())

    def test_confirmed_and_in_progress_appointments_also_block(self):
        tomorrow = self.today + timedelta(days=1)
        make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                         start=dt_time(9), end=dt_time(9, 30), status='confirmed')
        now_local = timezone.now().astimezone(ZoneInfo(CENTRO))
        # Una atención en curso cuyo fin aún no llega.
        Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet, date=now_local.date(),
            start_time=dt_time(0), end_time=dt_time(23, 59, 59),
            start_datetime=timezone.now() - timedelta(minutes=10),
            end_datetime=timezone.now() + timedelta(minutes=20),
            timezone_at_creation=CENTRO, reason='urgencia', status='in_progress', walk_in=True)
        response = self.patch(timezone=SURESTE)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['future_appointments'], 2)
        self.assertIn('2 citas por atender', response.data['message'])

    def test_past_and_terminal_appointments_do_not_block(self):
        yesterday = self.today - timedelta(days=1)
        tomorrow = self.today + timedelta(days=1)
        make_appointment(self.org, self.vet, self.pet, day=yesterday,
                         start=dt_time(10), end=dt_time(10, 30))   # programada que ya pasó
        for hour, status in ((11, 'canceled'), (12, 'no_show'), (13, 'done')):
            make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                             start=dt_time(hour), end=dt_time(hour, 30), status=status)
        response = self.patch(timezone=SURESTE)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Organization.objects.get(pk=self.org.pk).timezone, SURESTE)

    def test_a_zone_outside_the_catalog_is_rejected(self):
        for value in ('Europe/Madrid', 'UTC', 'Marte/Nada'):
            response = self.patch(timezone=value)
            self.assertEqual(response.status_code, 400, value)
            self.assertIn('timezone', response.data['errors'])
        self.assertEqual(Organization.objects.get(pk=self.org.pk).timezone, CENTRO)
        self.assertFalse(OrganizationConfigEvent.objects.filter(kind='timezone_changed').exists())

    def test_the_same_zone_is_not_a_change(self):
        response = self.patch(timezone=CENTRO, display_name='Clínica Centro')
        self.assertEqual(response.status_code, 200, response.data)
        org = Organization.objects.get(pk=self.org.pk)
        self.assertEqual(org.display_name, 'Clínica Centro')
        self.assertIsNone(org.timezone_updated_at)
        self.assertFalse(OrganizationConfigEvent.objects.filter(kind='timezone_changed').exists())

    def test_resending_a_current_zone_outside_the_catalog_is_allowed(self):
        legacy, admin, _, _ = seed('TZ legacy', 'legacy', tz='UTC')
        client = APIClient()
        client.force_authenticate(User.objects.get(pk=admin.pk))
        response = client.patch(ME_URL, {'timezone': 'UTC', 'display_name': 'Legado'},
                                format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Organization.objects.get(pk=legacy.pk).display_name, 'Legado')

    def test_editing_other_fields_does_not_revert_a_zone_changed_meanwhile(self):
        stale_admin = User.objects.select_related('organization').get(pk=self.admin.pk)
        self.assertEqual(stale_admin.organization.timezone, CENTRO)      # sesión vieja
        with transaction.atomic():
            change_organization_timezone(
                actor=self.admin, organization=Organization.objects.get(pk=self.org.pk),
                timezone_name=SURESTE)
        client = APIClient()
        client.force_authenticate(stale_admin)
        response = client.patch(ME_URL, {'display_name': 'Edición vieja'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        org = Organization.objects.get(pk=self.org.pk)
        self.assertEqual(org.display_name, 'Edición vieja')
        self.assertEqual(org.timezone, SURESTE)

    # — reactivar una cita cancelada o no presentada (opción c del PO) —

    def reactivate(self, appointment):
        return self.client.patch(f'/api/appointments/{appointment.public_id}/status/', {
            'status': 'scheduled', 'expected_state': current_state(appointment),
        }, format='json')

    def test_reactivating_after_a_zone_change_is_rejected_without_writing(self):
        tomorrow = self.today + timedelta(days=1)
        stopped = [make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                                    start=dt_time(hour), end=dt_time(hour, 30), status=status)
                   for hour, status in ((11, 'canceled'), (12, 'no_show'))]
        self.assertEqual(self.patch(timezone=SURESTE).status_code, 200)   # no la bloquean
        for appointment in stopped:
            response = self.reactivate(appointment)
            self.assertEqual(response.status_code, 409, response.data)
            self.assertEqual(response.data['code'], 'appointment_timezone_changed')
            self.assertIn('otra zona horaria', response.data['message'])
            fresh = Appointment.objects.get(pk=appointment.pk)
            self.assertEqual(fresh.status, appointment.status)
            self.assertEqual((fresh.start_datetime, fresh.timezone_at_creation),
                             (appointment.start_datetime, CENTRO))
        self.assertFalse(AppointmentStatusChange.objects.exists())

    # — editar una cita no recalcula su instante salvo que se mueva (opción A del PO) —

    def edit(self, appointment, **changes):
        return self.client.patch(f'/api/appointments/{appointment.public_id}/', {
            **changes, 'expected_state': current_state(appointment),
        }, format='json')

    def test_editing_a_canceled_appointment_keeps_its_instants_and_zone(self):
        tomorrow = self.today + timedelta(days=1)
        canceled = make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                                    start=dt_time(11), end=dt_time(11, 30), status='canceled')
        before = (canceled.start_datetime, canceled.end_datetime, canceled.timezone_at_creation)
        self.assertEqual(self.patch(timezone=SURESTE).status_code, 200)
        response = self.edit(canceled, notes='Solo una nota', reason='Revisión')
        self.assertEqual(response.status_code, 200, response.data)
        fresh = Appointment.objects.get(pk=canceled.pk)
        self.assertEqual(fresh.notes, 'Solo una nota')
        self.assertEqual((fresh.start_datetime, fresh.end_datetime, fresh.timezone_at_creation),
                         before)
        # Sigue con la zona anterior, así que la reactivación se sigue rechazando.
        response = self.reactivate(fresh)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'appointment_timezone_changed')

    def test_moving_a_canceled_appointment_uses_the_current_zone(self):
        tomorrow = self.today + timedelta(days=1)
        canceled = make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                                    start=dt_time(11), end=dt_time(11, 30), status='canceled')
        self.assertEqual(self.patch(timezone=SURESTE).status_code, 200)
        later = tomorrow + timedelta(days=1)
        response = self.edit(canceled, date=later.isoformat(),
                             start_time='12:00', end_time='12:30')
        self.assertEqual(response.status_code, 200, response.data)
        org = Organization.objects.get(pk=self.org.pk)
        fresh = Appointment.objects.get(pk=canceled.pk)
        self.assertEqual(fresh.status, 'canceled')
        self.assertEqual(fresh.timezone_at_creation, SURESTE)
        self.assertEqual(fresh.start_datetime, local_date_time_to_utc(org, later, dt_time(12)))
        self.assertEqual(fresh.end_datetime, local_date_time_to_utc(org, later, dt_time(12, 30)))
        # Una hora nueva elegida con la zona vigente ya no está desalineada.
        response = self.reactivate(fresh)
        self.assertEqual(response.status_code, 200, response.data)

    def test_editing_a_row_without_instants_fills_them(self):
        tomorrow = self.today + timedelta(days=1)
        legacy = Appointment.objects.create(
            organization=self.org, pet=self.pet, veterinarian=self.vet, date=tomorrow,
            start_time=dt_time(15), end_time=dt_time(15, 30), reason='consulta',
            status='scheduled')
        self.assertIsNone(legacy.start_datetime)
        response = self.edit(legacy, notes='Primera edición')
        self.assertEqual(response.status_code, 200, response.data)
        fresh = Appointment.objects.get(pk=legacy.pk)
        self.assertEqual(fresh.timezone_at_creation, CENTRO)
        self.assertEqual(fresh.start_datetime,
                         local_date_time_to_utc(self.org, tomorrow, dt_time(15)))

    def test_reactivating_in_the_same_zone_still_works(self):
        tomorrow = self.today + timedelta(days=1)
        canceled = make_appointment(self.org, self.vet, self.pet, day=tomorrow,
                                    start=dt_time(11), end=dt_time(11, 30), status='canceled')
        response = self.reactivate(canceled)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Appointment.objects.get(pk=canceled.pk).status, 'scheduled')
        self.assertEqual(AppointmentStatusChange.objects.filter(
            appointment=canceled, from_status='canceled', to_status='scheduled').count(), 1)


class PlatformProvisioningTimezoneTests(TestCase):
    URL = '/api/platform/organizations/'

    def setUp(self):
        op_org = Organization.objects.create(name='Operación TZ')
        operator = User.objects.create_superuser(
            username='tz_platform_op', email='tzop@vetcare.internal',
            password='PlatformPass1234!', role='ADMIN_SAAS', organization=op_org)
        self.client = APIClient()
        self.client.force_authenticate(user=operator)

    def payload(self, **overrides):
        base = {
            'name': 'Clínica TZ', 'tax_rate': '0.1600', 'admin_username': 'tz_newadmin',
            'admin_email': 'tz_newadmin@test.com', 'admin_password': 'SuperPass1234!',
            'admin_first_name': 'Laura', 'admin_last_name': 'García',
        }
        base.update(overrides)
        return base

    def test_a_zone_outside_the_catalog_is_rejected(self):
        response = self.client.post(self.URL, self.payload(timezone='Europe/Madrid'),
                                    format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Organization.objects.filter(name='Clínica TZ').exists())

    def test_the_default_zone_is_the_catalog_default(self):
        response = self.client.post(self.URL, self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Organization.objects.get(name='Clínica TZ').timezone, CENTRO)


class TimezoneConcurrencyTests(TransactionTestCase):
    """Entrelazado forzado entre un cambio de zona y las escrituras de cita."""

    TIMEOUT = 20

    def setUp(self):
        set_current_user(None)
        self.org, self.admin, self.vet, self.pet = seed('TZ concurrencia', 'conc')

    def tearDown(self):
        connections.close_all()

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

    def session_client(self):
        """Cliente con su propia sesión: la organización que carga es la de AHORA."""
        user = User.objects.select_related('organization').get(pk=self.admin.pk)
        user.organization.timezone  # noqa: B018 — se carga ya, como la autenticación
        client = APIClient()
        client.force_authenticate(user)
        return client

    def interleave(self, first, second, *, module, attribute):
        """Detiene la PRIMERA llamada a `module.attribute` justo después de que
        corra (con su bloqueo ya tomado) y lanza la segunda operación."""
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
            except BaseException:  # noqa: BLE001 — se reporta, no se traga
                outcomes[label] = traceback.format_exc()
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

    # — operaciones —

    def change_zone(self):
        client = self.session_client()
        return lambda: client.patch(ME_URL, {'timezone': SURESTE}, format='json')

    def walk_in(self):
        client = self.session_client()
        return lambda: client.post('/api/appointments/walk-in/', {
            'pet': self.pet.id, 'veterinarian': self.vet.id, 'reason': 'Urgencia',
        }, format='json')

    def create(self, day):
        client = self.session_client()
        return lambda: client.post('/api/appointments/', {
            'pet': self.pet.id, 'veterinarian': self.vet.id, 'date': day.isoformat(),
            'start_time': '10:00', 'end_time': '10:30', 'reason': 'consulta',
        }, format='json')

    def reactivate(self, appointment):
        client = self.session_client()
        expected = current_state(appointment)
        return lambda: client.patch(f'/api/appointments/{appointment.public_id}/status/', {
            'status': 'scheduled', 'expected_state': expected,
        }, format='json')

    def reschedule(self, appointment, day):
        client = self.session_client()
        expected = current_state(appointment)
        return lambda: client.patch(f'/api/appointments/{appointment.public_id}/', {
            'date': day.isoformat(), 'start_time': '11:00', 'end_time': '11:30',
            'expected_state': expected,
        }, format='json')

    # — comprobaciones —

    def assert_aligned(self, appointment, tz):
        org = Organization.objects.get(pk=self.org.pk)
        self.assertEqual(org.timezone, tz)
        self.assertEqual(appointment.timezone_at_creation, tz)
        self.assertEqual(appointment.start_datetime,
                         local_date_time_to_utc(org, appointment.date, appointment.start_time))
        self.assertEqual(appointment.end_datetime,
                         local_date_time_to_utc(org, appointment.date, appointment.end_time))

    def assert_blocked(self, response):
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'timezone_change_blocked')
        self.assertFalse(OrganizationConfigEvent.objects.filter(kind='timezone_changed').exists())

    def assert_changed(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(OrganizationConfigEvent.objects.filter(kind='timezone_changed').count(), 1)

    def test_the_service_requires_an_open_transaction(self):
        with self.assertRaises(RuntimeError):
            change_organization_timezone(actor=self.admin, organization=self.org,
                                         timezone_name=SURESTE)
        self.assertEqual(Organization.objects.get(pk=self.org.pk).timezone, CENTRO)

    # — atención sin cita —

    def test_walk_in_first_then_the_waiting_zone_change_is_rejected(self):
        walk_in, change = self.interleave(self.walk_in(), self.change_zone(),
                                          module=appointment_views,
                                          attribute='share_lock_organization')
        self.assertEqual(walk_in.status_code, 201, walk_in.data)
        self.assert_blocked(change)
        self.assert_aligned(Appointment.objects.get(), CENTRO)

    def test_zone_change_first_then_the_waiting_walk_in_uses_the_new_zone(self):
        change, walk_in = self.interleave(self.change_zone(), self.walk_in(),
                                          module=appointment_services,
                                          attribute='future_active_appointments_count')
        self.assert_changed(change)
        self.assertEqual(walk_in.status_code, 201, walk_in.data)
        self.assert_aligned(Appointment.objects.get(), SURESTE)

    # — creación de recepción —

    def test_creation_first_then_the_waiting_zone_change_is_rejected(self):
        day = org_today_local(self.org) + timedelta(days=3)
        created, change = self.interleave(self.create(day), self.change_zone(),
                                          module=appointment_views,
                                          attribute='share_lock_organization')
        self.assertEqual(created.status_code, 201, created.data)
        self.assert_blocked(change)
        self.assert_aligned(Appointment.objects.get(), CENTRO)

    def test_zone_change_first_then_the_waiting_creation_uses_the_new_zone(self):
        day = org_today_local(self.org) + timedelta(days=3)
        change, created = self.interleave(self.change_zone(), self.create(day),
                                          module=appointment_services,
                                          attribute='future_active_appointments_count')
        self.assert_changed(change)
        self.assertEqual(created.status_code, 201, created.data)
        self.assert_aligned(Appointment.objects.get(), SURESTE)

    # — reagendar una cita que ya pasó (no bloquea el cambio por sí sola) —

    def _missed_appointment(self):
        yesterday = org_today_local(self.org) - timedelta(days=1)
        return make_appointment(self.org, self.vet, self.pet, day=yesterday,
                                start=dt_time(10), end=dt_time(10, 30))

    def test_reschedule_first_then_the_waiting_zone_change_is_rejected(self):
        missed = self._missed_appointment()
        day = org_today_local(self.org) + timedelta(days=3)
        moved, change = self.interleave(self.reschedule(missed, day), self.change_zone(),
                                        module=appointment_views,
                                        attribute='share_lock_organization')
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assert_blocked(change)
        self.assert_aligned(Appointment.objects.get(pk=missed.pk), CENTRO)

    def test_zone_change_first_then_the_waiting_reschedule_uses_the_new_zone(self):
        missed = self._missed_appointment()
        day = org_today_local(self.org) + timedelta(days=3)
        change, moved = self.interleave(self.change_zone(), self.reschedule(missed, day),
                                        module=appointment_services,
                                        attribute='future_active_appointments_count')
        self.assert_changed(change)
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assert_aligned(Appointment.objects.get(pk=missed.pk), SURESTE)

    # — reactivar una cita cancelada (no bloquea el cambio por sí sola) —

    def _canceled_appointment(self):
        day = org_today_local(self.org) + timedelta(days=3)
        return make_appointment(self.org, self.vet, self.pet, day=day,
                                start=dt_time(10), end=dt_time(10, 30), status='canceled')

    def test_reactivation_first_then_the_waiting_zone_change_is_rejected(self):
        canceled = self._canceled_appointment()
        reactivated, change = self.interleave(self.reactivate(canceled), self.change_zone(),
                                              module=appointment_views,
                                              attribute='share_lock_organization')
        self.assertEqual(reactivated.status_code, 200, reactivated.data)
        self.assert_blocked(change)
        appointment = Appointment.objects.get(pk=canceled.pk)
        self.assertEqual(appointment.status, 'scheduled')
        self.assert_aligned(appointment, CENTRO)

    def test_zone_change_first_then_the_waiting_reactivation_is_rejected(self):
        canceled = self._canceled_appointment()
        change, reactivated = self.interleave(self.change_zone(), self.reactivate(canceled),
                                              module=appointment_services,
                                              attribute='future_active_appointments_count')
        self.assert_changed(change)
        self.assertEqual(reactivated.status_code, 409, reactivated.data)
        self.assertEqual(reactivated.data['code'], 'appointment_timezone_changed')
        appointment = Appointment.objects.get(pk=canceled.pk)
        self.assertEqual(appointment.status, 'canceled')
        self.assertEqual(appointment.timezone_at_creation, CENTRO)
        self.assertFalse(AppointmentStatusChange.objects.filter(appointment=appointment).exists())
