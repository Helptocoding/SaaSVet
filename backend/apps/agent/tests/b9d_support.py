"""Explicit synthetic release evidence. Never import from application runtime."""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from django.db import connection
from apps.agent import beta_release as beta
from apps.agent.capabilities import EFFECTS, OPERATIONS, READ_PUBLIC, READ_PERSONAL

TEST_ENVIRONMENT = 'TEST_EVIDENCE'
TEST_DATE = datetime(2020, 1, 1, tzinfo=timezone.utc)
CAPABILITIES = tuple(name for name, effect in EFFECTS.items()
                     if effect in (READ_PUBLIC, READ_PERSONAL)
                     or (name in OPERATIONS and OPERATIONS[name].operation_kind))


def approval(organization_id, *, capabilities=CAPABILITIES, approved_at=TEST_DATE):
    return beta.OrganizationApproval(organization_id, capabilities, approved_at, tuple(
        beta.Evidence(requirement, organization_id, 'test-authority',
                      approved_at if requirement == 'human_approval' else TEST_DATE,
                      'test-fixture:' + requirement, 'test-v1', TEST_ENVIRONMENT, 'PASS')
        for requirement in beta.OPERATIONAL_REQUIREMENTS + beta.TECHNICAL_REQUIREMENTS))


def release_for(*organization_ids, capabilities=CAPABILITIES):
    return beta.Release('test-only-release', '1' * 40, 'test-b9d-compatible', capabilities,
                        tuple(approval(org, capabilities=capabilities) for org in organization_ids))


@contextmanager
def approved_test_release(*organization_ids):
    """Fixtures for gate-open component tests, with the real evaluator/guard.

    Existing tests create organizations inside their gate context, so the data
    factory resolves those isolated fixture IDs when read. This is not a runtime
    config or enable-all command. The production evidence environment is restored.
    """
    if connection.vendor != 'postgresql' or not connection.settings_dict['NAME'].startswith('test_'):
        raise RuntimeError('Synthetic beta approval requires isolated PostgreSQL tests')

    def fixture_release():
        from apps.organizations.models import Organization
        ids = organization_ids or tuple(Organization.objects.values_list('pk', flat=True))
        return release_for(*ids)

    with patch.object(beta, 'EVIDENCE_ENVIRONMENT', TEST_ENVIRONMENT), patch.object(
            beta, 'current_release', side_effect=fixture_release):
        yield
