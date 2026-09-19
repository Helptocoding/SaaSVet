"""Effect-proportional eligibility to propose; never consent or a WRITE guard."""
from dataclasses import dataclass
from . import identity
from .capabilities import OPERATIONS, WRITE_BUSINESS


@dataclass(frozen=True)
class ActorPermission:
    result: str
    reason: str
    evidence: dict


def actor_permission(conversation, goal, capability):
    from .models import ContactIdentity, Conversation
    spec = OPERATIONS.get(capability)
    contact = conversation.contact
    def deny(result, reason):
        return ActorPermission(result, reason, {})
    if not spec or spec.effect != WRITE_BUSINESS or not spec.operation_kind:
        return deny('FORBIDDEN', 'unsupported_capability')
    if (not conversation.is_active or conversation.state != Conversation.STATE_ACTIVE or conversation.claimed_by_id
            or contact.is_blocked or not contact.is_active):
        return deny('FORBIDDEN', 'human_or_closed_ownership')
    if contact.organization_id != conversation.organization_id:
        return deny('FORBIDDEN', 'tenant_scope')
    if contact.is_ambiguous or contact.auto_rematch_blocked:
        return deny('REQUIRES_STEP_UP', 'identity_disputed')
    if not identity.is_verification_current(contact):
        return deny('REQUIRES_IDENTITY', 'current_link_required')
    if contact.authorization_revision == 0 and contact.verification_level != ContactIdentity.VERIFICATION_STAFF:
        return deny('REQUIRES_IDENTITY', 'legacy_identity_requires_revalidation')
    if contact.linked_via == ContactIdentity.LINKED_FAMILY and not spec.family_allowed:
        return deny('FORBIDDEN', 'family_restricted')
    if goal.bound_owner_id != contact.owner_id:
        return deny('FORBIDDEN', 'owner_scope')
    from .matter_binding import validate_entities
    try:
        validate_entities(goal, conversation, {})
    except ValueError:
        return deny('FORBIDDEN', 'entity_scope')
    return ActorPermission('ALLOWED_TO_PROPOSE', 'current_relationship', {
        'policy_version': 1, 'capability': capability,
        'identity_policy': spec.identity_policy,
        'verification_level': contact.verification_level, 'linked_via': contact.linked_via,
    })
