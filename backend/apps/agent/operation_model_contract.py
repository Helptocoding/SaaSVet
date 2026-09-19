"""ORM enforcement for immutable B7A definitions and disabled future states."""
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import TenantQuerySet


class OperationQuerySet(TenantQuerySet):
    def update(self, **kwargs):
        raise ValidationError('Operations are immutable; use the lifecycle service')

    def bulk_update(self, *args, **kwargs):
        raise ValidationError('Operations cannot be bulk edited')

    def bulk_create(self, *args, **kwargs):
        raise ValidationError('Operations require the preparation service')

    def retire_pending(self, state, reason):
        if state not in ('INVALIDATED', 'EXPIRED'):
            raise ValidationError('B7A cannot grant consent or execute')
        from django.utils import timezone
        return super(OperationQuerySet, self.filter(consent_state='PENDING')).update(
            consent_state=state, invalidation_reason=reason, updated_at=timezone.now())

    def for_organization(self, organization):
        if organization is None:
            raise ValueError('Organization required')
        return self.filter(organization=organization)


OperationManager = models.Manager.from_queryset(OperationQuerySet)


def validate_operation(operation):
    from .capabilities import operation_capability
    from .operation_schema import canonicalize, digest, InvalidParameters
    from .operations import digest_bindings
    spec = operation_capability(operation.operation_kind)
    try:
        canonical = canonicalize(operation.operation_kind, operation.parameters,
                                 version=operation.parameters_schema_version)
        if canonical != operation.parameters or operation.parameters_digest != digest(
                operation.operation_kind, canonical, version=operation.parameters_schema_version,
                bindings=digest_bindings(operation)):
            raise InvalidParameters('noncanonical definition/digest')
    except InvalidParameters as exc:
        raise ValidationError(str(exc)) from exc
    if spec.authorization_mode != operation.authorization_mode:
        raise ValidationError('Authorization mode differs from manifest')
    # Future lifecycle is representable, but B7A has NO writer for it.
    if (operation.consent_state not in ('PENDING', 'INVALIDATED', 'EXPIRED')
            or operation.execution_state != 'NOT_STARTED' or operation.proposal_message_id
            or operation.authorization_message_id or operation.authorized_at
            or operation.authorization_channel or operation.authorization_policy_version
            or operation.result or operation.result_code or operation.executed_at):
        raise ValidationError('B7A cannot emit, authorize, reject by consent, or execute')
    old = None
    if operation.pk:
        old = type(operation).all_objects.select_for_update().filter(pk=operation.pk).first()
        if old:
            mutable = {'consent_state', 'invalidation_reason', 'updated_at', 'updated_by_id'}
            for field in operation._meta.concrete_fields:
                if field.attname not in mutable and getattr(old, field.attname) != getattr(operation, field.attname):
                    raise ValidationError('Persisted operation definition is immutable')
            if old.consent_state != operation.consent_state and not (
                    old.consent_state == 'PENDING' and operation.consent_state in ('INVALIDATED', 'EXPIRED')):
                raise ValidationError('Terminal operation cannot be revived')
    if old is None:
        if operation.consent_state != 'PENDING':
            raise ValidationError('Operations start PENDING')
        from .operations import _preparing
        if not _preparing.get():
            raise ValidationError('New definitions require the operation service')
    conv = operation.conversation
    work = operation.source_turn
    if (conv.organization_id != operation.organization_id or conv.contact_id != operation.contact_id
            or operation.contact.organization_id != operation.organization_id
            or work.organization_id != operation.organization_id or work.conversation_id != conv.pk
            or operation.source_message_id != work.anchor_message_id):
        raise ValidationError('Operation causal/tenant scope mismatch')
    if operation.goal_id and (operation.goal.organization_id != operation.organization_id
                             or operation.goal.conversation_id != conv.pk):
        raise ValidationError('Operation matter scope mismatch')
    for entity in ('owner', 'pet', 'appointment'):
        obj = getattr(operation, entity)
        if obj and obj.organization_id != operation.organization_id:
            raise ValidationError('Operation entity tenant mismatch')
    if operation.pet_id and operation.pet.owner_id != operation.owner_id:
        raise ValidationError('Operation pet/owner mismatch')
    if operation.appointment_id and operation.appointment.pet_id != operation.pet_id:
        raise ValidationError('Operation appointment/pet mismatch')
    if operation.replaces_id:
        previous = operation.replaces
        # Only point backwards to an existing row; immutable links cannot cycle.
        if (previous.pk == operation.pk or (operation.pk and previous.pk >= operation.pk)
                or previous.organization_id != operation.organization_id
                or previous.conversation_id != conv.pk or previous.goal_id != operation.goal_id
                or previous.consent_state == 'PENDING'):
            raise ValidationError('Invalid replacement chain')
