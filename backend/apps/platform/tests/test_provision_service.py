"""
Tests for `apps.platform.services.provision_organization`.

Service-level coverage runs *before* the view exists. The service is the
authoritative orchestration; the view is a thin HTTP shell over it.

Invariants under test:
  - Side effects: Organization + signals (OrgSettings, generic Owner/Pet,
    Roles) + User + UserRole(assigned_by=actor).
  - Atomicity: any failure inside the service rolls back EVERYTHING.
    Specifically, after a forced failure: Organization.objects.count(),
    User.objects.count() and UserRole.objects.count() must match the
    snapshot taken before the call.
  - Audit: UserRole.assigned_by is populated despite the signal-created
    row arriving without it (update_or_create backfill).
  - Race translation: IntegrityError → DRF ValidationError (HTTP 400).
  - Post-condition: a violated invariant raises RuntimeError and triggers
    rollback.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.core.models import Role, UserRole
from apps.organizations.models import Organization, OrganizationSettings
from apps.patients.models import Owner, Pet
from apps.platform.services.provision_organization import (
    ProvisionResult,
    provision_organization,
)


User = get_user_model()


VALID_PAYLOAD = {
    'name': 'Clinica Test',
    'timezone': 'America/Mexico_City',
    'tax_rate': Decimal('0.1600'),
    'admin_username': 'newadmin',
    'admin_email': 'newadmin@test.com',
    'admin_password': 'SuperPass1234!',  # 14 chars
    'admin_first_name': 'Laura',
    'admin_last_name': 'García',
}


class ProvisionOrganizationServiceTests(TestCase):
    """Happy path + invariants of `provision_organization`."""

    def setUp(self):
        # Platform operator (ADMIN_SAAS) — actor for every call.
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.actor = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )

    # --- Happy path ----------------------------------------------------

    def test_creates_org_admin_userrole_atomically(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        self.assertIsInstance(result, ProvisionResult)
        self.assertEqual(result.organization.name, 'Clinica Test')
        self.assertEqual(result.admin.username, 'newadmin')
        self.assertEqual(result.admin.role, 'ADMIN')
        self.assertEqual(result.admin.organization_id, result.organization.pk)
        self.assertFalse(result.admin.is_staff)
        self.assertFalse(result.admin.is_superuser)
        self.assertTrue(result.admin.is_active)
        self.assertIsNotNone(result.organization.public_id)
        self.assertIsNotNone(result.admin.public_id)

    def test_signal_creates_org_settings(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        self.assertTrue(
            OrganizationSettings.objects.filter(organization=result.organization).exists()
        )

    def test_signal_creates_generic_owner_pet(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        self.assertTrue(
            Owner.objects.filter(
                organization=result.organization,
                is_generic=True,
            ).exists()
        )
        self.assertTrue(
            Pet.objects.filter(
                organization=result.organization,
                is_generic=True,
            ).exists()
        )

    def test_signal_creates_rbac_roles(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        role_names = set(
            Role.objects.filter(
                organization=result.organization,
                is_system_role=True,
            ).values_list('name', flat=True)
        )
        self.assertIn('ADMIN', role_names)
        self.assertIn('VET', role_names)
        self.assertIn('ASSISTANT', role_names)
        self.assertNotIn('ADMIN_SAAS', role_names)

    def test_userrole_assigned_with_actor_as_assigned_by(self):
        """Audit invariant — UserRole row exists and assigned_by == actor.

        The `users.signals.assign_rbac_role_on_create` signal creates the
        UserRole without `assigned_by`. The service uses update_or_create
        to backfill the audit field. Without this, audit_log queries
        cannot tell which platform operator provisioned each tenant.
        """
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        ur = UserRole.objects.get(
            user=result.admin,
            role__organization=result.organization,
            role__name='ADMIN',
        )
        self.assertEqual(ur.assigned_by_id, self.actor.pk)

    def test_duration_ms_captured(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        self.assertIsInstance(result.duration_ms, int)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_request_id_generated_when_not_provided(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
        )
        self.assertTrue(result.request_id)
        # uuid4 format: 8-4-4-4-12
        self.assertEqual(len(result.request_id), 36)

    def test_request_id_propagates_when_provided(self):
        result = provision_organization(
            actor=self.actor,
            validated_data=dict(VALID_PAYLOAD),
            request_id='custom-trace-id',
        )
        self.assertEqual(result.request_id, 'custom-trace-id')

    def test_log_event_contains_correlation_fields(self):
        with self.assertLogs('platform.events', level='INFO') as logs:
            provision_organization(
                actor=self.actor,
                validated_data=dict(VALID_PAYLOAD),
                request_id='trace-abc',
            )
        # Find the success log record (ignore noisy logs from signals).
        success = [r for r in logs.records if r.msg == 'PLATFORM_ORG_PROVISIONED']
        self.assertEqual(len(success), 1)
        record = success[0]
        self.assertEqual(record.event, 'PLATFORM_ORG_PROVISIONED')
        self.assertEqual(record.request_id, 'trace-abc')
        self.assertEqual(record.actor_id, self.actor.pk)
        self.assertEqual(record.actor_role, 'ADMIN_SAAS')
        self.assertTrue(record.org_id)
        self.assertTrue(record.org_public_id)
        self.assertTrue(record.admin_user_id)
        self.assertTrue(record.admin_user_public_id)
        self.assertIsInstance(record.duration_ms, int)


class ProvisionRollbackTests(TestCase):
    """Atomicity invariants — failures must roll back the entire transaction."""

    def setUp(self):
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.actor = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )
        # Snapshot baseline counts (the setUp itself creates rows).
        self.org_count_before = Organization.objects.count()
        self.user_count_before = User.objects.count()
        self.userrole_count_before = UserRole.objects.count()

    def _assert_no_side_effects(self):
        self.assertEqual(Organization.objects.count(), self.org_count_before)
        self.assertEqual(User.objects.count(), self.user_count_before)
        self.assertEqual(UserRole.objects.count(), self.userrole_count_before)

    def test_rollback_on_integrity_error_username_race(self):
        """Validation passed but another worker inserted same username
        between validate and create. Must translate to ValidationError
        AND leave zero side effects."""
        # Pre-existing user with the colliding username (created AFTER
        # serializer-style pre-check but BEFORE provision is called).
        op_org = self.actor.organization
        User.objects.create_user(
            username=VALID_PAYLOAD['admin_username'],
            email='preexisting@test.com',
            password='PreExistingPass1234!',
            role='VET',
            organization=op_org,
        )
        self.org_count_before = Organization.objects.count()
        self.user_count_before = User.objects.count()
        self.userrole_count_before = UserRole.objects.count()

        with self.assertRaises(ValidationError):
            provision_organization(
                actor=self.actor,
                validated_data=dict(VALID_PAYLOAD),
            )
        self._assert_no_side_effects()

    def test_rollback_on_role_does_not_exist(self):
        """If RBAC seed signal failed silently (no ADMIN role), the
        service must raise RuntimeError and roll back the freshly-created
        Organization + User."""
        with mock.patch(
            'apps.platform.services.provision_organization.Role'
        ) as mock_role:
            # Force the .filter().get() chain to raise DoesNotExist.
            mock_role.DoesNotExist = Role.DoesNotExist
            mock_role.objects.filter.return_value.get.side_effect = Role.DoesNotExist
            with self.assertRaises(RuntimeError):
                provision_organization(
                    actor=self.actor,
                    validated_data=dict(VALID_PAYLOAD),
                )
        self._assert_no_side_effects()

    def test_rollback_on_postcondition_failure(self):
        """Post-condition violation rolls back. Simulate by patching the
        final invariant check to return False."""
        # Patch the QuerySet.exists() used by the post-condition check.
        # Since the same query is reused, patch UserRole.objects to
        # return a queryset whose exists() returns False after the
        # update_or_create runs.
        real_filter = UserRole.objects.filter

        call_count = {'n': 0}

        def fake_filter(*args, **kwargs):
            call_count['n'] += 1
            qs = real_filter(*args, **kwargs)
            # The post-condition check filters with assigned_by=actor.
            # Force its .exists() to return False to trigger the failure.
            if 'assigned_by' in kwargs:
                qs.exists = lambda: False
            return qs

        with mock.patch.object(UserRole.objects, 'filter', side_effect=fake_filter):
            with self.assertRaises(RuntimeError):
                provision_organization(
                    actor=self.actor,
                    validated_data=dict(VALID_PAYLOAD),
                )
        self._assert_no_side_effects()

    def test_rollback_on_unexpected_exception(self):
        """Any unhandled exception inside the atomic block must roll back."""
        with mock.patch(
            'apps.platform.services.provision_organization.UserRole.objects.update_or_create',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(RuntimeError):
                provision_organization(
                    actor=self.actor,
                    validated_data=dict(VALID_PAYLOAD),
                )
        self._assert_no_side_effects()


class ProvisionRaceLoggingTests(TestCase):
    """Race condition path emits a structured warning before raising 400."""

    def setUp(self):
        op_org = Organization.objects.create(name='Vet Care Internal')
        self.actor = User.objects.create_superuser(
            username='platformop',
            email='ops@vetcare.internal',
            password='PlatformPass1234!',
            role='ADMIN_SAAS',
            organization=op_org,
        )

    def test_integrity_error_logs_race_event(self):
        # Pre-create colliding user to force IntegrityError on User.create.
        op_org = self.actor.organization
        User.objects.create_user(
            username=VALID_PAYLOAD['admin_username'],
            email='preexisting@test.com',
            password='PreExistingPass1234!',
            role='VET',
            organization=op_org,
        )
        with self.assertLogs('platform.events', level='WARNING') as logs:
            with self.assertRaises(ValidationError):
                provision_organization(
                    actor=self.actor,
                    validated_data=dict(VALID_PAYLOAD),
                )
        race_records = [
            r for r in logs.records if r.msg == 'PLATFORM_ORG_PROVISION_RACE'
        ]
        self.assertEqual(len(race_records), 1)
        self.assertEqual(race_records[0].actor_id, self.actor.pk)
