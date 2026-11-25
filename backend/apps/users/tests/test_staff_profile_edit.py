"""A1 (plan Equipo, F2): editar nombre, apellido y correo de un integrante.

Incluye la tabla de ejemplos de nombres de D4, que el frontend copia literalmente
(`frontend/src/pages/staff.test.jsx`): si cambia aquí, cambia allá y en
`docs/modules/organizations.md`.
"""
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import IntegrityError
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.services import update_staff_profile

User = get_user_model()

PASSWORD = 'Segura123'

# Tabla de ejemplos de nombres (D4). (entrada, se acepta, se guarda como).
NAME_EXAMPLES = [
    ('María José', True, 'María José'),
    ('Argüelles', True, 'Argüelles'),
    ('María-José', True, 'María-José'),
    ("O'Brien", True, "O'Brien"),
    ('D’Angelo', True, 'D’Angelo'),
    ('de la Cruz', True, 'de la Cruz'),
    ('Zoë', True, 'Zoë'),
    ('Łukasz', True, 'Łukasz'),
    ('José', True, 'José'),  # NFD → NFC
    ('  Ana  ', True, 'Ana'),
    ('Ana  Luz', True, 'Ana  Luz'),
    ('Juan2', False, None),
    ('Ana 😀', False, None),
    ('Аna', False, None),  # A cirílica
    ('Ana_Luz', False, None),
    ('Ma. José', False, None),
]


def _url(user):
    return f'/api/staff/{user.public_id}/'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class _Fixtures(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Edit', timezone='UTC')
        self.admin = User.objects.create_user(
            username='ed_admin', email='ed_admin@example.com', password=PASSWORD,
            organization=self.org, role='ADMIN', first_name='Ada',
        )
        role, _ = Role.objects.get_or_create(
            name='ADMIN', organization=self.org, defaults={'is_system_role': True},
        )
        role.permissions.set([Permission.objects.get_or_create(code='*.*')[0]])
        UserRole.objects.get_or_create(user=self.admin, role=role)
        self.vet = User.objects.create_user(
            username='ed_vet', email='ed_vet@example.com', password=PASSWORD,
            organization=self.org, role='VET', first_name='Eva', last_name='Original',
            license_number='1234567',
        )
        self.client.force_authenticate(user=self.admin)

    def patch(self, user, data):
        return self.client.patch(_url(user), data, format='json')


class EditIdentityTests(_Fixtures):
    def test_admin_edits_names_and_email(self):
        with self.assertLogs('users.events', level='INFO') as logs:
            r = self.patch(self.vet, {
                'first_name': 'Eva María', 'last_name': 'de la Cruz', 'email': ' Eva.Nueva@Example.com ',
            })
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.vet.refresh_from_db()
        self.assertEqual(
            (self.vet.first_name, self.vet.last_name, self.vet.email),
            ('Eva María', 'de la Cruz', 'eva.nueva@example.com'),
        )
        self.assertEqual(r.data['email'], 'eva.nueva@example.com')
        # El log nombra los campos, nunca los valores.
        self.assertTrue(any('STAFF_PROFILE_UPDATED' in line for line in logs.output))
        for record in logs.records:
            self.assertNotIn('eva.nueva@example.com', str(record.__dict__))

    def test_name_examples_on_edit(self):
        for value, accepted, stored in NAME_EXAMPLES:
            with self.subTest(value=value):
                r = self.patch(self.vet, {'first_name': value})
                if accepted:
                    self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
                    self.vet.refresh_from_db()
                    self.assertEqual(self.vet.first_name, stored)
                else:
                    self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
                    self.assertIn('first_name', r.data['errors'])

    def test_blank_first_name_is_rejected_and_blank_last_name_is_accepted(self):
        r = self.patch(self.vet, {'first_name': '   '})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
        self.assertEqual(r.data['errors']['first_name'], ['El nombre es obligatorio.'])
        r = self.patch(self.vet, {'last_name': ''})
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.last_name, '')

    def test_taken_email_gets_the_same_generic_message(self):
        other_org = Organization.objects.create(name='Clinica Otra', timezone='UTC')
        User.objects.create_user(username='same', email='same@example.com', organization=self.org)
        User.objects.create_user(username='else', email='else@example.com', organization=other_org)
        User.objects.create_user(
            username='gone', email='gone@example.com', organization=self.org, is_active=False,
        )
        for email in ('same@example.com', 'ELSE@example.com', 'gone@example.com'):
            with self.subTest(email=email):
                r = self.patch(self.vet, {'email': email})
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
                self.assertEqual(r.data['errors']['email'], ['Este correo no está disponible.'])
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.email, 'ed_vet@example.com')

    def test_same_email_with_other_case_saves_nothing(self):
        with mock.patch('apps.users.services.logger') as log:
            r = self.patch(self.vet, {'email': 'ED_VET@example.com'})
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        log.info.assert_not_called()
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.email, 'ed_vet@example.com')

    def test_other_fields_are_rejected_without_changes(self):
        for field, value in (
            ('role', 'ADMIN'), ('username', 'otro'), ('password', 'Otra12345'),
            ('is_active', False), ('session_version', 9),
        ):
            with self.subTest(field=field):
                r = self.patch(self.vet, {field: value, 'first_name': 'Cambio'})
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
                self.assertEqual(r.data['errors']['non_field_errors'], [
                    'Solo se pueden editar nombre, apellido, correo, especialidades, '
                    'cédula profesional y si atiende pacientes.'])
        self.vet.refresh_from_db()
        self.assertEqual(
            (self.vet.role, self.vet.username, self.vet.first_name, self.vet.is_active,
             self.vet.session_version),
            ('VET', 'ed_vet', 'Eva', True, 0),
        )

    def test_unreachable_targets_and_roles_without_permission(self):
        other_org = Organization.objects.create(name='Clinica B', timezone='UTC')
        foreign = User.objects.create_user(username='f', organization=other_org, role='VET')
        inactive = User.objects.create_user(
            username='i', organization=self.org, role='ASSISTANT', is_active=False,
        )
        agent = User.objects.create_user(username='ag', organization=self.org, role='AGENT')
        User.objects.filter(pk=agent.pk).update(is_service_account=True)
        saas = User.objects.create_user(username='s', organization=self.org, role='ADMIN_SAAS')
        for target in (foreign, inactive, agent, saas):
            with self.subTest(target=target.username):
                r = self.patch(target, {'first_name': 'Nadie'})
                self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.data)

        for role in ('VET', 'ASSISTANT'):
            with self.subTest(role=role):
                actor = User.objects.create_user(
                    username=f'actor_{role}', organization=self.org, role=role,
                    license_number='1234567' if role == 'VET' else '',
                )
                client = APIClient()
                client.force_authenticate(user=actor)
                r = client.patch(_url(self.vet), {'first_name': 'Nadie'}, format='json')
                self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.data)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.first_name, 'Eva')


class EmailRaceTests(_Fixtures):
    def test_unique_index_violation_becomes_a_field_error(self):
        User.objects.create_user(username='taken', email='taken@example.com', organization=self.org)
        # Simula que la validación pasó y otro ADMIN guardó el correo antes.
        with mock.patch(
            'apps.users.serializers.normalize_staff_email', side_effect=lambda v, **kw: v.lower(),
        ):
            r = self.patch(self.vet, {'email': 'taken@example.com'})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.data)
        self.assertEqual(r.data['errors']['email'], ['Este correo no está disponible.'])
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.email, 'ed_vet@example.com')

    def test_other_integrity_errors_propagate(self):
        with mock.patch.object(User, 'save', side_effect=IntegrityError('otra_restriccion')):
            with self.assertRaises(IntegrityError):
                update_staff_profile(
                    admin=self.admin, target_user=self.vet, changes={'first_name': 'X'},
                )


class CreateNamesTests(_Fixtures):
    def _create(self, n, **over):
        payload = {
            'username': f'nuevo{n}', 'email': f'nuevo{n}@example.com',
            'first_name': 'Nueva', 'role': 'ASSISTANT',
        }
        payload.update(over)
        return self.client.post('/api/staff/create/', payload, format='json')

    def test_name_examples_on_create(self):
        for n, (value, accepted, stored) in enumerate(NAME_EXAMPLES):
            with self.subTest(value=value):
                r = self._create(n, first_name=value, last_name=value)
                if accepted:
                    self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
                    created = User.objects.get(username=f'nuevo{n}')
                    self.assertEqual((created.first_name, created.last_name), (stored, stored))
                else:
                    self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_first_name_is_required_on_create(self):
        # El alta responde sin sobre: {campo: [mensajes]} (contrato existente).
        r = self._create(90, first_name='')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertEqual(r.data['first_name'], ['El nombre es obligatorio.'])
        payload = {
            'username': 'sinnombre', 'email': 'sinnombre@example.com', 'role': 'ASSISTANT',
        }
        r = self.client.post('/api/staff/create/', payload, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertEqual(r.data['first_name'], ['El nombre es obligatorio.'])


class LoginAfterEmailChangeTests(_Fixtures):
    def test_new_email_logs_in_old_one_does_not_and_username_still_works(self):
        r = self.patch(self.vet, {'email': 'eva.nueva@example.com'})
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        login = APIClient()
        for identifier, expected in (
            ('eva.nueva@example.com', status.HTTP_200_OK),
            ('ed_vet@example.com', status.HTTP_401_UNAUTHORIZED),
            ('ed_vet', status.HTTP_200_OK),
        ):
            with self.subTest(identifier=identifier):
                res = login.post('/api/token/', {'username': identifier, 'password': PASSWORD},
                                 format='json')
                self.assertEqual(res.status_code, expected, res.data)


class SnapshotTests(_Fixtures):
    def _record(self):
        owner = Owner.objects.create(name='O', phone='5512345678', organization=self.org)
        pet = Pet.objects.create(name='P', species='dog', owner=owner, organization=self.org)
        return MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, organization=self.org, diagnosis='d', treatment='t',
        )

    def test_renaming_keeps_closed_snapshots_and_updates_open_records(self):
        closed = self._record()
        r = self.client.post(f'/api/medical-records/{closed.public_id}/close/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        open_record = self._record()

        r = self.patch(self.vet, {'last_name': 'Nuevo'})
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

        closed.refresh_from_db()
        self.assertEqual(closed.vet_name_at_close, 'Eva Original')
        from pypdf import PdfReader
        pdf = self.client.get(f'/api/medical-records/{closed.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
        self.assertIn('Eva Original', text)
        self.assertNotIn('Eva Nuevo', text)

        detail = self.client.get(f'/api/medical-records/{open_record.public_id}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['veterinarian_name'], 'Eva Nuevo')
