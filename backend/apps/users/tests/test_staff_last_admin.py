"""Invariante del último ADMIN (plan Equipo, II.3.1).

Una organización nunca queda sin al menos un ADMIN activo como consecuencia de
una operación de gestión de personal. La regla vive en ``deactivate_staff`` y no
depende del frontend ni de qué rol tenga ``staff.destroy``.

Secuenciales con ``APITestCase``; concurrentes con ``TransactionTestCase`` e
hilos sincronizados con ``threading.Barrier`` (las transacciones son reales).
"""
import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.http import Http404
from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.organizations.models import Organization
from apps.users.services import (
    ActorInactive,
    LastActiveAdmin,
    deactivate_staff,
)

User = get_user_model()


def _grant(user, org, role_name, codes):
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={'is_system_role': True},
    )
    role.permissions.set([Permission.objects.get_or_create(code=c)[0] for c in codes])
    UserRole.objects.filter(user=user).delete()
    UserRole.objects.create(user=user, role=role)


def _user(org, username, role):
    return User.objects.create(username=username, organization=org, role=role)


def _active_admins(org):
    return User.objects.filter(
        organization=org, role='ADMIN', is_active=True, is_service_account=False,
    ).count()


class LastAdminSequentialTests(APITestCase):
    def setUp(self):
        set_current_user(None)  # no heredar el usuario de auditoría de otra prueba
        self.org = Organization.objects.create(name='Clinica UA', timezone='UTC')
        self.admin = _user(self.org, 'ua_admin', 'ADMIN')
        _grant(self.admin, self.org, 'ADMIN', ['*.*'])
        self.vet = _user(self.org, 'ua_vet', 'VET')

    def test_the_only_admin_cannot_be_deactivated_even_with_a_db_grant(self):
        # Un VET con staff.destroy concedido directamente en la base.
        _grant(self.vet, self.org, 'VET', ['staff.destroy', 'staff.list'])
        client = APIClient()
        client.force_authenticate(user=self.vet)
        res = client.delete(f'/api/staff/{self.admin.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.data)
        self.assertEqual(res.data['code'], 'last_active_admin')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_an_admin_can_deactivate_another_admin(self):
        other = _user(self.org, 'ua_admin2', 'ADMIN')
        client = APIClient()
        client.force_authenticate(user=self.admin)
        res = client.delete(f'/api/staff/{other.public_id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(_active_admins(self.org), 1)

    def test_admins_of_other_clinics_do_not_count(self):
        other_org = Organization.objects.create(name='Clinica UB', timezone='UTC')
        _user(other_org, 'ub_admin', 'ADMIN')
        _grant(self.vet, self.org, 'VET', ['staff.destroy'])
        with self.assertRaises(LastActiveAdmin):
            deactivate_staff(admin=self.vet, target_user=self.admin)

    def test_service_accounts_do_not_count(self):
        agent = _user(self.org, 'ua_agent', 'ADMIN')
        User.objects.filter(pk=agent.pk).update(is_service_account=True)
        _grant(self.vet, self.org, 'VET', ['staff.destroy'])
        with self.assertRaises(LastActiveAdmin):
            deactivate_staff(admin=self.vet, target_user=self.admin)

    def test_actor_deactivated_meanwhile_is_rejected(self):
        stale_actor = User.objects.get(pk=self.admin.pk)
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        with self.assertRaises(ActorInactive):
            deactivate_staff(admin=stale_actor, target_user=self.vet)
        self.vet.refresh_from_db()
        self.assertTrue(self.vet.is_active)

    def test_actor_inactive_response_shape(self):
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        client = APIClient()
        client.force_authenticate(user=self.admin)  # instancia vieja, aún activa
        res = client.delete(f'/api/staff/{self.vet.public_id}/')
        # La vista resuelve al objetivo antes; el servicio rechaza al actor.
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)
        self.assertEqual(res.data['code'], 'actor_inactive')

    def test_target_deactivated_meanwhile_is_404(self):
        stale_target = User.objects.get(pk=self.vet.pk)
        User.objects.filter(pk=self.vet.pk).update(is_active=False)
        with self.assertRaises(Http404):
            deactivate_staff(admin=self.admin, target_user=stale_target)


class _Concurrent(TransactionTestCase):
    def setUp(self):
        # El usuario de auditoría vive en un thread-local: no heredar el de otra prueba.
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica UC', timezone='UTC')

    def run_concurrently(self, *calls):
        barrier = threading.Barrier(len(calls))
        outcomes = [None] * len(calls)

        def worker(index, call):
            try:
                barrier.wait(timeout=10)
                call()
                outcomes[index] = 'ok'
            except Exception as exc:  # se clasifica abajo
                outcomes[index] = exc
            finally:
                connection.close()

        threads = [
            threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return outcomes

    def assertOnlyExpectedRejections(self, outcomes):
        for outcome in outcomes:
            if outcome != 'ok':
                self.assertIsInstance(outcome, (ActorInactive, LastActiveAdmin, Http404))


class LastAdminConcurrencyTests(_Concurrent):
    def test_two_admins_deactivating_each_other(self):
        a = _user(self.org, 'uc_a', 'ADMIN')
        b = _user(self.org, 'uc_b', 'ADMIN')
        outcomes = self.run_concurrently(
            lambda: deactivate_staff(admin=User.objects.get(pk=a.pk), target_user=User.objects.get(pk=b.pk)),
            lambda: deactivate_staff(admin=User.objects.get(pk=b.pk), target_user=User.objects.get(pk=a.pk)),
        )
        self.assertEqual(outcomes.count('ok'), 1, outcomes)
        rejected = [o for o in outcomes if o != 'ok']
        self.assertIsInstance(rejected[0], ActorInactive)
        self.assertEqual(_active_admins(self.org), 1)

    def test_three_admins_deactivating_in_a_cross(self):
        a, b, c = (_user(self.org, f'uc_{n}', 'ADMIN') for n in ('x', 'y', 'z'))
        pairs = ((a, b), (b, c), (c, a))
        outcomes = self.run_concurrently(*[
            (lambda actor=actor, target=target: deactivate_staff(
                admin=User.objects.get(pk=actor.pk),
                target_user=User.objects.get(pk=target.pk),
            ))
            for actor, target in pairs
        ])
        self.assertOnlyExpectedRejections(outcomes)
        self.assertGreaterEqual(_active_admins(self.org), 1)

    def test_deactivating_an_admin_while_another_is_created(self):
        a = _user(self.org, 'uc_a2', 'ADMIN')
        b = _user(self.org, 'uc_b2', 'ADMIN')
        outcomes = self.run_concurrently(
            lambda: deactivate_staff(admin=User.objects.get(pk=a.pk), target_user=User.objects.get(pk=b.pk)),
            lambda: _user(self.org, 'uc_new', 'ADMIN'),
        )
        self.assertOnlyExpectedRejections(outcomes)
        self.assertGreaterEqual(_active_admins(self.org), 1)
