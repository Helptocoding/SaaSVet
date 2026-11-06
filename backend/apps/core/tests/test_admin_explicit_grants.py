"""ADR p63: el ADMIN de clínica tiene una lista explícita, no `*.*`.

Se ejercen los seeds reales y se comprueba lo persistido y la autorización, no solo
listas de Python. Muchos tests del proyecto asignan `*.*` en sus fixtures, así que su
verde no dice nada sobre esta política.
"""
from io import StringIO
from pathlib import Path
import re
from unittest import mock
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.core.management.commands import seed_permissions as seed_module
from apps.core.management.commands.seed_demo_clinic import Command as DemoCommand
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions import (
    HybridPermission, RolePermission, _resolve_required, build_permissions_list,
    user_has_permission, user_has_permission_strict,
)
from apps.core.permissions_codes import (
    ORDINARY_CODES, PERMISSION_CODES, PERMISSIONS, SENSITIVE_CODES, role_grants,
)
from apps.organizations.models import Organization
from apps.organizations.signals import _seed_roles_for_org

FUTURE_CODE = 'future_module.execute'
CATALOG_PATH = 'apps.core.management.commands.seed_permissions.PERMISSION_CODES'
MANAGED = ('ADMIN', 'VET', 'ASSISTANT', 'AGENT')
# Las rutas que el ADMIN solo pasaba por `*.*`. Un 404 prueba que pasó RBAC.
FORMER_WILDCARD_ROUTES = (
    ('get', '/api/organizations/me/'),
    ('get', '/api/organizations/schedule/'),
    ('get', '/api/organizations/settings/'),
    ('get', '/api/settings/configuration/'),
    ('patch', f'/api/prescriptions/{uuid.uuid4()}/'),
    ('delete', f'/api/inventory/products/{uuid.uuid4()}/'),
    ('delete', f'/api/inventory/presentations/{uuid.uuid4()}/'),
    ('delete', f'/api/medical-records/{uuid.uuid4()}/'),
)


def seed():
    call_command('seed_permissions', stdout=StringIO())


def role_codes(org, name='ADMIN'):
    role = Role.objects.get(organization=org, name=name)
    return set(role.permissions.values_list('code', flat=True))


def make_admin(username, org):
    return get_user_model().objects.create_user(
        username=username, password='x', organization=org, role='ADMIN')


def make_user_with_role(username, org, role):
    return get_user_model().objects.create_user(
        username=username, password='x', organization=org, role=role)


def fresh(user):
    return get_user_model().objects.get(pk=user.pk)


def previous_release_seed():
    """Lo que hace el release anterior a p63 con el rol ADMIN: lo deja en `*.*`."""
    wildcard, _ = Permission.objects.get_or_create(code='*.*')
    for org in Organization.objects.all():
        Role.objects.get(organization=org, name='ADMIN').permissions.set([wildcard])


def _walk(patterns, prefix=''):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern


def codes_required_by_routes():
    """Código que exige cada ruta real, con el mismo `_resolve_required` de producción."""
    factory = APIRequestFactory()
    required = {}
    for route, pattern in _walk(get_resolver().url_patterns):
        callback = pattern.callback
        cls = getattr(callback, 'cls', None)
        if cls is None:
            continue
        actions = getattr(callback, 'actions', None) or {}
        methods = actions or {
            name: None for name in cls.http_method_names
            if name not in ('options', 'head', 'trace') and hasattr(cls, name)
        }
        for method, action in methods.items():
            view = cls(**getattr(callback, 'initkwargs', {}))
            if action:
                view.action_map = actions
                view.action = action
            view.kwargs = {name: '1' for name in pattern.pattern.regex.groupindex}
            view.args = ()
            view.format_kwarg = None
            request = Request(factory.generic(method.upper(), '/x'))
            request.user = AnonymousUser()
            view.request = request
            checks = [p for p in view.get_permissions()
                      if isinstance(p, (HybridPermission, RolePermission))]
            for check in checks:
                check.has_permission(request, view)
            code = _resolve_required(request, view) if checks else None
            if code:
                required[(method.upper(), route)] = code
    return required


class PolicyIsExplicit(SimpleTestCase):
    def test_no_clinic_role_has_a_wildcard(self):
        for role in MANAGED:
            with self.subTest(role=role):
                self.assertEqual([c for c in PERMISSIONS[role] if c.endswith('.*')], [])

    def test_platform_keeps_its_wildcard(self):
        self.assertEqual(PERMISSIONS['ADMIN_SAAS'], ['*.*'])

    def test_every_grant_is_in_the_catalog(self):
        """El seed fallaría, o antes descartaba en silencio, lo que no esté en el catálogo."""
        for role in MANAGED:
            with self.subTest(role=role):
                self.assertEqual(set(PERMISSIONS[role]) - set(PERMISSION_CODES), set())

    def test_admin_receives_the_approved_matrix(self):
        # Un código nuevo hace fallar este test: obliga a decidir si el ADMIN lo recibe.
        self.assertEqual(set(PERMISSIONS['ADMIN']), set(PERMISSION_CODES))
        self.assertEqual(len(PERMISSIONS['ADMIN']), len(set(PERMISSIONS['ADMIN'])))

    def test_codes_added_by_the_adr_have_the_approved_class(self):
        self.assertLessEqual({'organization.list', 'prescription.update'}, ORDINARY_CODES)
        self.assertLessEqual({'inventory.destroy', 'medicalrecord.destroy'}, SENSITIVE_CODES)

    def test_every_route_requires_a_code_the_admin_holds(self):
        required = codes_required_by_routes()
        self.assertGreater(len(required), 150, 'La enumeración de rutas dejó de encontrarlas')
        missing = {key: code for key, code in required.items() if code not in PERMISSIONS['ADMIN']}
        self.assertEqual(missing, {})


class EveryProgrammaticCheckUsesAGrantedCode(SimpleTestCase):
    """Las rutas no lo ven todo: un servicio también puede pedir un permiso."""
    CHECK = re.compile(
        r"""\b(?:user_has_permission(?:_strict|_db_only)?|_has_required_permission|_recipients_with_capability)"""
        r"""\(\s*[^,()]+,\s*['"]([^'"]+)['"]""")

    def test_codes_asked_by_services_are_held_by_the_admin(self):
        found = set()
        for path in Path('apps').rglob('*.py'):
            if 'tests' not in path.parts and 'migrations' not in path.parts:
                found |= set(self.CHECK.findall(path.read_text(encoding='utf-8', errors='ignore')))
        self.assertIn('inventory.view', found, 'La búsqueda dejó de encontrar los chequeos')
        self.assertEqual(found - set(PERMISSIONS['ADMIN']), set())


class SeededAdminKeepsCapabilities(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.orgs = [Organization.objects.create(name=f'Clinica {n}', timezone='UTC') for n in 'AB']
        previous_release_seed()
        seed()
        cls.admins = [make_admin(f'admin_{n}', org) for n, org in enumerate(cls.orgs)]

    def test_the_wildcard_is_replaced_in_every_organization(self):
        for org in self.orgs:
            with self.subTest(org=org.name):
                self.assertEqual(role_codes(org), set(PERMISSIONS['ADMIN']))

    def test_effective_set_is_the_same_for_each_admin(self):
        for admin in self.admins:
            with self.subTest(user=admin.username):
                self.assertEqual(set(build_permissions_list(fresh(admin))), set(PERMISSION_CODES))
                for code in set(codes_required_by_routes().values()):
                    self.assertTrue(user_has_permission_strict(fresh(admin), code), code)

    @mock.patch('apps.core.permissions._legal_blocks', return_value=False)
    def test_routes_that_depended_on_the_wildcard_still_pass_rbac(self, _legal):
        client = APIClient()
        client.force_authenticate(user=fresh(self.admins[0]))
        for method, url in FORMER_WILDCARD_ROUTES:
            with self.subTest(method=method, url=url):
                response = getattr(client, method)(url, {}, format='json')
                self.assertNotEqual(response.status_code, 403, response.data)

    @mock.patch('apps.core.permissions._legal_blocks', return_value=False)
    def test_unimplemented_method_is_405_not_403(self, _legal):
        vet = make_user_with_role('vet_method', self.orgs[0], 'VET')
        for user in (fresh(self.admins[0]), vet):
            client = APIClient()
            client.force_authenticate(user=user)
            with self.subTest(role=user.role):
                self.assertEqual(client.delete('/api/organizations/me/').status_code, 405)

    def test_implemented_method_without_the_code_is_still_403(self):
        vet = make_user_with_role('vet_denied', self.orgs[0], 'VET')
        client = APIClient()
        client.force_authenticate(user=vet)
        self.assertEqual(client.patch('/api/organizations/me/', {}, format='json').status_code, 403)

    def test_admin_still_receives_stock_notifications(self):
        from apps.notifications.services import _recipients_with_capability
        recipients = _recipients_with_capability(self.orgs[0], 'inventory.view')
        self.assertIn(self.admins[0].pk, [user.pk for user in recipients])

    def test_stock_notifications_do_not_reach_other_roles(self):
        from apps.notifications.services import _recipients_with_capability
        vet = make_user_with_role('vet_stock', self.orgs[0], 'VET')
        recipients = _recipients_with_capability(self.orgs[0], 'inventory.view')
        self.assertNotIn(vet.pk, [user.pk for user in recipients])

    def test_other_roles_do_not_gain_the_new_admin_codes(self):
        new_codes = {'organization.list', 'prescription.update', 'inventory.destroy',
                     'medicalrecord.destroy', 'inventory.view'}
        for role in ('VET', 'ASSISTANT', 'AGENT'):
            with self.subTest(role=role):
                self.assertEqual(role_codes(self.orgs[0], role) & new_codes, set())


class FutureCodesAreNotGrantedAutomatically(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica', timezone='UTC')
        cls.admin = make_admin('admin', cls.org)
        cls.fallback_admin = make_admin('admin_fallback', cls.org)
        UserRole.objects.filter(user=cls.fallback_admin).delete()
        cls.superuser = get_user_model().objects.create_superuser(
            username='root', password='x', email='root@example.mx')

    def seed_with_future_code(self):
        with mock.patch(CATALOG_PATH, [*PERMISSION_CODES, FUTURE_CODE]):
            seed()

    def test_admin_does_not_receive_it_by_database_or_fallback(self):
        self.seed_with_future_code()
        self.assertTrue(Permission.objects.filter(code=FUTURE_CODE).exists())
        self.assertFalse(user_has_permission(fresh(self.admin), FUTURE_CODE))
        self.assertFalse(user_has_permission_strict(fresh(self.admin), FUTURE_CODE))
        self.assertFalse(user_has_permission(fresh(self.fallback_admin), FUTURE_CODE))

    def test_platform_is_not_affected(self):
        self.seed_with_future_code()
        self.assertTrue(user_has_permission(self.superuser, FUTURE_CODE))

    def test_classifying_it_does_not_grant_it(self):
        with mock.patch('apps.core.permissions_codes.ORDINARY_CODES', ORDINARY_CODES | {FUTURE_CODE}):
            self.seed_with_future_code()
        self.assertFalse(user_has_permission(fresh(self.admin), FUTURE_CODE))

    def test_adding_it_to_the_list_and_seeding_grants_it(self):
        grants = [*PERMISSIONS['ADMIN'], FUTURE_CODE]
        with mock.patch.dict(PERMISSIONS, {'ADMIN': grants}):
            self.seed_with_future_code()
        self.assertTrue(user_has_permission(fresh(self.admin), FUTURE_CODE))


class ThreeWritersShareThePolicy(TestCase):
    def assert_managed_roles_follow_the_policy(self, org):
        for role in MANAGED:
            with self.subTest(org=org.name, role=role):
                self.assertEqual(role_codes(org, role), set(role_grants(role, is_demo=org.is_demo)))

    def test_new_organization_signal(self):
        org = Organization.objects.create(name='Nueva', timezone='UTC')
        self.assert_managed_roles_follow_the_policy(org)

    def test_seed_roles_for_org_repairs_a_role(self):
        org = Organization.objects.create(name='Reparar', timezone='UTC')
        Role.objects.get(organization=org, name='ADMIN').permissions.clear()
        _seed_roles_for_org(org)
        self.assert_managed_roles_follow_the_policy(org)

    def test_seed_permissions(self):
        org = Organization.objects.create(name='Release', timezone='UTC')
        Role.objects.get(organization=org, name='VET').permissions.clear()
        seed()
        self.assert_managed_roles_follow_the_policy(org)

    def test_demo_writer_only_subtracts_imports(self):
        org = Organization.objects.create(name='Demo', timezone='UTC', is_demo=True)
        DemoCommand()._restrict_demo_import(org)
        self.assert_managed_roles_follow_the_policy(org)
        self.assertEqual(
            set(PERMISSIONS['ADMIN']) - role_codes(org),
            {code for code in PERMISSIONS['ADMIN'] if code.startswith('import.')})

    def test_release_does_not_undo_the_demo_restriction(self):
        org = Organization.objects.create(name='Demo', timezone='UTC', is_demo=True)
        admin = make_admin('admin_demo', org)
        DemoCommand()._restrict_demo_import(org)
        seed()
        self.assertFalse(user_has_permission(fresh(admin), 'import.create'))
        self.assertTrue(user_has_permission(fresh(admin), 'organization.update'))

    def test_demo_does_not_receive_a_catalog_code_outside_the_list(self):
        org = Organization.objects.create(name='Demo', timezone='UTC', is_demo=True)
        with mock.patch(CATALOG_PATH, [*PERMISSION_CODES, FUTURE_CODE]):
            seed()
        self.assertNotIn(FUTURE_CODE, role_codes(org))


class PreflightBlocksRemainingWildcards(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Clinica', timezone='UTC')
        cls.admin = make_admin('admin', cls.org)
        wildcard, _ = Permission.objects.get_or_create(code='*.*')
        cls.custom = Role.objects.create(name='DUENO', organization=cls.org)
        cls.custom.permissions.set([wildcard])
        UserRole.objects.create(user=cls.admin, role=cls.custom)
        previous_release_seed()

    def assert_blocked(self, *args):
        with self.assertRaisesMessage(CommandError, 'DUENO'):
            call_command('seed_permissions', *args, stdout=StringIO())
        self.assertEqual(role_codes(self.org), {'*.*'}, 'El seed bloqueado no debe escribir')

    def test_custom_role_with_wildcard_blocks_seed_and_dry_run(self):
        self.assert_blocked()
        self.assert_blocked('--dry-run')

    def test_resource_wildcard_also_blocks(self):
        partial, _ = Permission.objects.get_or_create(code='invoice.*')
        self.custom.permissions.set([partial])
        self.assert_blocked()

    def test_documented_exception_is_allowed(self):
        exception = frozenset({(str(self.org.public_id), 'DUENO')})
        with mock.patch.object(seed_module, 'WILDCARD_ROLE_EXCEPTIONS', exception):
            seed()
        self.assertEqual(role_codes(self.org), set(PERMISSIONS['ADMIN']))

    def test_combined_role_without_wildcard_gets_only_the_union(self):
        code, _ = Permission.objects.get_or_create(code='extra.action')
        self.custom.permissions.set([code])
        with mock.patch(CATALOG_PATH, [*PERMISSION_CODES, FUTURE_CODE]):
            seed()
        admin = fresh(self.admin)
        self.assertTrue(user_has_permission(admin, 'extra.action'))
        self.assertFalse(user_has_permission(admin, FUTURE_CODE))

    def test_dry_run_writes_nothing_and_reports_changes(self):
        self.custom.permissions.clear()
        out = StringIO()
        call_command('seed_permissions', '--dry-run', stdout=out)
        self.assertEqual(role_codes(self.org), {'*.*'})
        self.assertIn('ADMIN: gana', out.getvalue())
        self.assertIn('Rol no gestionado DUENO', out.getvalue())
        self.assertIn('Sin cambios', out.getvalue())

    def test_grant_outside_the_catalog_blocks(self):
        self.custom.permissions.clear()
        with mock.patch.dict(PERMISSIONS, {'ADMIN': [*PERMISSIONS['ADMIN'], FUTURE_CODE]}):
            with self.assertRaisesMessage(CommandError, FUTURE_CODE):
                seed()
        self.assertEqual(role_codes(self.org), {'*.*'})


class RollbackScenarios(TestCase):
    """El release anterior se representa con lo que ese seed hacía con el rol ADMIN."""

    @classmethod
    def setUpTestData(cls):
        cls.orgs = [Organization.objects.create(name=f'Clinica {n}', timezone='UTC') for n in 'AB']
        cls.admin = make_admin('admin', cls.orgs[0])

    def snapshot(self):
        return {
            (org.pk, role): role_codes(org, role)
            for org in self.orgs for role in ('VET', 'ASSISTANT', 'AGENT')
        }

    def test_explicit_list_to_wildcard_recovers_capabilities(self):
        seed()
        others = self.snapshot()
        previous_release_seed()
        self.assertTrue(user_has_permission(fresh(self.admin), FUTURE_CODE))
        self.assertEqual(role_codes(self.orgs[0]), {'*.*'})
        self.assertEqual(self.snapshot(), others)

    def test_rolling_back_with_new_codes_seeded_is_consistent(self):
        with mock.patch(CATALOG_PATH, [*PERMISSION_CODES, FUTURE_CODE]):
            seed()
        previous_release_seed()
        seed()
        self.assertEqual(Permission.objects.filter(code=FUTURE_CODE).count(), 1)
        for org in self.orgs:
            self.assertEqual(Role.objects.filter(organization=org, name='ADMIN').count(), 1)
            self.assertEqual(role_codes(org), set(PERMISSIONS['ADMIN']))

    def fail_on_second_organization(self):
        real = Role.objects.get_or_create
        second = self.orgs[1]

        def flaky(**kwargs):
            if kwargs['organization'] == second:
                raise RuntimeError('fallo a mitad del seed')
            return real(**kwargs)
        return mock.patch.object(Role.objects, 'get_or_create', side_effect=flaky)

    def test_seed_failing_midway_converges_when_rerun(self):
        previous_release_seed()
        with self.fail_on_second_organization(), self.assertRaises(RuntimeError):
            seed()
        self.assertEqual(role_codes(self.orgs[0]), set(PERMISSIONS['ADMIN']))
        self.assertEqual(role_codes(self.orgs[1]), {'*.*'})

        seed()
        for org in self.orgs:
            self.assertEqual(role_codes(org), set(PERMISSIONS['ADMIN']))

    def test_rollback_after_a_midway_failure_converges(self):
        previous_release_seed()
        with self.fail_on_second_organization(), self.assertRaises(RuntimeError):
            seed()
        previous_release_seed()
        for org in self.orgs:
            self.assertEqual(role_codes(org), {'*.*'})
