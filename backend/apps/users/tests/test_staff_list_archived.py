"""A2 (plan Equipo, F3): ``GET /api/staff/?archived=true`` y el permiso
``staff.reactivate`` (D1, D6)."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.core.models import Permission, Role, UserRole, set_current_user
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS, SENSITIVE_CODES
from apps.organizations.models import Organization

User = get_user_model()


def _grant(user, org, role_name, codes):
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={'is_system_role': True},
    )
    role.permissions.set([Permission.objects.get_or_create(code=c)[0] for c in codes])
    UserRole.objects.filter(user=user).delete()
    UserRole.objects.create(user=user, role=role)


class ArchivedListTests(APITestCase):
    def setUp(self):
        set_current_user(None)
        self.org = Organization.objects.create(name='Clinica L', timezone='UTC')
        self.admin = User.objects.create(username='la_admin', organization=self.org, role='ADMIN')
        _grant(self.admin, self.org, 'ADMIN', ['*.*'])
        self.active = User.objects.create(username='la_active', organization=self.org, role='VET')
        self.inactive = User.objects.create(
            username='la_inactive', organization=self.org, role='ASSISTANT', is_active=False,
        )
        agent = User.objects.create(
            username='la_agent', organization=self.org, role='AGENT', is_active=False,
        )
        User.objects.filter(pk=agent.pk).update(is_service_account=True)
        other = Organization.objects.create(name='Clinica L2', timezone='UTC')
        User.objects.create(username='la_foreign', organization=other, role='VET', is_active=False)
        self.client.force_authenticate(user=self.admin)

    def test_default_list_is_unchanged(self):
        res = self.client.get('/api/staff/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        usernames = {row['username'] for row in res.data}
        self.assertEqual(usernames, {'la_admin', 'la_active'})
        self.assertFalse(any(row['demo_protected'] for row in res.data))

    def test_archived_returns_only_inactive_humans_of_the_clinic(self):
        res = self.client.get('/api/staff/', {'archived': 'true'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([row['username'] for row in res.data], ['la_inactive'])

    def test_archived_requires_staff_reactivate(self):
        vet = User.objects.create(username='la_vet', organization=self.org, role='VET')
        _grant(vet, self.org, 'VET', ['staff.list'])
        client = APIClient()
        client.force_authenticate(user=vet)
        self.assertEqual(client.get('/api/staff/').status_code, status.HTTP_200_OK)
        res = client.get('/api/staff/', {'archived': 'true'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN, res.data)


class ReactivatePermissionCatalogTests(APITestCase):
    def test_only_admin_holds_staff_reactivate_and_it_is_sensitive(self):
        self.assertIn('staff.reactivate', PERMISSION_CODES)
        self.assertIn('staff.reactivate', SENSITIVE_CODES)
        self.assertIn('staff.reactivate', PERMISSIONS['ADMIN'])
        for role in ('VET', 'ASSISTANT', 'AGENT'):
            with self.subTest(role=role):
                self.assertNotIn('staff.reactivate', PERMISSIONS.get(role, []))

    def test_seed_permissions_grants_it_to_existing_clinics(self):
        from django.core.management import call_command

        set_current_user(None)
        org = Organization.objects.create(name='Clinica Seed', timezone='UTC')
        call_command('seed_permissions', verbosity=0)
        role = Role.objects.get(name='ADMIN', organization=org, is_system_role=True)
        self.assertTrue(role.permissions.filter(code='staff.reactivate').exists())
