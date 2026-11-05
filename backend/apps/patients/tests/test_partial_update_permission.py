"""PATCH exige la misma capacidad que PUT.

DRF despacha PATCH como `partial_update`, y `_resolve_required` lo convertía en
`patient.partial_update` y `owner.partial_update`, códigos que no existen en el
catálogo. VET y ASSISTANT tienen `*.update` y recibían 403 al editar desde la app.
"""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions import _resolve_required
from apps.core.permissions_codes import PERMISSION_CODES
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

OWNER_PHONE = '5512345678'


def make_user(username, org, role):
    return get_user_model().objects.create_user(
        username=username, password='x', organization=org, role=role)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class ResolvedCode(SimpleTestCase):
    def test_partial_update_resolves_to_update(self):
        view = SimpleNamespace(basename='patient', action='partial_update', kwargs={})
        self.assertEqual(_resolve_required(SimpleNamespace(method='PATCH'), view), 'patient.update')

    def test_declared_permission_still_wins(self):
        view = SimpleNamespace(
            required_permission='patient.list', basename='patient', action='partial_update', kwargs={})
        self.assertEqual(_resolve_required(SimpleNamespace(method='PATCH'), view), 'patient.list')

    def test_catalog_has_no_duplicate_capability(self):
        self.assertEqual([c for c in PERMISSION_CODES if c.endswith('.partial_update')], [])


class PatchMatchesPut(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica A', timezone='UTC')
        cls.other_org = Organization.objects.create(name='Clinica B', timezone='UTC')
        cls.vet = make_user('vet_a', cls.org, 'VET')
        cls.assistant = make_user('assistant_a', cls.org, 'ASSISTANT')
        cls.agent = make_user('agent_a', cls.org, 'AGENT')
        cls.foreign_vet = make_user('vet_b', cls.other_org, 'VET')

        cls.read_only = make_user('read_only_a', cls.org, 'VET')
        UserRole.objects.filter(user=cls.read_only).delete()
        role = Role.objects.create(name='SOLO_LECTURA', organization=cls.org)
        role.permissions.set([
            Permission.objects.get_or_create(code=code)[0]
            for code in ('patient.retrieve', 'owner.retrieve')
        ])
        UserRole.objects.create(user=cls.read_only, role=role)

    def setUp(self):
        self.owner = Owner.objects.create(organization=self.org, name='Ana', phone=OWNER_PHONE)
        self.pet = Pet.objects.create(
            organization=self.org, owner=self.owner, name='Luna', species='canino',
            birth_date='2020-01-01')
        self.pet_url = f'/api/pets/{self.pet.public_id}/'
        self.owner_url = f'/api/owners/{self.owner.public_id}/'

    def pet_body(self, name):
        return {'name': name, 'species': 'canino', 'birth_date': '2020-01-01',
                'owner': {'name': 'Ana', 'phone': OWNER_PHONE}}

    def test_vet_and_assistant_update_pets_with_put_and_patch(self):
        for user in (self.vet, self.assistant):
            for method, name in (('put', 'Por Put'), ('patch', 'Por Patch')):
                with self.subTest(role=user.role, method=method):
                    response = getattr(client_for(user), method)(
                        self.pet_url, self.pet_body(name), format='json')
                    self.assertEqual(response.status_code, 200, response.data)
                    self.pet.refresh_from_db()
                    self.assertEqual(self.pet.name, name)

    def test_vet_and_assistant_update_owners_with_put_and_patch(self):
        for user in (self.vet, self.assistant):
            for method, name in (('put', 'Ana Put'), ('patch', 'Ana Patch')):
                with self.subTest(role=user.role, method=method):
                    response = getattr(client_for(user), method)(
                        self.owner_url, {'name': name, 'phone': OWNER_PHONE}, format='json')
                    self.assertEqual(response.status_code, 200, response.data)
                    self.owner.refresh_from_db()
                    self.assertEqual(self.owner.name, name)

    def test_payload_of_the_edit_screen_is_accepted(self):
        """Mismo cuerpo que afirma `frontend/src/pages/pets.edit.test.jsx`."""
        response = client_for(self.vet).patch(self.pet_url, {
            'name': 'Luna Editada', 'species': 'canino', 'breed': '', 'birth_date': '2020-01-01',
            'sex': 'unknown', 'color': '', 'owner': {'name': 'Ana', 'phone': OWNER_PHONE},
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.pet.refresh_from_db()
        self.assertEqual(self.pet.name, 'Luna Editada')

    def test_user_without_database_role_uses_the_same_rule(self):
        user = make_user('vet_fallback', self.org, 'VET')
        UserRole.objects.filter(user=user).delete()
        response = client_for(user).patch(self.pet_url, {'name': 'Por Fallback'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_roles_without_update_are_still_denied(self):
        for user in (self.read_only, self.agent):
            for method in ('put', 'patch'):
                for url in (self.pet_url, self.owner_url):
                    with self.subTest(user=user.username, method=method, url=url):
                        response = getattr(client_for(user), method)(url, {'name': 'X'}, format='json')
                        self.assertEqual(response.status_code, 403)
        self.pet.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.pet.name, 'Luna')
        self.assertEqual(self.owner.name, 'Ana')

    def test_other_organization_gets_not_found(self):
        for method in ('put', 'patch'):
            for url in (self.pet_url, self.owner_url):
                with self.subTest(method=method, url=url):
                    response = getattr(client_for(self.foreign_vet), method)(
                        url, {'name': 'Ajeno', 'phone': OWNER_PHONE}, format='json')
                    self.assertEqual(response.status_code, 404)
        self.pet.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.pet.name, 'Luna')
        self.assertEqual(self.owner.name, 'Ana')
