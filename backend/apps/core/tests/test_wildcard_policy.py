"""H-1 reducida: cada código se clasifica, y excluir uno del comodín tiene efecto.

No retira el `*.*` del ADMIN de clínica; eso exige un ADR. Lo que garantiza es que
un código nuevo no entra al comodín sin una decisión, y que un código exclusivo de
plataforma tiene dónde declararse para que el comodín no lo conceda.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.core.models import Permission, Role, UserRole
from apps.core.permissions import (
    _is_allowed, user_has_permission, user_has_permission_strict,
)
from apps.core.permissions_codes import (
    ADMIN_WILDCARD_ORDINARY, ADMIN_WILDCARD_SENSITIVE, PERMISSION_CODES, PERMISSIONS,
    WILDCARD_EXCLUDED,
)
from apps.organizations.models import Organization

PLATFORM_CODE = 'organization.provision'
EXCLUDED_PATH = 'apps.core.permissions.WILDCARD_EXCLUDED'


class EveryCodeIsClassified(SimpleTestCase):
    def test_groups_partition_the_catalog_exactly(self):
        groups = (ADMIN_WILDCARD_ORDINARY, ADMIN_WILDCARD_SENSITIVE, WILDCARD_EXCLUDED)
        classified = [code for group in groups for code in group]
        self.assertEqual(len(classified), len(set(classified)), 'A code is in two groups')
        self.assertEqual(set(classified) - set(PERMISSION_CODES), set(), 'Classified but not in catalog')
        self.assertEqual(set(PERMISSION_CODES) - set(classified), set(),
                         'New code: classify it in permissions_codes.py')

    def test_money_access_and_identity_codes_stay_marked_sensitive(self):
        for code in ('billing.refund', 'invoice.void_terminal', 'staff.reset_password',
                     'agentinbox.identity_verify'):
            with self.subTest(code=code):
                self.assertIn(code, ADMIN_WILDCARD_SENSITIVE)


class ExclusionIsEnforcedAtEvaluation(SimpleTestCase):
    def test_no_current_code_loses_access(self):
        for code in PERMISSION_CODES:
            with self.subTest(code=code):
                self.assertTrue(_is_allowed(code, PERMISSIONS['ADMIN']))

    def test_global_wildcard_does_not_grant_an_excluded_code(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertFalse(_is_allowed(PLATFORM_CODE, PERMISSIONS['ADMIN']))

    def test_resource_wildcard_does_not_grant_an_excluded_code(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertFalse(_is_allowed(PLATFORM_CODE, ['organization.*']))

    def test_explicit_assignment_still_grants_it(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertTrue(_is_allowed(PLATFORM_CODE, [PLATFORM_CODE]))

    def test_exclusion_does_not_affect_other_codes(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertTrue(_is_allowed('billing.refund', PERMISSIONS['ADMIN']))


class ExclusionReachesEveryPermissionPath(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica', timezone='UTC')
        wildcard, _ = Permission.objects.get_or_create(code='*.*')
        role, _ = Role.objects.get_or_create(
            name='ADMIN', organization=cls.org, defaults={'is_system_role': True})
        role.permissions.set([wildcard])
        users = get_user_model().objects
        cls.db_admin = users.create_user(
            username='db_admin', password='x', organization=cls.org, role='ADMIN')
        UserRole.objects.get_or_create(user=cls.db_admin, role=role)
        cls.static_admin = users.create_user(
            username='static_admin', password='x', organization=cls.org, role='ADMIN')
        UserRole.objects.filter(user=cls.static_admin).delete()
        cls.superuser = users.create_superuser(username='root', password='x', email='r@e.mx')

    def test_clinic_admin_is_denied_through_database_roles(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertFalse(user_has_permission(self.db_admin, PLATFORM_CODE))
            self.assertFalse(user_has_permission_strict(self.db_admin, PLATFORM_CODE))

    def test_clinic_admin_is_denied_through_static_fallback(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertFalse(user_has_permission(self.static_admin, PLATFORM_CODE))

    def test_platform_superuser_is_not_affected(self):
        with mock.patch(EXCLUDED_PATH, frozenset({PLATFORM_CODE})):
            self.assertTrue(user_has_permission(self.superuser, PLATFORM_CODE))
