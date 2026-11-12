"""
Tests del refactor OrganizationViewSet → OrganizationMeView (Issue #10 / PR-4B / ADR p16).

Cubre:
- Singleton /api/organizations/me/ — GET/PATCH/405 + guard null org
- Router list/create/destroy removidos → 404 en /api/organizations/
- Legacy /api/organizations/<pk>/ retirado en el orden 6 (D2) → 404
"""

from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS
from apps.organizations.models import Organization
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


class OrganizationMeViewTests(APITestCase):
    """Singleton /api/organizations/me/ — sin pk en URL."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Me Test", timezone="UTC")
        cls.admin = _make_user("adm_me", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_get_returns_own_org(self):
        r = self.client.get('/api/organizations/me/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['id'], self.org.pk)
        self.assertEqual(r.data['name'], "Org Me Test")

    def test_patch_updates_own_org(self):
        r = self.client.patch(
            '/api/organizations/me/',
            {'name': 'Org Me Renamed'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, 'Org Me Renamed')

    def test_delete_returns_405(self):
        r = self.client.delete('/api/organizations/me/')
        self.assertEqual(r.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_post_returns_405(self):
        r = self.client.post('/api/organizations/me/', {'name': 'X'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_me_blocks_user_without_organization(self):
        """Guard PR-4B HIGH: user.organization=None debe ser bloqueado.
        RBAC (HybridPermission) rechaza con 403 antes que el guard interno
        del view se active — defensa en capas. El test acepta cualquier
        respuesta no-200 (403 RBAC o 404 guard view); cualquiera evita el
        crash TypeError al serializar None que el guard previene."""
        from apps.users.models import User
        user_no_org = User.objects.create_user(
            username="user_no_org", password="x", organization=None, role="ASSISTANT",
        )
        self.client.force_authenticate(user_no_org)
        r = self.client.get('/api/organizations/me/')
        self.assertIn(
            r.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            f"user.organization=None debe ser rechazado, no crashear (got {r.status_code})",
        )


class OrganizationRouterRemovedTests(APITestCase):
    """Verifica que /api/organizations/ (list/create) ya no existe."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Router Test", timezone="UTC")
        cls.admin = _make_user("adm_router", cls.org, "ADMIN")

    def setUp(self):
        self.client.force_authenticate(self.admin)

    def test_list_route_returns_404(self):
        """GET /api/organizations/ (sin pk, sin /me/) ya no está enrutado."""
        r = self.client.get('/api/organizations/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_route_returns_404(self):
        """POST /api/organizations/ ya no está enrutado."""
        r = self.client.post('/api/organizations/', {'name': 'X', 'timezone': 'UTC'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_legacy_pk_route_is_gone(self):
        """D2 (orden 6): la vista legacy se retiró tras su Sunset; la ruta ya no existe."""
        for method in ('get', 'patch', 'delete'):
            with self.subTest(method=method):
                r = getattr(self.client, method)(
                    f'/api/organizations/{self.org.pk}/', {'name': 'X'}, format='json')
                self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, 'Org Router Test')
