"""B9 release approval, separate from implementation, identity and consent.

The immutable release is changed only by a reviewed, drained release cutover.
There is no runtime writer, environment override or administrative activation API.
References point to the authorized operational record; no document bodies here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from .capabilities import EFFECTS, OPERATIONS, READ_PUBLIC, READ_PERSONAL, WRITE_BUSINESS


OPERATIONAL_REQUIREMENTS = (
    'pilot_scope_and_rate', 'inbox_owner_and_coverage',
    'veterinary_protocol_and_corpus', 'inbox_drill',
    'privacy_policy_and_applicable_retention', 'validated_fallback',
    'identity_residual_risk', 'compatible_cutover_and_rollback', 'human_approval',
)
TECHNICAL_REQUIREMENTS = ('critical_ci', 'candidate_eval', 'profile_beta_1')
EVIDENCE_ENVIRONMENT = 'REAL_OPERATIONAL_EVIDENCE'


@dataclass(frozen=True)
class Evidence:
    requirement: str
    organization_id: int
    authority: str
    recorded_at: datetime
    reference: str
    revision: str
    environment: str = 'REAL_OPERATIONAL_EVIDENCE'
    outcome: str = 'PENDING'
    failures: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class OrganizationApproval:
    organization_id: int
    capabilities: tuple[str, ...]
    approved_at: datetime
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Release:
    revision: str
    # Exact tested code artifact, not the later documentation commit.
    candidate_commit: str
    minimum_compatible_version: str
    capabilities: tuple[str, ...]
    organizations: tuple[OrganizationApproval, ...]


# No organization has operational approval in this release. Technical completion
# of B9D cannot populate this list; B9E and external approvals remain pending.
APPROVED_RELEASE = Release('b9d-contained-v1', '', '', (), ())


def current_release():
    return APPROVED_RELEASE


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _text(value):
    return type(value) is str and bool(value.strip()) and len(value) <= 240


def _capabilities(values):
    return (type(values) is tuple and all(type(v) is str for v in values)
            and len(values) == len(set(values)) and all(
                EFFECTS.get(v) in (READ_PUBLIC, READ_PERSONAL)
                or (EFFECTS.get(v) == WRITE_BUSINESS and OPERATIONS[v].operation_kind)
                for v in values))


def evaluate(organization_id, *, release=None, now=None):
    """Read-only structural gate; human review of referenced evidence is external.

    A PASS record is scoped to this candidate/release by its containing approval.
    Code review must verify the references against the actual candidate artifacts.
    This function never runs an eval or asserts the substance of a clinical review.
    """
    release = current_release() if release is None else release
    now = datetime.now(timezone.utc) if now is None else now
    missing = []
    capabilities = ()
    approved_at = None
    required = OPERATIONAL_REQUIREMENTS + TECHNICAL_REQUIREMENTS
    if type(organization_id) is not int or organization_id <= 0 or not _aware(now):
        return MappingProxyType(dict(status='PENDING_ACTIVATION_REQUIREMENTS',
            missing=('invalid_organization',), capabilities=(), approved_at=None,
            evidence_environment=EVIDENCE_ENVIRONMENT, release_revision='unknown'))
    if (type(release) is not Release or not _text(release.revision)
            or not _capabilities(release.capabilities)
            or type(release.organizations) is not tuple
            or any(type(g) is not OrganizationApproval or type(g.organization_id) is not int
                   or g.organization_id <= 0 for g in release.organizations)
            or len({g.organization_id for g in release.organizations}) != len(release.organizations)):
        return MappingProxyType(dict(status='PENDING_ACTIVATION_REQUIREMENTS',
            missing=('invalid_release',), capabilities=(), approved_at=None,
            evidence_environment=EVIDENCE_ENVIRONMENT, release_revision='unknown'))
    if (type(release.candidate_commit) is not str or len(release.candidate_commit) != 40
            or any(c not in '0123456789abcdef' for c in release.candidate_commit)
            or not _text(release.minimum_compatible_version)):
        missing.append('candidate_artifact')
    grant = next((g for g in release.organizations if g.organization_id == organization_id), None)
    if grant is None:
        missing.extend(('organization_not_approved', *required))
    elif (not _capabilities(grant.capabilities) or not grant.capabilities
          or not set(grant.capabilities) <= set(release.capabilities)
          or not _aware(grant.approved_at) or grant.approved_at > now
          or type(grant.evidence) is not tuple):
        missing.append('invalid_organization_approval')
    else:
        approved_at = grant.approved_at
        records = {}
        for evidence in grant.evidence:
            if (type(evidence) is not Evidence or type(evidence.requirement) is not str or evidence.requirement not in required
                    or evidence.requirement in records):
                missing.append('invalid_evidence')
                continue
            records[evidence.requirement] = evidence
        for requirement in required:
            e = records.get(requirement)
            if (e is None or type(e.organization_id) is not int or e.organization_id != organization_id
                    or not all(_text(v) for v in (e.authority, e.reference, e.revision))
                    or not _aware(e.recorded_at) or e.recorded_at > grant.approved_at
                    or (requirement == 'human_approval' and e.recorded_at != grant.approved_at)
                    or e.environment != EVIDENCE_ENVIRONMENT or e.outcome != 'PASS'
                    or type(e.failures) is not int or e.failures != 0
                    or type(e.skipped) is not int or e.skipped != 0):
                missing.append(requirement)
        if not missing:
            capabilities = grant.capabilities
    return MappingProxyType(dict(status='READY' if not missing else 'PENDING_ACTIVATION_REQUIREMENTS',
        missing=tuple(dict.fromkeys(missing)), capabilities=capabilities, approved_at=approved_at,
        evidence_environment=EVIDENCE_ENVIRONMENT, release_revision=release.revision))


def write_gate(operation):
    """Called inside B8A, after reconciliation and before any new domain effect."""
    snapshot = evaluate(operation.organization_id)
    if snapshot['status'] != 'READY':
        return 'beta_requirements_pending'
    capability = next((name for name, spec in OPERATIONS.items()
                       if spec.operation_kind == operation.operation_kind), None)
    if capability not in snapshot['capabilities']:
        return 'beta_capability_not_approved'
    # Reapproval never revives an operation prepared under a withdrawn release.
    # This uses the existing immutable creation timestamp, not a new revision.
    if not _aware(operation.created_at) or operation.created_at < snapshot['approved_at']:
        return 'beta_operation_predates_approval'
    return ''


def inspect_organization(organization_id):
    """Snapshot only; enabled and implementation are not operational approval."""
    from .models import AgentSettings
    from .operation_execution import REGISTRY
    from . import intake
    from django.conf import settings
    snapshot = dict(evaluate(organization_id))
    configured = AgentSettings.objects.filter(organization_id=organization_id).first()
    flags = getattr(settings, 'AGENT_OPERATION_EXECUTION_ENABLED', {})
    snapshot['implementation'] = 'INSTALLED'
    snapshot['agent_enabled'] = bool(configured and configured.enabled)
    snapshot['activation_model'] = 'RELEASE_APPROVAL_WITH_EXISTING_GATES'
    snapshot['approved_at'] = snapshot['approved_at'].isoformat() if snapshot['approved_at'] else None
    snapshot['approved_capabilities'] = snapshot.pop('capabilities')
    snapshot['write_gates'] = {}
    for kind, entry in REGISTRY.items():
        reasons = []
        if intake.write_is_contained(entry.capability):
            reasons.append('containment_closed')
        if not snapshot['agent_enabled']:
            reasons.append('agent_disabled')
        if snapshot['status'] != 'READY':
            reasons.append('beta_requirements_pending')
        elif entry.capability not in snapshot['approved_capabilities']:
            reasons.append('beta_capability_not_approved')
        if type(flags) is not dict or flags.get(kind) is not True:
            reasons.append('flag_disabled')
        if getattr(settings, 'AGENT_B7B_CONSENT_ENABLED', False) is not True:
            reasons.append('consent_feature_disabled')
        if entry.enabled is not True or entry.adapter is None or getattr(entry.adapter, 'transaction_mode', None) != 'LOCAL_ATOMIC':
            reasons.append('adapter_contract_disabled')
        snapshot['write_gates'][kind] = reasons
    snapshot['operation_checks_required'] = (
        'witness', 'human_precedence', 'identity', 'binding', 'causal_consent',
        'approval_date', 'domain_preconditions',
    )
    return snapshot
