"""
test_legacy_view_org_id_writable.py — Día 6 audit F21 (ADR p18 Fase 4)

Cubre el caso específico de body con campos `id` o `public_id` en PATCH
sobre OrganizationLegacyView/OrganizationMeView. Ambos deben ser
read_only — DRF los ignora silenciosamente, pero verificamos que la
mutación NO ocurre (defense-in-depth contra audit drift).
"""
from uuid import uuid4

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.users.models import User


def _seed_admin(org):
    wildcard, _ = Permission.objects.get_or_create(code="*.*")
    role, _ = Role.objects.get_or_create(
        name="ADMIN", organization=org, defaults={"is_system_role": True}
    )
    role.permissions.set([wildcard])
    return role


def _make_admin(username, org):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role="ADMIN"
    )
    UserRole.objects.get_or_create(user=u, role=_seed_admin(org))
    return u


class OrganizationLegacyImmutableIdTests(APITestCase):
    """El endpoint legacy ya venció: ningún body puede mutar la org."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org IdMut", timezone="UTC")
        cls.admin = _make_admin("idmut_admin", cls.org)
        cls.original_pk = cls.org.pk
        cls.original_public_id = cls.org.public_id

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_patch_with_id_in_body_is_rejected_after_sunset(self):
        """El legacy retirado no admite mutaciones aunque incluya un id."""
        r = self.client.patch(
            f'/api/organizations/{self.org.pk}/',
            {'id': 999999, 'name': 'After Patch'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_410_GONE, r.content)
        self.assertEqual(r.data['code'], 'endpoint_sunset')
        self.org.refresh_from_db()
        self.assertEqual(self.org.pk, self.original_pk)
        self.assertEqual(self.org.name, 'Org IdMut')

    def test_patch_with_public_id_in_body_is_rejected_after_sunset(self):
        """El endpoint retirado no puede cambiar ni nombre ni identificador."""
        foreign_uuid = uuid4()
        r = self.client.patch(
            f'/api/organizations/{self.org.pk}/',
            {'public_id': str(foreign_uuid), 'name': 'PubId Patch'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_410_GONE, r.content)
        self.assertEqual(r.data['code'], 'endpoint_sunset')
        self.org.refresh_from_db()
        self.assertEqual(self.org.public_id, self.original_public_id)
        self.assertNotEqual(self.org.public_id, foreign_uuid)
        self.assertEqual(self.org.name, 'Org IdMut')

    def test_me_endpoint_patch_with_id_in_body_ignores_id(self):
        """Mismo test sobre /me/ singleton."""
        r = self.client.patch(
            '/api/organizations/me/',
            {'id': 999999, 'name': 'Me Patch'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.pk, self.original_pk)

    def test_me_endpoint_patch_with_public_id_in_body_ignores_it(self):
        foreign_uuid = uuid4()
        r = self.client.patch(
            '/api/organizations/me/',
            {'public_id': str(foreign_uuid), 'name': 'Me Pubid'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.public_id, self.original_public_id)


class MeResponseContainsPublicIdTests(APITestCase):
    """Verifica que OrganizationSerializer expone ambos `id` y `public_id`
    (deuda pre-beta D5 documentada en POST-BETA-DEBT.md)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Me Pubid Org", timezone="UTC")
        cls.admin = _make_admin("me_pubid", cls.org)

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_me_response_has_both_id_and_public_id(self):
        r = self.client.get('/api/organizations/me/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('id', r.data)
        self.assertIn('public_id', r.data)
        self.assertEqual(r.data['id'], self.org.pk)
        self.assertEqual(str(r.data['public_id']), str(self.org.public_id))
