"""
Registro rápido (POST /api/appointments/create-with-patient/) — datos mínimos.

Misma regla que el alta manual de /pets: especie OPCIONAL ('' => pendiente),
teléfono SIGUE obligatorio. Blinda que ambos caminos manuales queden alineados.
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


class QuickRegisterMinimalTests(APITestCase):
    URL = "/api/appointments/create-with-patient/"

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Clínica QR", timezone="UTC")
        cls.admin = _make_user("adm_qr", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def _payload(self, **over):
        base = {
            'owner_name': 'Carlos Ruiz',
            'owner_phone': '8112345670',
            'pet_name': 'Rocky',
            'pet_species': '',            # pendiente
            'veterinarian': self.admin.id,
            'date': '2035-01-01',
            'start_time': '10:00',
            'end_time': '11:00',
            'reason': 'Chequeo general',
        }
        base.update(over)
        return base

    def test_quick_register_without_species(self):
        resp = self.client.post(self.URL, self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        pet = Pet.objects.get(name='Rocky')
        self.assertEqual(pet.species, '')        # pendiente
        self.assertEqual(pet.organization_id, self.org.id)

    def test_quick_register_still_requires_phone(self):
        resp = self.client.post(self.URL, self._payload(owner_phone='123'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('owner_phone', resp.data)

    def test_quick_register_invalid_species_rejected(self):
        resp = self.client.post(self.URL, self._payload(pet_species='dinosaurio'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pet_species', resp.data)
