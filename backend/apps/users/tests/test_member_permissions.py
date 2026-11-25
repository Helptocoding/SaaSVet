"""ADR p69: permisos por integrante sobre su rol.

- El catálogo nombra cada código del RBAC y lo sitúa en un área.
- Permisos efectivos = (rol ∪ concedidos) − quitados, en todas las comprobaciones
  (petición, validación de otro usuario, ``/me/``, la lista de asignables de
  WhatsApp). Se guarda solo la diferencia con el rol.
- Solo un ADMIN concede o quita; los permisos reservados no se conceden a otro rol
  ni se quitan a un ADMIN; nadie se quita a sí mismo permisos de administración.
- Al cambiar de rol con ajustes hay que decidir si se conservan.
- Guardar la ficha (datos, rol y permisos) es una sola transacción.
- Cambiar permisos exige declarar los que se veían (§12): sin ellos 400; si
  cambiaron, 409 y nada se escribe, también con dos ADMIN guardando a la vez.
"""
import threading
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.core.models import UserPermissionOverride, set_current_user
from apps.core.permission_catalog import (
    ADMIN_RESERVED, ADMINISTRATION_CODES, PERMISSIONS as CATALOG, catalog_payload,
    permission_area,
)
from apps.core.permissions import user_has_permission, user_has_permission_strict
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS, SENSITIVE_CODES
from apps.organizations.models import Organization
from apps.users import member_permissions
from apps.users.member_permissions import effective_codes, role_default_codes
from apps.users.services import PermissionsChanged, update_staff_member
from apps.users.models import StaffAccessEvent

User = get_user_model()
FAST = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


class CatalogTests(SimpleTestCase):
    def test_every_rbac_code_has_a_name_and_an_area(self):
        self.assertEqual(set(CATALOG), set(PERMISSION_CODES))
        for code in PERMISSION_CODES:
            self.assertIn(permission_area(code), {'clinical', 'operation', 'administration'}, code)
        listed = [p['code'] for area in catalog_payload() for g in area['groups'] for p in g['permissions']]
        self.assertEqual(sorted(listed), sorted(PERMISSION_CODES))

    def test_reserved_codes_are_administration_and_admin_only(self):
        self.assertTrue(ADMIN_RESERVED <= ADMINISTRATION_CODES)
        self.assertIn('staff.manage_permissions', SENSITIVE_CODES)
        self.assertTrue(ADMIN_RESERVED <= set(PERMISSIONS['ADMIN']))
        for role in ('VET', 'ASSISTANT', 'AGENT'):
            self.assertFalse(ADMIN_RESERVED & set(PERMISSIONS[role]), role)

    def test_reads_everyone_needs_are_not_administration(self):
        for code in ('staff.list', 'dashboard.view', 'organization.retrieve', 'service.list'):
            self.assertEqual(permission_area(code), 'operation', code)


@FAST
class _Base(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica Permisos', timezone='UTC')
        self.admin = User.objects.create_user(
            username='pm_admin', email='pm_admin@example.com', password='x',
            organization=self.org, role='ADMIN', first_name='Ana')
        self.vet = User.objects.create_user(
            username='pm_vet', email='pm_vet@example.com', password='x',
            organization=self.org, role='VET', license_number='1234567', attends_patients=True)
        self.assistant = User.objects.create_user(
            username='pm_asis', email='pm_asis@example.com', password='x',
            organization=self.org, role='ASSISTANT')
        self.client.force_authenticate(self.admin)

    def defaults(self, role):
        return role_default_codes(self.org.pk, role)

    def patch(self, member, body, client=None, *, precondition=True):
        # §12: quien envía permisos declara los que veía; por omisión, los vigentes.
        if precondition and 'permissions' in body and 'expected_permissions' not in body:
            body = {**body, 'expected_permissions': sorted(effective_codes(self.fresh(member)))}
        return (client or self.client).patch(f'/api/staff/{member.public_id}/', body, format='json')

    def fresh(self, user):
        return User.objects.get(pk=user.pk)


class EffectivePermissionsTests(_Base):
    def test_grant_and_revoke_change_every_check(self):
        desired = (self.defaults('ASSISTANT') | {'billing.refund'}) - {'appointment.destroy'}
        res = self.patch(self.assistant, {'permissions': sorted(desired)})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data['permission_overrides'],
                         {'granted': ['billing.refund'], 'revoked': ['appointment.destroy']})
        member = self.fresh(self.assistant)
        self.assertTrue(user_has_permission(member, 'billing.refund'))
        self.assertTrue(user_has_permission_strict(self.fresh(self.assistant), 'billing.refund'))
        self.assertFalse(user_has_permission(self.fresh(self.assistant), 'appointment.destroy'))
        client = APIClient()
        client.force_authenticate(self.fresh(self.assistant))
        me = client.get('/api/me/').data['permissions']
        self.assertIn('billing.refund', me)
        self.assertNotIn('appointment.destroy', me)

    def test_a_revoke_wins_over_a_wildcard_role(self):
        from apps.core.models import Permission, Role, UserRole
        wildcard_perm, _ = Permission.objects.get_or_create(code='inventory.*')
        custom = Role.objects.create(name='Bodega', organization=self.org)
        custom.permissions.add(wildcard_perm)
        UserRole.objects.create(user=self.assistant, role=custom)
        self.assertTrue(user_has_permission(self.fresh(self.assistant), 'inventory.destroy'))
        UserPermissionOverride.objects.create(
            organization=self.org, user=self.assistant,
            permission=Permission.objects.get(code='inventory.destroy'), effect='revoke')
        self.assertFalse(user_has_permission(self.fresh(self.assistant), 'inventory.destroy'))
        self.assertTrue(user_has_permission(self.fresh(self.assistant), 'inventory.update'))

    def test_only_the_difference_with_the_role_is_stored(self):
        self.patch(self.vet, {'permissions': sorted(self.defaults('VET') | {'billing.refund'})})
        res = self.patch(self.vet, {'permissions': sorted(self.defaults('VET'))})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(UserPermissionOverride.objects.filter(user=self.vet).exists())
        events = list(StaffAccessEvent.objects.filter(member=self.vet, kind='permissions_changed')
                      .order_by('created_at', 'pk').values_list('changes', flat=True))
        self.assertEqual(events, [
            {'granted': ['billing.refund'], 'revoked': [], 'restored': []},
            {'granted': [], 'revoked': [], 'restored': ['billing.refund']},
        ])

    def test_unknown_codes_are_rejected(self):
        res = self.patch(self.vet, {'permissions': sorted(self.defaults('VET') | {'astro.logia'})})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(UserPermissionOverride.objects.exists())


class RulesTests(_Base):
    def test_reserved_codes_cannot_be_granted_to_another_role(self):
        for code in ('staff.reset_password', 'staff.change_role', 'staff.manage_permissions'):
            res = self.patch(self.vet, {'permissions': sorted(self.defaults('VET') | {code})})
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, code)
        self.assertFalse(UserPermissionOverride.objects.exists())

    def test_an_admin_always_keeps_the_reserved_codes(self):
        other = User.objects.create_user(username='pm_admin2', password='x',
                                         organization=self.org, role='ADMIN')
        res = self.patch(other, {'permissions': sorted(self.defaults('ADMIN') - {'staff.reset_password'})})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.patch(other, {'permissions': sorted(self.defaults('ADMIN') - {'organization.update'})})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(user_has_permission(self.fresh(other), 'organization.update'))

    def test_nobody_removes_their_own_administration_permissions(self):
        res = self.patch(self.admin, {'permissions': sorted(self.defaults('ADMIN') - {'organization.update'})})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('administración', str(res.data))
        res = self.patch(self.admin, {'permissions': sorted(self.defaults('ADMIN') - {'billing.refund'})})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

    def test_only_admins_edit_permissions(self):
        client = APIClient()
        client.force_authenticate(self.vet)
        res = self.patch(self.assistant, {'permissions': sorted(self.defaults('ASSISTANT'))}, client)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('staff.manage_permissions', PERMISSIONS['ADMIN'])

    def test_service_accounts_and_other_clinics_are_not_reachable(self):
        agent = User.objects.create_user(username='pm_agent', password='x', organization=self.org,
                                         role='AGENT', is_service_account=True)
        foreign = User.objects.create_user(username='pm_f', password='x', role='VET',
                                           organization=Organization.objects.create(name='Otra P', timezone='UTC'))
        for member in (agent, foreign):
            self.assertEqual(self.patch(member, {'permissions': []}).status_code, status.HTTP_404_NOT_FOUND)


class RoleChangeWithCustomPermissionsTests(_Base):
    def setUp(self):
        super().setUp()
        self.patch(self.assistant, {'permissions': sorted(self.defaults('ASSISTANT') | {'billing.refund'})})

    def test_the_caller_must_decide_what_happens_to_them(self):
        res = self.patch(self.assistant, {'role': 'VET', 'license_number': '7654321'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('keep_custom_permissions', res.data.get('errors', res.data))
        self.assertEqual(self.fresh(self.assistant).role, 'ASSISTANT')

    def test_keeping_them_reapplies_them_on_the_new_role(self):
        res = self.patch(self.assistant, {'role': 'VET', 'license_number': '7654321',
                                          'keep_custom_permissions': True})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        member = self.fresh(self.assistant)
        self.assertEqual(member.role, 'VET')
        self.assertTrue(user_has_permission(member, 'billing.refund'))
        event = StaffAccessEvent.objects.get(member=self.assistant, kind='role_changed')
        self.assertEqual(event.changes['custom_permissions'], 'kept')

    def test_discarding_them_leaves_the_role_defaults(self):
        res = self.client.post(f'/api/staff/{self.assistant.public_id}/role/',
                               {'role': 'VET', 'keep_custom_permissions': False}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, 'VET sin cédula')
        self.patch(self.assistant, {'license_number': '7654321'})
        res = self.client.post(f'/api/staff/{self.assistant.public_id}/role/',
                               {'role': 'VET', 'keep_custom_permissions': False}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(UserPermissionOverride.objects.filter(user=self.assistant).exists())
        self.assertEqual(res.data['permission_overrides'], {'granted': [], 'revoked': []})


class AtomicSaveTests(_Base):
    def test_one_invalid_part_saves_nothing(self):
        res = self.patch(self.vet, {'first_name': 'Nueva',
                                    'permissions': sorted(self.defaults('VET') | {'staff.change_role'})})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.fresh(self.vet).first_name, '')
        res = self.patch(self.assistant, {'role': 'ADMIN',
                                          'permissions': sorted(self.defaults('ASSISTANT'))})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, 'ADMIN sin sus reservados')
        self.assertEqual(self.fresh(self.assistant).role, 'ASSISTANT')

    def test_profile_role_and_permissions_together(self):
        res = self.patch(self.assistant, {
            'first_name': 'Rosa', 'role': 'ADMIN', 'attends_patients': False,
            'permissions': sorted(self.defaults('ADMIN') - {'billing.refund'}),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        member = self.fresh(self.assistant)
        self.assertEqual((member.first_name, member.role), ('Rosa', 'ADMIN'))
        self.assertFalse(user_has_permission(member, 'billing.refund'))
        self.assertEqual(
            sorted(StaffAccessEvent.objects.filter(member=self.assistant).values_list('kind', flat=True)),
            ['permissions_changed', 'profile_updated', 'role_changed'])


class ListAndCatalogTests(_Base):
    def test_list_carries_permissions_without_a_query_per_member(self):
        def queries():
            with CaptureQueriesContext(connection) as ctx:
                res = self.client.get('/api/staff/')
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            return res, len(ctx.captured_queries)
        queries()  # la primera petición llena cachés de una sola vez (legal, permisos del actor)
        res, few = queries()
        row = next(r for r in res.data if r['public_id'] == str(self.vet.public_id))
        self.assertIn('medicalrecord.close', row['permissions'])
        self.assertEqual(row['permission_overrides'], {'granted': [], 'revoked': []})
        for n in range(4):
            User.objects.create_user(username=f'pm_more{n}', password='x', organization=self.org, role='VET')
        _, many = queries()
        self.assertEqual(few, many)

    def test_catalog_is_for_staff_managers(self):
        res = self.client.get('/api/staff/permission-catalog/')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual([a['key'] for a in res.data['areas']], ['clinical', 'operation', 'administration'])
        self.assertEqual(set(res.data['roles']['VET']), self.defaults('VET'))
        self.assertEqual(res.data['signing_permission'], 'prescription.create')
        client = APIClient()
        client.force_authenticate(self.vet)
        self.assertEqual(client.get('/api/staff/permission-catalog/').status_code, status.HTTP_403_FORBIDDEN)


class InboxAssigneesTests(_Base):
    def test_assignable_users_respect_member_adjustments(self):
        from apps.agent.inbox_assignment import assignable_users
        self.assertIn(self.assistant, assignable_users(self.org))
        self.assertNotIn(self.vet, assignable_users(self.org))
        self.patch(self.assistant, {'permissions': sorted(self.defaults('ASSISTANT') - {'agentinbox.send'})})
        self.patch(self.vet, {'permissions': sorted(self.defaults('VET') | {'agentinbox.send'})})
        users = list(assignable_users(self.org))
        self.assertNotIn(self.assistant, users)
        self.assertIn(self.vet, users)


class PreconditionTests(_Base):
    def test_changing_permissions_requires_the_set_that_was_seen(self):
        res = self.patch(self.vet, {'first_name': 'Nueva',
                                    'permissions': sorted(self.defaults('VET') | {'billing.refund'})},
                         precondition=False)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(res.data['code'], 'precondition_required')
        self.assertFalse(UserPermissionOverride.objects.exists())
        self.assertEqual(self.fresh(self.vet).first_name, '')

    def test_a_stale_view_is_rejected_and_nothing_is_written(self):
        seen = sorted(self.defaults('VET'))
        self.patch(self.vet, {'permissions': sorted(self.defaults('VET') | {'billing.refund'})})
        res = self.patch(self.vet, {'first_name': 'Nueva', 'expected_permissions': seen,
                                    'permissions': sorted(self.defaults('VET') - {'appointment.list'})})
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.content)
        self.assertEqual(res.data['code'], 'permissions_changed')
        self.assertIn('billing.refund', res.data['current'])
        member = self.fresh(self.vet)
        self.assertEqual(member.first_name, '')
        self.assertTrue(user_has_permission(member, 'billing.refund'))
        self.assertTrue(user_has_permission(self.fresh(self.vet), 'appointment.list'))


@FAST
class ConcurrentPermissionEditsTests(TransactionTestCase):
    """Interleaving forzado: el primer ADMIN se detiene DENTRO de su transacción,
    con la fila de la persona bloqueada. El segundo, que abrió la ficha antes,
    espera ese bloqueo (``pg_stat_activity``) y al seguir ve el cambio: 409."""

    def setUp(self):
        set_current_user(None)
        cache.clear()
        self.org = Organization.objects.create(name='Clinica Permisos Carrera', timezone='UTC')
        self.admin = User.objects.create(username='pmc_admin', organization=self.org, role='ADMIN')
        self.other_admin = User.objects.create(username='pmc_admin2', organization=self.org, role='ADMIN')
        self.vet = User.objects.create(username='pmc_vet', organization=self.org, role='VET',
                                       license_number='1234567', attends_patients=True)

    def _wait_for_a_lock_waiter(self, timeout=10):
        deadline = time.monotonic() + timeout
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
                if cursor.fetchone()[0] >= 1:
                    return True
                time.sleep(0.05)
        return False

    def test_the_second_admin_waits_and_sees_the_first_change(self):
        base = role_default_codes(self.org.pk, 'VET')
        seen = sorted(base)
        entered, release = threading.Event(), threading.Event()
        real_write = member_permissions.write_overrides

        def held_write(**kwargs):
            entered.set()
            release.wait(timeout=20)
            return real_write(**kwargs)

        outcomes = {}

        def run(key, actor_pk, desired):
            try:
                update_staff_member(
                    admin=User.objects.get(pk=actor_pk), target_user=User.objects.get(pk=self.vet.pk),
                    permissions=desired, expected_permissions=seen)
                outcomes[key] = 'ok'
            except Exception as exc:
                outcomes[key] = exc
            finally:
                connection.close()

        with mock.patch.object(member_permissions, 'write_overrides', held_write):
            first = threading.Thread(
                target=run, args=('first', self.admin.pk, sorted(base | {'billing.refund'})))
            second = threading.Thread(
                target=run, args=('second', self.other_admin.pk, sorted(base - {'appointment.list'})))
            try:
                first.start()
                self.assertTrue(entered.wait(timeout=10), 'el primero no llegó a escribir')
                second.start()
                waited = self._wait_for_a_lock_waiter()
                still_running = second.is_alive()
            finally:
                release.set()
                first.join(timeout=30)
                second.join(timeout=30)
        self.assertTrue(waited, 'el segundo no esperó ningún bloqueo')
        self.assertTrue(still_running, 'el segundo terminó sin esperar al primero')
        self.assertEqual(outcomes['first'], 'ok')
        self.assertIsInstance(outcomes['second'], PermissionsChanged)
        self.assertTrue(user_has_permission(User.objects.get(pk=self.vet.pk), 'billing.refund'))
        self.assertTrue(user_has_permission(User.objects.get(pk=self.vet.pk), 'appointment.list'))


class ProfileSecurityTests(_Base):
    def test_the_profile_says_whether_mfa_is_on_and_nothing_else(self):
        from django.utils import timezone
        from apps.users.models import UserMFA
        other = User.objects.create_user(username='pm_admin3', password='x',
                                         organization=self.org, role='ADMIN')
        res = self.client.get(f'/api/staff/{other.public_id}/profile/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIs(res.data['mfa_enabled'], False)
        UserMFA.objects.create(user=other, secret_encrypted='cifrado', enabled_at=timezone.now())
        res = self.client.get(f'/api/staff/{other.public_id}/profile/')
        self.assertIs(res.data['mfa_enabled'], True)
        self.assertNotIn('secret', str(res.data).lower())
