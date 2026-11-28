"""Historial de cambios de Configuración (ADR p70 D9, plan F1.1) y robustez del
`PUT` de horario (F1.4).

- Un evento por guardado con cambios, ninguno sin cambios, con quién, cuándo y
  qué cambió (`{campo: [antes, después]}`).
- Un rollback no deja evento.
- Cada clínica ve solo el suyo, y solo quien puede editarla (`organization.update`).
- La migración 0018 copia el registro de zona horaria anterior.
- Solo los servicios de Configuración escriben eventos (gate estático).
"""
import ast
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.billing.models import Service
from apps.core.models import Permission, Role, UserRole
from apps.medical_records.models import MedicalRecord, MedicalRecordService
from apps.organizations.models import Organization, OrganizationConfigEvent
from apps.organizations.services import update_clinic_profile
from apps.patients.models import Owner, Pet
from apps.users.models import User

ME_URL = '/api/organizations/me/'
RULES_URL = '/api/organizations/settings/'
SCHEDULE_URL = '/api/organizations/schedule/'
HISTORY_URL = '/api/organizations/config-history/'
SERVICES_URL = '/api/billing/services/'
REQUEST_ID = '6f1c2a8e-4b7d-4c1e-9a3f-2d5e8b7c1a90'


def seed(name, suffix, *, codes=('*.*',)):
    org = Organization.objects.create(name=name, timezone='America/Mexico_City')
    role, _ = Role.objects.get_or_create(
        name=f'ROL {suffix}', organization=org, defaults={'is_system_role': False})
    role.permissions.set([Permission.objects.get_or_create(code=code)[0] for code in codes])
    user = User.objects.create_user(
        username=f'cfg_{suffix}', password='p', organization=org, role='ADMIN',
        first_name='Ana', last_name='Pérez')
    UserRole.objects.get_or_create(user=user, role=role)
    # Solo los permisos pedidos: fuera el rol de sistema que se asigna al crear.
    UserRole.objects.filter(user=user).exclude(role=role).delete()
    return org, user


def week(**overrides):
    days = [
        {'weekday': wd, 'is_closed': False, 'opens_at': '09:00', 'closes_at': '18:00',
         'has_break': False}
        for wd in range(1, 7)
    ] + [{'weekday': 7, 'is_closed': True, 'has_break': False}]
    for day in days:
        day.update(overrides.get(f'weekday_{day["weekday"]}', {}))
    return days


class ConfigHistoryApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin = seed('Clínica Historial', 'admin')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.get(pk=self.admin.pk))

    def events(self, kind=None):
        qs = OrganizationConfigEvent.objects.filter(organization=self.org)
        return qs.filter(kind=kind) if kind else qs

    # — datos de la clínica —

    def test_editing_the_clinic_records_only_what_changed(self):
        response = self.client.patch(ME_URL, {
            'display_name': 'Clínica Luna', 'city': '', 'phone': '5512345678',
        }, format='json', HTTP_X_REQUEST_ID=REQUEST_ID)
        self.assertEqual(response.status_code, 200, response.data)
        event = self.events('clinic_updated').get()
        # `city` ya estaba vacía: no es un cambio.
        self.assertEqual(event.changes, {
            'display_name': ['', 'Clínica Luna'], 'phone': ['', '5512345678'],
        })
        self.assertEqual(event.actor_id, self.admin.pk)
        self.assertEqual(event.request_id, REQUEST_ID)

    def test_saving_without_changes_records_nothing(self):
        self.client.patch(ME_URL, {'display_name': 'Clínica Luna'}, format='json')
        self.client.patch(ME_URL, {'display_name': 'Clínica Luna'}, format='json')
        self.assertEqual(self.events().count(), 1)

    def test_zone_and_other_fields_in_one_patch_are_two_events(self):
        response = self.client.patch(ME_URL, {
            'timezone': 'America/Cancun', 'display_name': 'Clínica Sur',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.events('timezone_changed').get().changes,
                         {'timezone': ['America/Mexico_City', 'America/Cancun']})
        self.assertEqual(self.events('clinic_updated').get().changes,
                         {'display_name': ['', 'Clínica Sur']})

    def test_a_rolled_back_change_leaves_no_event(self):
        Organization.objects.filter(pk=self.org.pk).update(phone='5512345678')
        org = Organization.objects.get(pk=self.org.pk)
        # INV-L rechaza vaciar el teléfono DESPUÉS de cambiar la zona: todo se deshace.
        with self.assertRaises(DjangoValidationError):
            update_clinic_profile(actor=self.admin, organization=org,
                                  data={'timezone': 'America/Cancun', 'phone': ''})
        self.assertEqual(Organization.objects.get(pk=self.org.pk).timezone, 'America/Mexico_City')
        self.assertFalse(self.events().exists())

    # — reglas de operación —

    def test_rules_record_their_change(self):
        response = self.client.patch(RULES_URL, {
            'require_open_cash_session': True, 'credit_default_days': 30,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.events('rules_updated').get().changes,
                         {'require_open_cash_session': [False, True]})
        self.client.patch(RULES_URL, {'require_open_cash_session': True}, format='json')
        self.assertEqual(self.events('rules_updated').count(), 1)

    # — horario —

    def test_replacing_the_schedule_records_only_the_changed_days(self):
        self.assertEqual(self.client.put(SCHEDULE_URL, week(), format='json').status_code, 200)
        # El primer PUT ya cambia el sábado frente al horario sembrado.
        baseline = self.events('schedule_replaced').count()
        response = self.client.put(SCHEDULE_URL, week(weekday_3={
            'opens_at': '10:00', 'has_break': True, 'break_start': '14:00', 'break_end': '15:00',
        }), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.events('schedule_replaced').count(), baseline + 1)
        event = self.events('schedule_replaced').first()
        self.assertEqual(list(event.changes), ['weekday_3'])
        before, after = event.changes['weekday_3']
        self.assertEqual((before['opens_at'], after['opens_at']), ('09:00', '10:00'))
        self.assertEqual((after['break_start'], after['break_end']), ('14:00', '15:00'))
        # Reenviar la misma semana no es un cambio.
        self.client.put(SCHEDULE_URL, week(weekday_3={
            'opens_at': '10:00', 'has_break': True, 'break_start': '14:00', 'break_end': '15:00',
        }), format='json')
        self.assertEqual(self.events('schedule_replaced').count(), baseline + 1)

    # — servicios —

    def test_the_service_lifecycle_is_recorded(self):
        response = self.client.post(SERVICES_URL, {
            'name': 'Consulta general', 'base_price': '350.00',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        public_id = response.data['public_id']
        created = self.events('service_created').get()
        self.assertEqual(created.subject,
                         {'type': 'service', 'public_id': public_id, 'name': 'Consulta general'})
        self.assertEqual(created.changes['base_price'], [None, '350.00'])

        url = f'{SERVICES_URL}{public_id}/'
        self.assertEqual(self.client.patch(url, {'base_price': '400.00'}, format='json').status_code, 200)
        self.assertEqual(self.events('service_updated').get().changes,
                         {'base_price': ['350.00', '400.00']})
        self.assertEqual(self.client.patch(url, {'is_active': False}, format='json').status_code, 200)
        self.assertEqual(self.events('service_deactivated').get().changes,
                         {'is_active': [True, False]})

        other = Service.objects.create(organization=self.org, name='Baño', base_price=Decimal('200'))
        response = self.client.delete(f'{SERVICES_URL}{other.public_id}/')
        self.assertEqual(response.status_code, 204)
        deleted = self.events('service_deleted').get()
        self.assertEqual(deleted.subject['name'], 'Baño')

    def test_inactive_services_are_listed_only_on_request_and_can_be_reactivated(self):
        # Plan F1.7: Configuración ve los inactivos para reactivarlos; el resto no.
        Service.objects.create(organization=self.org, name='Activo', base_price=Decimal('100'))
        inactive = Service.objects.create(organization=self.org, name='Retirado',
                                          base_price=Decimal('100'), is_active=False)
        other_org, _ = seed('Otra clínica servicios', 'svc_other')
        Service.objects.create(organization=other_org, name='Ajeno', base_price=Decimal('100'),
                               is_active=False)
        names = lambda response: sorted(item['name'] for item in response.data)  # noqa: E731
        self.assertEqual(names(self.client.get(SERVICES_URL)), ['Activo'])
        self.assertEqual(names(self.client.get(SERVICES_URL, {'include_inactive': 'true'})),
                         ['Activo', 'Retirado'])
        response = self.client.patch(f'{SERVICES_URL}{inactive.public_id}/',
                                     {'is_active': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.events('service_activated').get().subject['name'], 'Retirado')

    def test_a_service_with_dependencies_is_not_deleted_and_leaves_no_event(self):
        service = Service.objects.create(organization=self.org, name='Vacuna', base_price=Decimal('300'))
        owner = Owner.objects.create(organization=self.org, name='Ana', phone='5511110003')
        pet = Pet.objects.create(organization=self.org, owner=owner, name='Luna',
                                 species='perro', birth_date='2021-01-01')
        record = MedicalRecord.objects.create(organization=self.org, pet=pet)
        MedicalRecordService.objects.create(medical_record=record, service=service)
        response = self.client.delete(f'{SERVICES_URL}{service.public_id}/')
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(Service.objects.filter(pk=service.pk).exists())
        self.assertFalse(self.events('service_deleted').exists())

    # — endpoint —

    def test_the_history_lists_newest_first_with_readable_fields(self):
        self.client.patch(ME_URL, {'display_name': 'Uno'}, format='json')
        self.client.patch(ME_URL, {'display_name': 'Dos'}, format='json')
        response = self.client.get(HISTORY_URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 2)
        first = response.data['results'][0]
        self.assertEqual(first['kind'], 'clinic_updated')
        self.assertEqual(first['kind_label'], 'Datos de la clínica')
        self.assertEqual(first['actor_name'], 'Ana Pérez')
        self.assertEqual(first['changes'], {'display_name': ['Uno', 'Dos']})
        self.assertNotIn('id', first)

    def test_each_clinic_sees_only_its_history(self):
        other_org, other_admin = seed('Otra clínica', 'other')
        other = APIClient()
        other.force_authenticate(other_admin)
        other.patch(ME_URL, {'display_name': 'Ajena'}, format='json')
        self.client.patch(ME_URL, {'display_name': 'Propia'}, format='json')
        response = self.client.get(HISTORY_URL)
        self.assertEqual([e['changes']['display_name'][1] for e in response.data['results']],
                         ['Propia'])

    def test_only_who_can_edit_the_clinic_sees_the_history(self):
        _, viewer = seed('Clínica lectura', 'viewer', codes=('organization.retrieve',))
        User.objects.filter(pk=viewer.pk).update(role='VET')
        viewer.refresh_from_db()
        client = APIClient()
        client.force_authenticate(viewer)
        self.assertEqual(client.get(HISTORY_URL).status_code, 403)

    def test_events_are_insert_only(self):
        self.client.patch(ME_URL, {'display_name': 'Uno'}, format='json')
        event = self.events().get()
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()


class ScheduleBulkRobustnessTests(TestCase):
    """F1.4 (C19): una entrada mal formada es 400, nunca 500."""

    @classmethod
    def setUpTestData(cls):
        cls.org, cls.admin = seed('Clínica Horario', 'sched')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.get(pk=self.admin.pk))

    def test_an_item_that_is_not_an_object_is_rejected(self):
        days = week()
        days[2] = 'miércoles'
        response = self.client.put(SCHEDULE_URL, days, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_the_frontend_repeats_the_server_messages(self):
        # Plan F1.3: la validación previa del horario usa los mismos mensajes.
        from apps.organizations import serializers as org_serializers
        path = (Path(settings.BASE_DIR).parent / 'frontend' / 'src' / 'features'
                / 'config' / 'schedule.js')
        source = path.read_text(encoding='utf-8')
        for name in ('SCHEDULE_HOURS_REQUIRED', 'SCHEDULE_HOURS_ORDER',
                     'SCHEDULE_BREAK_REQUIRED', 'SCHEDULE_BREAK_INSIDE'):
            self.assertIn(f'"{getattr(org_serializers, name)}"', source, name)

    def test_a_text_or_boolean_weekday_is_rejected(self):
        for bad in ('3', True, 3.0):
            days = week()
            days[2]['weekday'] = bad
            response = self.client.put(SCHEDULE_URL, days, format='json')
            self.assertEqual(response.status_code, 400, (bad, response.data))
        self.assertFalse(OrganizationConfigEvent.objects.filter(organization=self.org).exists())


class ConfigEventMigrationTests(TransactionTestCase):
    """0018 copia cada registro de zona horaria como evento `timezone_changed`."""

    def test_timezone_audits_become_events(self):
        old = ('organizations', '0017_normalize_timezones_to_catalog')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()

        def restore():
            MigrationExecutor(connection).migrate(latest)
        self.addCleanup(restore)
        # La clínica y el usuario, con los modelos de hoy: solo `organizations`
        # retrocede a 0017.
        org = Organization.objects.create(name='Legado')
        user = User.objects.create_user(username='legado', password='p',
                                        organization=org, role='ADMIN')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        apps.get_model('organizations', 'OrganizationTimezoneAudit').objects.create(
            organization_id=org.pk, old_timezone='UTC', new_timezone='America/Mexico_City',
            changed_by_id=user.pk)
        restore()

        event = OrganizationConfigEvent.objects.get(organization_id=org.pk)
        self.assertEqual(event.kind, 'timezone_changed')
        self.assertEqual(event.changes, {'timezone': ['UTC', 'America/Mexico_City']})
        self.assertEqual(event.actor_id, user.pk)


class OnlyConfigServicesWriteEventsGateTests(TestCase):
    """Gate estático: fuera de `record_config_event`, nadie crea eventos."""

    ALLOWED = {('organizations', 'services.py')}

    def test_no_other_production_module_creates_events(self):
        apps_dir = Path(settings.BASE_DIR) / 'apps'
        offenders = []
        for path in apps_dir.rglob('*.py'):
            rel = path.relative_to(apps_dir).parts
            if 'tests' in rel or 'migrations' in rel:
                continue
            if (rel[0], rel[-1]) in self.ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    # OrganizationConfigEvent(...) / .objects.create / bulk_create
                    target = ast.unparse(func)
                    if (target == 'OrganizationConfigEvent'
                            or (target.startswith('OrganizationConfigEvent.')
                                and target.rsplit('.', 1)[-1] in ('create', 'bulk_create',
                                                                  'get_or_create',
                                                                  'update_or_create'))):
                        offenders.append(f'{"/".join(rel)}:{node.lineno}')
        self.assertEqual(offenders, [], 'Usa organizations.services.record_config_event')
