"""ADR p66: cambio de rol de un integrante (``POST /api/staff/<uuid>/role/``).

- Permiso ``staff.change_role`` (sensible, solo ADMIN).
- ``User.role`` y el ``UserRole`` de sistema cambian juntos; los permisos nuevos
  aplican en la siguiente petición y las sesiones NO se cierran (decisión del PO).
- La función clínica sigue al rol; quien atiende necesita cédula.
- INV-J: el último ADMIN activo no pierde el rol, tampoco en carreras (bloqueo
  ordenado, con interleaving forzado como en ``test_staff_last_admin``).
- Mismo alcance que el resto de Equipo: 404 fuera de la clínica, a sí mismo 400,
  cuentas semilla de la demo 403. Repetir el mismo rol no escribe nada.
"""
import threading
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient, APITestCase

from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.core.permissions import user_has_permission
from apps.organizations.models import Organization
from apps.users import services
from apps.users.models import StaffAccessEvent
from apps.users.services import LastActiveAdmin, change_staff_role

User = get_user_model()

FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


def _user(org, username, role, **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='x',
        organization=org, role=role, first_name='Ana', **extra)


def _system_roles(user):
    return set(UserRole.objects.filter(user=user, role__is_system_role=True)
               .values_list('role__name', flat=True))


@FAST_HASHER
class RoleChangeTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica Rol', timezone='UTC')
        self.admin = _user(self.org, 'rc_admin', 'ADMIN')
        self.assistant = _user(self.org, 'rc_asst', 'ASSISTANT')
        self.vet = _user(self.org, 'rc_vet', 'VET', license_number='1234567', attends_patients=True)
        self.client.force_authenticate(self.admin)

    def change(self, member, role, **extra):
        return self.client.post(f'/api/staff/{member.public_id}/role/', {'role': role, **extra},
                                format='json')

    def fresh(self, user):
        return User.objects.get(pk=user.pk)  # sin la caché de permisos de la instancia

    def test_promote_assistant_to_admin(self):
        res = self.change(self.assistant, 'ADMIN')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.data['role'], 'ADMIN')
        promoted = self.fresh(self.assistant)
        self.assertEqual(promoted.role, 'ADMIN')
        self.assertEqual(_system_roles(promoted), {'ADMIN'})
        self.assertTrue(user_has_permission(promoted, 'staff.create'))
        event = StaffAccessEvent.objects.get(member=promoted, kind='role_changed')
        self.assertEqual(event.changes, {'role': {'from': 'ASSISTANT', 'to': 'ADMIN'}})
        self.assertEqual(event.actor, self.admin)

    def test_demoting_a_vet_removes_clinical_permissions_without_closing_sessions(self):
        version = self.vet.session_version
        res = self.change(self.vet, 'ASSISTANT')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        demoted = self.fresh(self.vet)
        self.assertEqual((demoted.role, demoted.attends_patients), ('ASSISTANT', False))
        self.assertEqual(_system_roles(demoted), {'ASSISTANT'})
        self.assertFalse(user_has_permission(demoted, 'medicalrecord.create'))
        self.assertEqual(demoted.session_version, version)  # PO: no se cierran sesiones
        event = StaffAccessEvent.objects.get(member=demoted, kind='role_changed')
        self.assertEqual(event.changes['attends_patients'], {'from': True, 'to': False})

    def test_the_new_role_applies_on_the_next_request_with_the_same_token(self):
        from django.core.cache import cache, caches
        cache.clear()
        caches['throttle_login'].clear()
        login = APIClient().post('/api/token/', {'username': 'rc_asst@example.com', 'password': 'x'},
                                 format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.content)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(client.post('/api/staff/create/', {}, format='json').status_code,
                         status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.change(self.assistant, 'ADMIN').status_code, status.HTTP_200_OK)
        # Mismo access token, siguiente petición: ya tiene staff.create (falla la
        # validación del cuerpo vacío, no el permiso). La sesión sigue viva.
        self.assertEqual(client.post('/api/staff/create/', {}, format='json').status_code,
                         status.HTTP_400_BAD_REQUEST)

    def test_becoming_a_vet_requires_a_license(self):
        res = self.change(self.assistant, 'VET')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn('license_number', res.data['errors'])
        self.assertEqual(self.fresh(self.assistant).role, 'ASSISTANT')
        User.objects.filter(pk=self.assistant.pk).update(license_number='7654321')
        res = self.change(self.assistant, 'VET')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertTrue(self.fresh(self.assistant).attends_patients)

    def test_vet_promoted_to_admin_keeps_attending_unless_told_otherwise(self):
        res = self.change(self.vet, 'ADMIN')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertTrue(res.data['attends_patients'])
        other = _user(self.org, 'rc_vet2', 'VET', license_number='2222222', attends_patients=True)
        res = self.change(other, 'ADMIN', attends_patients=False)
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(res.data['attends_patients'])

    def test_attends_patients_cannot_contradict_a_non_admin_role(self):
        res = self.change(self.vet, 'ASSISTANT', attends_patients=True)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(self.fresh(self.vet).role, 'VET')

    def test_the_last_admin_keeps_the_role(self):
        other_admin = _user(self.org, 'rc_admin2', 'ADMIN')
        client = APIClient()
        client.force_authenticate(other_admin)
        res = client.post(f'/api/staff/{self.admin.public_id}/role/', {'role': 'ASSISTANT'},
                          format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        # other_admin es ahora el único ADMIN activo. Ni alguien con el permiso
        # concedido en la base puede quitárselo (INV-J no depende del rol).
        granted = _user(self.org, 'rc_granted', 'VET', license_number='3333333')
        role = Role.objects.create(name='CAMBIA_ROLES', organization=self.org)
        role.permissions.set([Permission.objects.get_or_create(code=c)[0]
                              for c in ('staff.list', 'staff.change_role')])
        UserRole.objects.filter(user=granted).delete()
        UserRole.objects.create(user=granted, role=role)
        client.force_authenticate(granted)
        res = client.post(f'/api/staff/{other_admin.public_id}/role/', {'role': 'ASSISTANT'},
                          format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.content)
        self.assertEqual(res.data['code'], 'last_active_admin')
        self.assertEqual(self.fresh(other_admin).role, 'ADMIN')
        self.assertFalse(StaffAccessEvent.objects.filter(member=other_admin).exists())

    def test_cannot_change_own_role(self):
        res = self.change(self.admin, 'ASSISTANT')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(self.fresh(self.admin).role, 'ADMIN')

    def test_same_role_writes_nothing(self):
        res = self.change(self.assistant, 'ASSISTANT')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertFalse(StaffAccessEvent.objects.filter(member=self.assistant).exists())

    def test_custom_roles_are_kept(self):
        custom = Role.objects.create(name='EXTRA', organization=self.org)
        custom.permissions.set([Permission.objects.get_or_create(code='inventory.view')[0]])
        UserRole.objects.create(user=self.assistant, role=custom)
        self.assertEqual(self.change(self.assistant, 'ADMIN').status_code, status.HTTP_200_OK)
        self.assertTrue(UserRole.objects.filter(user=self.assistant, role=custom).exists())

    def test_scope_and_permissions(self):
        other_org = Organization.objects.create(name='Clinica Rol B', timezone='UTC')
        foreign = _user(other_org, 'rc_foreign', 'ASSISTANT')
        self.assertEqual(self.change(foreign, 'ADMIN').status_code, status.HTTP_404_NOT_FOUND)
        User.objects.filter(pk=self.assistant.pk).update(is_active=False)
        self.assertEqual(self.change(self.assistant, 'ADMIN').status_code, status.HTTP_404_NOT_FOUND)
        for caller in (self.vet,):
            client = APIClient()
            client.force_authenticate(caller)
            res = client.post(f'/api/staff/{self.admin.public_id}/role/', {'role': 'VET'},
                              format='json')
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertEqual(self.fresh(foreign).role, 'ASSISTANT')

    def test_invalid_role_is_rejected(self):
        for role in ('ADMIN_SAAS', 'AGENT', 'OWNER'):
            with self.subTest(role):
                self.assertEqual(self.change(self.assistant, role).status_code,
                                 status.HTTP_400_BAD_REQUEST)

    def test_catalog_grants_change_role_only_to_admin(self):
        from apps.core.permissions_codes import PERMISSIONS, SENSITIVE_CODES
        self.assertIn('staff.change_role', SENSITIVE_CODES)
        self.assertIn('staff.change_role', PERMISSIONS['ADMIN'])
        for role in ('VET', 'ASSISTANT', 'AGENT'):
            self.assertNotIn('staff.change_role', PERMISSIONS[role])


@FAST_HASHER
class DemoSeedRoleTests(APITestCase):
    def test_demo_seed_accounts_are_protected(self):
        from apps.core.demo_reset import DEMO_VET_USERNAME
        org = Organization.objects.create(name='Demo Rol', timezone='UTC', is_demo=True)
        admin = _user(org, 'demo_rol_admin', 'ADMIN')
        seed = User.objects.create_user(username=DEMO_VET_USERNAME, password='x', organization=org,
                                        role='VET', license_number='1234567')
        self.client.force_authenticate(admin)
        res = self.client.post(f'/api/staff/{seed.public_id}/role/', {'role': 'ASSISTANT'},
                               format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.content)
        self.assertEqual(User.objects.get(pk=seed.pk).role, 'VET')


class RoleChangeLockWaitTests(TransactionTestCase):
    """INV-J con interleaving forzado (ver test_staff_last_admin).

    El primer cambio se detiene DENTRO de su transacción, ya con las filas
    bloqueadas y el rol guardado. El segundo arranca, la prueba comprueba en
    ``pg_stat_activity`` que espera un bloqueo, y al soltar el primero vuelve a
    evaluar las filas confirmadas y rechaza.
    """

    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica Rol Carrera', timezone='UTC')

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

    def interleave(self, first, second):
        entered, release = threading.Event(), threading.Event()
        claimed = threading.Lock()
        real_swap = services._swap_system_role

        def held_swap(user):
            if claimed.acquire(blocking=False):
                entered.set()
                release.wait(timeout=20)
            return real_swap(user)

        outcomes = {}

        def worker(label, call):
            try:
                call()
                outcomes[label] = 'ok'
            except Exception as exc:  # se clasifica en la prueba
                outcomes[label] = exc
            finally:
                connection.close()

        with mock.patch.object(services, '_swap_system_role', held_swap):
            t1 = threading.Thread(target=worker, args=('first', first))
            t2 = threading.Thread(target=worker, args=('second', second))
            try:
                t1.start()
                self.assertTrue(entered.wait(timeout=10), 'el primero no llegó al bloqueo')
                t2.start()
                waited = self._wait_for_a_lock_waiter()
                second_still_running = t2.is_alive()
            finally:
                release.set()
                t1.join(timeout=30)
                t2.join(timeout=30)
        self.assertTrue(waited, 'el segundo no esperó ningún bloqueo')
        self.assertTrue(second_still_running, 'el segundo terminó sin esperar al primero')
        return outcomes

    def test_two_admins_demoting_each_other_leave_one_admin(self):
        a = User.objects.create(username='rl_a', organization=self.org, role='ADMIN')
        b = User.objects.create(username='rl_b', organization=self.org, role='ADMIN')
        outcomes = self.interleave(
            lambda: change_staff_role(admin=User.objects.get(pk=a.pk),
                                      target_user=User.objects.get(pk=b.pk), role='ASSISTANT'),
            lambda: change_staff_role(admin=User.objects.get(pk=b.pk),
                                      target_user=User.objects.get(pk=a.pk), role='ASSISTANT'),
        )
        self.assertEqual(outcomes['first'], 'ok')
        # B ya no es ADMIN: pierde el permiso o, si lo conservara, sería el último.
        self.assertIsInstance(outcomes['second'], (PermissionDenied, LastActiveAdmin))
        self.assertEqual(
            list(User.objects.filter(organization=self.org, role='ADMIN', is_active=True)
                 .values_list('pk', flat=True)),
            [a.pk],
        )

    def test_demoting_an_admin_while_the_other_is_deactivated(self):
        a = User.objects.create(username='rl_a2', organization=self.org, role='ADMIN')
        b = User.objects.create(username='rl_b2', organization=self.org, role='ADMIN')
        c = User.objects.create(username='rl_c2', organization=self.org, role='ADMIN')
        # A quita el rol a B (se detiene con el bloqueo tomado) mientras C desactiva
        # a A: al soltar, C ve a B ya no ADMIN y a sí mismo como único otro ADMIN.
        outcomes = self.interleave(
            lambda: change_staff_role(admin=User.objects.get(pk=a.pk),
                                      target_user=User.objects.get(pk=b.pk), role='ASSISTANT'),
            lambda: services.deactivate_staff(admin=User.objects.get(pk=c.pk),
                                              target_user=User.objects.get(pk=a.pk)),
        )
        self.assertEqual(outcomes['first'], 'ok')
        self.assertGreaterEqual(
            User.objects.filter(organization=self.org, role='ADMIN', is_active=True).count(), 1)
