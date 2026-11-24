"""ADR p66: función clínica separada del rol («atiende pacientes»).

- Predicado único: atiende quien es VET, o ADMIN marcado; ASSISTANT nunca.
- Backfill de la migración 0014 (decisión del PO): VET y ADMIN con cédula.
- La cédula la exige quien atiende (alta y edición).
- El agente y la creación de citas del agente usan el mismo predicado: un ADMIN
  que atiende recibe huecos; uno que no, no.
"""
import importlib
from datetime import time, timedelta
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import set_current_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import StaffAccessEvent
from apps.users.professional import clinician_q, is_clinician

User = get_user_model()

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
backfill = importlib.import_module('apps.users.migrations.0014_user_attends_patients').backfill


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name=username.title(), **extra)


class ClinicianPredicateTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica Funcion', timezone='UTC')
        cls.vet = _user(cls.org, 'cf_vet', 'VET', license_number='1234567')
        cls.admin_vet = _user(cls.org, 'cf_admin_vet', 'ADMIN', license_number='7654321',
                              attends_patients=True)
        cls.admin = _user(cls.org, 'cf_admin', 'ADMIN')
        cls.assistant = _user(cls.org, 'cf_asst', 'ASSISTANT')

    def test_predicate_and_queryset_agree(self):
        expected = {self.vet.pk, self.admin_vet.pk}
        self.assertEqual(
            {u.pk for u in User.objects.filter(organization=self.org) if is_clinician(u)}, expected)
        self.assertEqual(
            set(User.objects.filter(clinician_q(), organization=self.org).values_list('pk', flat=True)),
            expected)

    def test_the_role_decides_for_vet_and_assistant(self):
        # El campo solo cuenta en ADMIN: un VET sin la marca atiende y un ASSISTANT
        # con la marca no (filas escritas fuera de los servicios).
        User.objects.filter(pk=self.vet.pk).update(attends_patients=False)
        User.objects.filter(pk=self.assistant.pk).update(attends_patients=True)
        self.vet.refresh_from_db()
        self.assistant.refresh_from_db()
        self.assertTrue(is_clinician(self.vet))
        self.assertFalse(is_clinician(self.assistant))
        self.assertTrue(User.objects.filter(clinician_q(), pk=self.vet.pk).exists())
        self.assertFalse(User.objects.filter(clinician_q(), pk=self.assistant.pk).exists())


class BackfillTests(APITestCase):
    def test_backfill_follows_the_po_decision(self):
        org = Organization.objects.create(name='Clinica Backfill', timezone='UTC')
        vet = _user(org, 'bf_vet', 'VET', license_number='1234567')
        admin_with = _user(org, 'bf_admin_c', 'ADMIN', license_number='7654321')
        admin_without = _user(org, 'bf_admin_s', 'ADMIN')
        assistant = _user(org, 'bf_asst', 'ASSISTANT', license_number='1111111')
        User.objects.filter(organization=org).update(attends_patients=False)

        backfill(django_apps, None)

        got = dict(User.objects.filter(organization=org).values_list('username', 'attends_patients'))
        self.assertEqual(got, {
            vet.username: True, admin_with.username: True,
            admin_without.username: False, assistant.username: False,
        })


@FAST_HASHER
class ClinicalFunctionApiTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica Funcion API', timezone='UTC')
        self.admin = _user(self.org, 'fa_admin', 'ADMIN')
        self.client.force_authenticate(self.admin)

    def create(self, **over):
        payload = {'username': 'fa_new', 'email': 'fa_new@example.com', 'first_name': 'Nuevo',
                   'role': 'ADMIN'}
        payload.update(over)
        return self.client.post('/api/staff/create/', payload, format='json')

    def test_admin_who_attends_needs_a_license(self):
        res = self.create(attends_patients=True)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('license_number', res.data)
        res = self.create(attends_patients=True, license_number='1234567')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(res.data['member']['attends_patients'])
        self.assertTrue(User.objects.get(username='fa_new').attends_patients)

    def test_admin_without_the_mark_does_not_attend_and_needs_no_license(self):
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertFalse(res.data['member']['attends_patients'])

    def test_vet_always_attends_and_assistant_never(self):
        res = self.create(role='VET', license_number='1234567')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(User.objects.get(username='fa_new').attends_patients)
        res = self.create(username='fa_asst', email='fa_asst@example.com', role='ASSISTANT',
                          attends_patients=True)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('attends_patients', res.data)

    def test_edit_the_mark_only_on_admins_and_with_license(self):
        other = _user(self.org, 'fa_other_admin', 'ADMIN')
        url = f'/api/staff/{other.public_id}/'
        res = self.client.patch(url, {'attends_patients': True}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('license_number', res.data['errors'])
        res = self.client.patch(url, {'attends_patients': True, 'license_number': '1234567'},
                                format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertTrue(res.data['attends_patients'])
        event = StaffAccessEvent.objects.get(member=other, kind='profile_updated')
        self.assertEqual(event.changes, {'fields': ['attends_patients', 'license_number']})

        vet = _user(self.org, 'fa_vet', 'VET', license_number='1234567')
        res = self.client.patch(f'/api/staff/{vet.public_id}/', {'attends_patients': False},
                                format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('attends_patients', res.data['errors'])

    def test_directory_tells_the_agenda_who_attends(self):
        _user(self.org, 'fa_dir_vet', 'VET', license_number='1234567')
        assistant = _user(self.org, 'fa_dir_asst', 'ASSISTANT')
        self.client.force_authenticate(assistant)
        rows = {r['first_name']: r for r in self.client.get('/api/staff/').data}
        self.assertTrue(rows['Fa_Dir_Vet']['attends_patients'])
        self.assertFalse(rows['Fa_Admin']['attends_patients'])
        self.assertFalse(rows['Fa_Dir_Asst']['attends_patients'])


class AgentUsesTheClinicalFunctionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica Agente Funcion', timezone='UTC')
        cls.vet = _user(cls.org, 'ag_vet', 'VET', license_number='1234567')
        cls.admin_vet = _user(cls.org, 'ag_admin_vet', 'ADMIN', license_number='7654321',
                              attends_patients=True)
        cls.admin = _user(cls.org, 'ag_admin', 'ADMIN')
        cls.assistant = _user(cls.org, 'ag_asst', 'ASSISTANT')
        owner = Owner.objects.create(organization=cls.org, name='Ana', phone='5511113333')
        cls.pet = Pet.objects.create(organization=cls.org, owner=owner, name='Luna',
                                     species='perro', birth_date='2021-01-01')

    def test_scheduling_candidates_are_the_clinicians(self):
        from apps.agent import tools
        settings = SimpleNamespace(default_veterinarian_id=None, default_veterinarian=None)
        self.assertEqual(tools._scheduling_vets(self.org, settings), [self.vet, self.admin_vet])

    def test_a_non_clinician_default_vet_is_not_offered(self):
        from apps.agent import tools
        settings = SimpleNamespace(default_veterinarian_id=self.admin.pk, default_veterinarian=self.admin)
        self.assertEqual(tools._scheduling_vets(self.org, settings), [self.vet, self.admin_vet])
        settings = SimpleNamespace(default_veterinarian_id=self.admin_vet.pk,
                                   default_veterinarian=self.admin_vet)
        self.assertEqual(tools._scheduling_vets(self.org, settings), [self.admin_vet])

    def _validate(self, vet):
        from apps.appointments.creation import AppointmentCommand, CreationRejected, validate_creation
        day = timezone.now().date() + timedelta(days=7)
        command = AppointmentCommand(
            organization_id=self.org.pk, pet_id=self.pet.pk, veterinarian_id=vet.pk,
            date=day, start_time=time(10, 0), end_time=time(10, 30), reason='vacuna')
        try:
            with transaction.atomic():
                validate_creation(command, require_schedule=True)
        except CreationRejected as exc:
            return exc.reason
        return None

    def test_agent_creation_accepts_an_admin_who_attends_and_rejects_one_who_does_not(self):
        self.assertEqual(self._validate(self.admin), 'entity_scope')
        self.assertEqual(self._validate(self.assistant), 'entity_scope')
        self.assertNotEqual(self._validate(self.admin_vet), 'entity_scope')
        self.assertNotEqual(self._validate(self.vet), 'entity_scope')
