"""A2 (plan Equipo, F3): reactivar a un integrante desactivado.

Misma cuenta (PK, public_id, rol, UserRole, relaciones), contraseña temporal de
24 h con cambio obligatorio, todas las sesiones anteriores invalidadas (ADR p65)
y respuesta con ``no-store``. Atomicidad: la contraseña temporal solo sale
después del commit.
"""
import ast
import threading
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.medical_records.models import MedicalRecord
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.services import (
    AlreadyActive,
    deactivate_staff,
    reactivate_staff,
)

User = get_user_model()

PASSWORD = 'OldPass1234!'
NEW_PASSWORD = 'BrandNewPass1234!'
FAST_HASHER = override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
BACKEND = Path(__file__).resolve().parents[3]


def _admin(org, username):
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password=PASSWORD,
        organization=org, role='ADMIN', first_name='Ada',
    )
    role, _ = Role.objects.get_or_create(
        name='ADMIN', organization=org, defaults={'is_system_role': True},
    )
    role.permissions.set([Permission.objects.get_or_create(code='*.*')[0]])
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _reactivate_url(user):
    return f'/api/staff/{user.public_id}/reactivate/'


@FAST_HASHER
class _Fixtures(APITestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica R', timezone='UTC')
        self.admin = _admin(self.org, 'ra_admin')
        self.vet = User.objects.create_user(
            username='ra_vet', email='ra_vet@example.com', password=PASSWORD,
            organization=self.org, role='VET', first_name='Eva', license_number='1234567',
        )
        self.client.force_authenticate(user=self.admin)

    def deactivate(self, user):
        res = self.client.delete(f'/api/staff/{user.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def reactivate(self, user):
        return self.client.post(_reactivate_url(user))

    def login(self, password=PASSWORD, identifier='ra_vet'):
        return APIClient().post(
            '/api/token/', {'username': identifier, 'password': password}, format='json',
        )

    @staticmethod
    def me(access):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return client.get('/api/me/')


class ReactivateContractTests(_Fixtures):
    def test_reactivates_the_same_account(self):
        role_ids = set(UserRole.objects.filter(user=self.vet).values_list('role_id', flat=True))
        pk, public_id = self.vet.pk, self.vet.public_id
        self.deactivate(self.vet)

        res = self.reactivate(self.vet)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res['Cache-Control'], 'no-store')
        for key in ('temp_password', 'expires_in_seconds', 'must_change_on_first_login',
                    'request_id', 'duration_ms', 'member'):
            self.assertIn(key, res.data)
        self.assertEqual(res.data['expires_in_seconds'], 24 * 3600)
        self.assertEqual(res.data['member']['public_id'], str(public_id))
        self.assertTrue(res.data['member']['is_active'])

        self.vet.refresh_from_db()
        self.assertEqual((self.vet.pk, self.vet.public_id, self.vet.role), (pk, public_id, 'VET'))
        self.assertTrue(self.vet.is_active)
        self.assertTrue(self.vet.password_must_change)
        self.assertIsNotNone(self.vet.password_temp_issued_at)
        self.assertEqual(
            set(UserRole.objects.filter(user=self.vet).values_list('role_id', flat=True)), role_ids,
        )

    def test_reset_response_is_no_store_too(self):
        res = self.client.post(f'/api/staff/{self.vet.public_id}/reset-password/')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res['Cache-Control'], 'no-store')

    def test_blocking_scenario_exactly(self):
        """Login (T) → desactivar → reactivar en <15 min → temporal → cambio."""
        token_t = self.login().data['access']
        self.deactivate(self.vet)
        self.assertEqual(self.me(token_t).status_code, status.HTTP_401_UNAUTHORIZED)

        temp = self.reactivate(self.vet).data['temp_password']
        res = self.me(token_t)
        self.assertEqual((res.status_code, res.data['code']), (401, 'session_revoked'))

        temp_login = self.login(password=temp)
        self.assertEqual(temp_login.status_code, status.HTTP_200_OK, temp_login.data)
        self.assertTrue(temp_login.data.get('must_change_password'))
        me = self.me(temp_login.data['access'])
        self.assertTrue(me.data['must_change_password'])

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {temp_login.data['access']}")
        changed = client.post('/api/users/change-password/', {
            'current_password': temp, 'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        self.assertEqual(changed.status_code, status.HTTP_200_OK, changed.data)

        res = self.me(token_t)
        self.assertEqual((res.status_code, res.data['code']), (401, 'session_revoked'))
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.password_must_change)
        self.assertFalse(self.me(changed.data['access']).data['must_change_password'])

    def test_sessions_left_alive_by_an_out_of_band_deactivation_are_revoked(self):
        first = self.login().data
        rotated = APIClient().post(
            '/api/token/refresh/', {'refresh': first['refresh']}, format='json',
        ).data
        User.objects.filter(pk=self.vet.pk).update(is_active=False)  # sin el servicio

        self.assertEqual(self.reactivate(self.vet).status_code, status.HTTP_201_CREATED)
        for refresh in (first['refresh'], rotated['refresh']):
            res = APIClient().post('/api/token/refresh/', {'refresh': refresh}, format='json')
            self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.me(first['access']).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.me(rotated['access']).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_old_password_stops_working(self):
        self.deactivate(self.vet)
        self.reactivate(self.vet)
        self.assertEqual(self.login().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_temporary_password(self):
        self.deactivate(self.vet)
        temp = self.reactivate(self.vet).data['temp_password']
        User.objects.filter(pk=self.vet.pk).update(
            password_temp_issued_at=timezone.now() - timedelta(hours=25),
        )
        res = self.login(password=temp)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['code'], 'temp_password_expired')

    def test_temp_password_is_never_logged_and_event_waits_for_commit(self):
        self.deactivate(self.vet)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with mock.patch('apps.users.services._log_staff_reactivated') as early:
                res = self.reactivate(self.vet)
        early.assert_not_called()  # nada se registra antes del commit
        self.assertEqual(len(callbacks), 1)
        with self.assertLogs('users.events', level='INFO') as logs:
            callbacks[0]()
        record = next(r for r in logs.records if r.getMessage() == 'STAFF_REACTIVATED')
        self.assertEqual(record.target_user_id, self.vet.pk)
        for value in record.__dict__.values():
            self.assertNotIn(res.data['temp_password'], str(value))

    def test_relations_still_point_to_the_same_user(self):
        owner = Owner.objects.create(name='O', phone='5512345678', organization=self.org)
        pet = Pet.objects.create(name='P', species='dog', owner=owner, organization=self.org)
        record = MedicalRecord.objects.create(
            pet=pet, veterinarian=self.vet, organization=self.org, diagnosis='d', treatment='t',
        )
        self.deactivate(self.vet)
        self.reactivate(self.vet)
        record.refresh_from_db()
        self.assertEqual(record.veterinarian_id, self.vet.pk)

    def test_vet_without_license_can_be_reactivated(self):
        User.objects.filter(pk=self.vet.pk).update(license_number='')
        self.deactivate(self.vet)
        self.assertEqual(self.reactivate(self.vet).status_code, status.HTTP_201_CREATED)


class ReactivateRejectionsTests(_Fixtures):
    def test_active_member_is_409(self):
        res = self.reactivate(self.vet)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], 'already_active')
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.password_must_change)

    def test_unreachable_targets_are_404(self):
        other_org = Organization.objects.create(name='Clinica R2', timezone='UTC')
        foreign = User.objects.create_user(
            username='ra_foreign', organization=other_org, role='VET', is_active=False,
        )
        agent = User.objects.create_user(
            username='ra_agent', organization=self.org, role='AGENT', is_active=False,
        )
        User.objects.filter(pk=agent.pk).update(is_service_account=True)
        saas = User.objects.create_user(
            username='ra_saas', organization=self.org, role='ADMIN_SAAS', is_active=False,
        )
        for target in (foreign, agent, saas):
            with self.subTest(target=target.username):
                res = self.reactivate(target)
                self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND, res.data)
                target.refresh_from_db()
                self.assertFalse(target.is_active)

    def test_roles_without_permission_get_403(self):
        self.deactivate(self.vet)
        for role in ('VET', 'ASSISTANT'):
            with self.subTest(role=role):
                actor = User.objects.create_user(
                    username=f'ra_{role}', organization=self.org, role=role,
                    license_number='1234567' if role == 'VET' else '',
                )
                client = APIClient()
                client.force_authenticate(user=actor)
                res = client.post(_reactivate_url(self.vet))
                self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.is_active)

    def test_throttle_applies(self):
        for _ in range(10):
            self.assertEqual(self.reactivate(self.vet).status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self.reactivate(self.vet).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_durable_rejects_being_called_inside_a_transaction(self):
        self.deactivate(self.vet)
        target = User.objects.get(pk=self.vet.pk)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                reactivate_staff(admin=self.admin, target_user=target)
        self.vet.refresh_from_db()
        self.assertFalse(self.vet.is_active)


class SingleCallerGateTests(APITestCase):
    def test_reactivate_staff_has_a_single_production_caller(self):
        callers = []
        for root in (BACKEND / 'apps', BACKEND / 'config'):
            for path in root.rglob('*.py'):
                parts = set(path.relative_to(BACKEND).parts)
                if parts & {'tests', 'migrations', '__pycache__'} or path.name.startswith('test_'):
                    continue
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and getattr(node.func, 'id', getattr(node.func, 'attr', None)) == 'reactivate_staff'
                    ):
                        callers.append(path.relative_to(BACKEND).as_posix())
        self.assertEqual(
            callers, ['apps/users/views.py'],
            'reactivate_staff es durable: un llamador nuevo debe invocarlo fuera '
            'de cualquier transacción (plan Equipo, II.3).',
        )


@FAST_HASHER
class ReactivateAtomicityTests(TransactionTestCase):
    def setUp(self):
        set_current_user(None)
        cache.clear()
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clinica RT', timezone='UTC')
        self.admin = _admin(self.org, 'rt_admin')
        self.vet = User.objects.create_user(
            username='rt_vet', email='rt_vet@example.com', password=PASSWORD,
            organization=self.org, role='VET', license_number='1234567',
        )
        deactivate_staff(admin=self.admin, target_user=self.vet)
        self.client = APIClient(raise_request_exception=False)
        self.client.force_authenticate(user=self.admin)

    def test_failure_before_commit_leaves_everything_untouched(self):
        version = User.objects.get(pk=self.vet.pk).session_version
        blacklisted = BlacklistedToken.objects.count()
        with mock.patch(
            'apps.users.services._revoke_all_sessions', side_effect=RuntimeError('fallo forzado'),
        ), mock.patch('apps.users.services._log_staff_reactivated') as log:
            res = self.client.post(_reactivate_url(self.vet))
        self.assertEqual(res.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertNotIn('temp_password', res.json())
        log.assert_not_called()
        vet = User.objects.get(pk=self.vet.pk)
        self.assertFalse(vet.is_active)
        self.assertTrue(vet.check_password(PASSWORD))
        self.assertEqual(vet.session_version, version)
        self.assertEqual(BlacklistedToken.objects.count(), blacklisted)

    def test_failing_event_does_not_turn_a_committed_reactivation_into_an_error(self):
        with mock.patch(
            'apps.users.services._log_staff_reactivated', side_effect=RuntimeError('log caído'),
        ):
            res = self.client.post(_reactivate_url(self.vet))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertIn('temp_password', res.json())
        self.assertTrue(User.objects.get(pk=self.vet.pk).is_active)


class ReactivateConcurrencyTests(TransactionTestCase):
    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica RC', timezone='UTC')

    def _run(self, *calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def worker(index, call):
            try:
                barrier.wait(timeout=10)
                outcomes[index] = call()
            except Exception as exc:
                outcomes[index] = exc
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return outcomes

    def test_two_simultaneous_reactivations_issue_one_password(self):
        a = User.objects.create(username='rc_a', organization=self.org, role='ADMIN')
        b = User.objects.create(username='rc_b', organization=self.org, role='ADMIN')
        vet = User.objects.create(username='rc_vet', organization=self.org, role='VET',
                                  is_active=False)
        outcomes = self._run(
            lambda: reactivate_staff(admin=User.objects.get(pk=a.pk), target_user=User.objects.get(pk=vet.pk)),
            lambda: reactivate_staff(admin=User.objects.get(pk=b.pk), target_user=User.objects.get(pk=vet.pk)),
        )
        successes = [o for o in outcomes if not isinstance(o, Exception)]
        self.assertEqual(len(successes), 1, outcomes)
        self.assertEqual(sum(isinstance(o, AlreadyActive) for o in outcomes), 1, outcomes)
        vet.refresh_from_db()
        self.assertTrue(vet.check_password(successes[0].temp_password))

    def test_deactivating_an_admin_while_another_is_reactivated(self):
        a = User.objects.create(username='rc_a2', organization=self.org, role='ADMIN')
        b = User.objects.create(username='rc_b2', organization=self.org, role='ADMIN')
        c = User.objects.create(username='rc_c2', organization=self.org, role='ADMIN',
                                is_active=False)
        self._run(
            lambda: deactivate_staff(admin=User.objects.get(pk=a.pk), target_user=User.objects.get(pk=b.pk)),
            lambda: reactivate_staff(admin=User.objects.get(pk=b.pk), target_user=User.objects.get(pk=c.pk)),
        )
        active_admins = User.objects.filter(
            organization=self.org, role='ADMIN', is_active=True, is_service_account=False,
        ).count()
        self.assertGreaterEqual(active_admins, 1)
