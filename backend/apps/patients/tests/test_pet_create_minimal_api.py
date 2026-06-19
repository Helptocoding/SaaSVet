"""
Alta MANUAL de mascota vía API (POST /api/pets/) — datos mínimos + multi-tenant.

Confirma que relajar especie/fecha NO toca el aislamiento por organización: la
mascota creada hereda la org del usuario autenticado (nunca del body) y el
teléfono sigue siendo obligatorio.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Pet
from apps.users.models import User


def _seed_roles(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    perms_map = {c: Permission.objects.get_or_create(code=c)[0] for c in PERMISSION_CODES}
    roles = {}
    for name, codes in PERMISSIONS.items():
        if name == "ADMIN_SAAS":
            continue
        role, _ = Role.objects.get_or_create(name=name, organization=org, defaults={"is_system_role": True})
        role.permissions.set([wildcard] if "*.*" in codes else [perms_map[c] for c in codes if c in perms_map])
        roles[name] = role
    return roles


def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
    roles = _seed_roles(org)
    UserRole.objects.get_or_create(user=u, role=roles[role_name])
    return u


class PetCreateMinimalApiTests(APITestCase):
    URL = "/api/pets/"

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Clínica Mínima", timezone="UTC")
        cls.other = Organization.objects.create(name="Otra Clínica", timezone="UTC")
        cls.admin = _make_user("adm_min", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_create_minimal_without_species_or_birthdate(self):
        resp = self.client.post(
            self.URL,
            {'name': 'Lola', 'owner': {'name': 'Ana Soto', 'phone': '8112345678'}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        pet = Pet.objects.get(name='Lola')
        self.assertEqual(pet.species, '')          # pendiente
        self.assertIsNone(pet.birth_date)
        # Multi-tenant: la org viene del usuario, nunca del cliente.
        self.assertEqual(pet.organization_id, self.org.id)

    def test_create_still_requires_phone(self):
        resp = self.client.post(
            self.URL,
            {'name': 'Lola', 'owner': {'name': 'Ana Soto', 'phone': ''}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_invalid_species_rejected(self):
        resp = self.client.post(
            self.URL,
            {'name': 'Lola', 'species': 'dinosaurio',
             'owner': {'name': 'Ana Soto', 'phone': '8112345678'}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
