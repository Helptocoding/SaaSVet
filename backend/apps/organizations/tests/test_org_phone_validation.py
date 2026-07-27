"""PATCH /api/organizations/me/ — el teléfono de la clínica ya no acepta basura.

Antes `validate_phone` solo quitaba los no-dígitos: `"5"` se guardaba tal cual y
`"no sé"` se guardaba como `""` en silencio. El campo alimenta la plantilla de
URGENCIA del agente de WhatsApp y la señal `has_clinic_contact` del onboarding.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
from apps.users.models import User

ME_URL = '/api/organizations/me/'


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
    UserRole.objects.get_or_create(user=u, role=_seed_roles(org)[role_name])
    return u


class OrganizationPhoneValidationTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Clínica Teléfono", timezone="UTC")
        cls.admin = _make_user("adm_phone", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_valid_phone_is_normalized(self):
        r = self.client.patch(ME_URL, {'phone': '(55) 1234-5678'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.org.refresh_from_db()
        self.assertEqual(self.org.phone, '5512345678')

    def test_short_number_rejected(self):
        r = self.client.patch(ME_URL, {'phone': '5'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.org.refresh_from_db()
        self.assertEqual(self.org.phone, '')

    def test_text_rejected_instead_of_silent_blank(self):
        """El fallo que dejaba al ADMIN creyendo que había capturado el dato."""
        r = self.client.patch(ME_URL, {'phone': 'no sé'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filler_rejected(self):
        for filler in ['1111111111', '0000000000', '1234567890']:
            with self.subTest(filler=filler):
                r = self.client.patch(ME_URL, {'phone': filler}, format='json')
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, filler)

    def test_blank_allowed_so_the_rest_of_the_section_can_be_saved(self):
        """La org NACE con phone='': exigirlo aquí impediría guardar lo demás.

        La obligatoriedad la impone el onboarding (hito `has_clinic_contact`) y
        el gate del kill switch del agente — no el serializer.
        """
        r = self.client.patch(ME_URL, {'phone': '', 'city': 'Monterrey'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.org.refresh_from_db()
        self.assertEqual(self.org.phone, '')
        self.assertEqual(self.org.city, 'Monterrey')
