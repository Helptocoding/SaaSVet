"""B8A server-side boundary. Production autonomous WRITE gates remain CLOSED.

Only local DB effects may be added under this contract. No HTTP, LLM, durable
RUNNING state, arbitrary request parameters or provider exactly-once claim.
"""
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import Q

from . import durable, intake, operation_consent, operation_permission
from .capabilities import OPERATIONS, EFFECTS, WRITE_BUSINESS
from .operation_schema import canonicalize, digest, InvalidParameters
from .operations import digest_bindings

logger = logging.getLogger('agent.events')
EVENTS = frozenset(('execution_guard_denied', 'execution_guard_allowed', 'execution_gate_closed',
    'execution_precondition_failed', 'execution_stale_revision', 'execution_permission_denied',
    'execution_started', 'execution_succeeded', 'execution_failed', 'execution_uncertain',
    'execution_reconciled', 'execution_duplicate_suppressed'))
GATE_REASONS = frozenset(('containment_closed', 'kind_disabled', 'flag_disabled',
    'adapter_missing', 'adapter_contract_disabled', 'consent_feature_disabled'))
PRECONDITION_REASONS = frozenset(('entity_inactive', 'entity_scope', 'appointment_changed',
    'appointment_not_mutable', 'schedule_elapsed', 'slot_unavailable', 'invalid_pet_data',
    'domain_conflict', 'precondition_failed', 'schedule_closed', 'invalid_local_time', 'appointment_no_change'))
FAILURE_REASONS = PRECONDITION_REASONS | {'definitive_rejection', 'reconciled_no_effect'}


@dataclass(frozen=True)
class ExecutionContext:
    """Server-supplied B3 witness; not tool args, bearer headers or LLM output."""
    witness: durable.OwnershipWitness
    contact_id: int
    capability: str

    def __post_init__(self):
        if (not isinstance(self.witness, durable.OwnershipWitness)
                or not isinstance(self.witness.lease_token, UUID)
                or type(self.contact_id) is not int or self.contact_id <= 0
                or not isinstance(self.capability, str)):
            raise ValueError('Invalid server execution context')


@dataclass(frozen=True)
class EffectEvidence:
    operation_key: UUID
    parameters_digest: str
    domain_object_id: str
    committed_at: datetime

    def matches(self, operation):
        return (self.operation_key == operation.operation_key
            and self.parameters_digest == operation.parameters_digest
            and type(self.domain_object_id) is str and 0 < len(self.domain_object_id) <= 64
            and isinstance(self.committed_at, datetime) and self.committed_at.tzinfo is not None
            and operation.authorized_at <= self.committed_at <= durable.db_now())


@dataclass(frozen=True)
class AdapterResult:
    status: str  # SUCCEEDED / FAILED / UNCERTAIN / ABSENT (reconcile only)
    evidence: EffectEvidence | None = None
    reason: str = ''
    no_effect_confirmed: bool = False
    operation_key: UUID | None = None
    parameters_digest: str = ''

    def proves_absence_for(self, operation):
        return (self.no_effect_confirmed is True and self.operation_key == operation.operation_key
                and self.parameters_digest == operation.parameters_digest)


@dataclass(frozen=True)
class PreconditionResult:
    allowed: bool
    reason: str = ''
    transient: bool = False


class OperationAdapter(Protocol):
    """Trusted code, never a tool callable or dynamically loaded plugin.

    validate_preconditions must lock current tenant/domain rows in the domain's
    documented order and validate exact parameters/expected_state/availability.
    Locks survive execute and reconcile. All three use the guard's DB connection.
    reconcile must query durable evidence by operation_key + digest + tenant;
    ABSENT/no_effect_confirmed is a domain assertion, not an empty HTTP response.
    committed_at is recorded inside the atomic commit, visible only after commit.
    External effects are unsupported until a separate provider contract exists.
    """
    transaction_mode: str

    def validate_preconditions(self, operation, context: ExecutionContext) -> PreconditionResult: ...
    def reconcile(self, operation, context: ExecutionContext) -> AdapterResult: ...
    def execute(self, operation, context: ExecutionContext) -> AdapterResult: ...


@dataclass(frozen=True)
class Registration:
    capability: str
    enabled: bool = False
    adapter: OperationAdapter | None = None


from .appointment_execution import CreateAppointmentAdapter
from .appointment_mutation_execution import RescheduleAppointmentAdapter, CancelAppointmentAdapter

REGISTRY = MappingProxyType({
    'CREATE_APPOINTMENT': Registration('create_appointment', enabled=True, adapter=CreateAppointmentAdapter()),
    'RESCHEDULE_APPOINTMENT': Registration('reschedule_appointment', enabled=True, adapter=RescheduleAppointmentAdapter()),
    'CANCEL_APPOINTMENT': Registration('cancel_appointment', enabled=True, adapter=CancelAppointmentAdapter()),
    'CONFIRM_ATTENDANCE': Registration('confirm_appointment'),
    'REGISTER_PET': Registration('register_pet_only'),
})


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason: str
    operation_key: UUID | None = None
    evidence: EffectEvidence | None = None
    duplicate: bool = False
    reconciliation_required: bool = False


def observe(event):
    if event not in EVENTS:
        raise ValueError('Unknown execution event')
    transaction.on_commit(lambda: logger.info('AGENT_B8A_' + event.upper(),
        extra={'event': event, 'count': 1, 'schema': 1}))


def legacy_write_denied():
    """No arbitrary WRITE handler/HTTP call can become a guard bypass."""
    return True


def agent_api_write_denied(user, method):
    # Future B8 adapters must enter the guard explicitly server-side. Neither
    # optional headers nor a staff RBAC grant opens legacy domain endpoints.
    return getattr(user, 'role', None) == 'AGENT' and method.upper() not in ('GET', 'HEAD', 'OPTIONS')


def _gate(operation, entry):
    if intake.write_is_contained(entry.capability):
        return 'containment_closed'
    if entry.enabled is not True:
        return 'kind_disabled'
    flags = getattr(settings, 'AGENT_OPERATION_EXECUTION_ENABLED', None)
    if type(flags) is not dict or flags.get(operation.operation_kind) is not True:
        return 'flag_disabled'
    if getattr(settings, 'AGENT_B7B_CONSENT_ENABLED', False) is not True:
        return 'consent_feature_disabled'
    if entry.adapter is None:
        return 'adapter_missing'
    if getattr(entry.adapter, 'transaction_mode', None) != 'LOCAL_ATOMIC':
        return 'adapter_contract_disabled'
    return ''


def _record(operation, status, reason, evidence=None):
    """Private lifecycle update under operation lock; no definition/consent edits.

    Deliberately does not call Model.save's historical proposal validation: a
    stale/corrupted definition must still be inspectable as denied. Normal ORM
    writers remain forbidden from altering execution or terminal evidence.
    """
    from .models import ConversationOperation
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('Execution record requires the guard transaction')
    if operation.execution_state in ('SUCCEEDED', 'FAILED'):
        raise ValueError('Confirmed execution results are immutable')
    if status not in ('BLOCKED', 'SUCCEEDED', 'FAILED', 'UNCERTAIN'):
        raise ValueError('Invalid execution result')
    if status != 'BLOCKED' and operation.consent_state != 'AUTHORIZED':
        raise ValueError('Effect record requires historical authorization')
    if status == 'SUCCEEDED' and (not isinstance(evidence, EffectEvidence) or not evidence.matches(operation)):
        raise ValueError('Durable exact effect evidence required')
    result = {'schema': 1, 'status': status, 'reason': reason,
        'operation_key': str(operation.operation_key),
        'reconciliation_required': status == 'UNCERTAIN',
        'no_effect_confirmed': status == 'FAILED'}
    if evidence:
        result['evidence'] = {**asdict(evidence), 'operation_key': str(evidence.operation_key),
                              'committed_at': evidence.committed_at.isoformat()}
    state = 'NOT_STARTED' if status == 'BLOCKED' else status
    stamp = evidence.committed_at if status == 'SUCCEEDED' else None
    qs = ConversationOperation.objects.filter(pk=operation.pk,
        organization_id=operation.organization_id, execution_state=operation.execution_state)
    if models.QuerySet.update(qs, execution_state=state, result=result, result_code=reason,
                              executed_at=stamp, updated_at=durable.db_now()) != 1:
        raise RuntimeError('Execution lifecycle conflict')
    operation.execution_state, operation.result, operation.result_code = state, result, reason
    operation.executed_at = stamp


def _deny(operation, reason, *, event='execution_guard_denied', durable_block=True):
    observe(event)
    if event != 'execution_guard_denied':
        observe('execution_guard_denied')
    if (operation is not None and operation.execution_state == 'NOT_STARTED' and durable_block
            and operation.result_code not in PRECONDITION_REASONS and not _contradictory_record(operation)):
        _record(operation, 'BLOCKED', reason)
    return ExecutionResult('DENIED', reason, operation.operation_key if operation else None)


def _contradictory_record(operation):
    value = operation.result
    return bool(operation.executed_at or (value and (
        not isinstance(value, dict) or value.get('schema') != 1 or value.get('status') != 'BLOCKED'
        or value.get('operation_key') != str(operation.operation_key)
        or set(value) - {'schema', 'status', 'reason', 'operation_key',
                         'reconciliation_required', 'no_effect_confirmed'}
        or value.get('reconciliation_required') is not False
        or value.get('no_effect_confirmed') is not False)))


def _definition_reason(operation, conv, goal, context):
    if type(operation.permission_snapshot) is not dict or type(operation.preconditions) is not dict:
        return 'definition_corrupted'
    spec = OPERATIONS.get(context.capability)
    entry = REGISTRY.get(operation.operation_kind)
    if (not spec or not entry or entry.capability != context.capability
            or spec.operation_kind != operation.operation_kind
            or spec.effect != WRITE_BUSINESS or EFFECTS.get(context.capability) != WRITE_BUSINESS
            or operation.permission_snapshot.get('capability') != context.capability
            or operation.authorization_mode != spec.authorization_mode):
        return 'capability_mismatch'
    if (operation.contact_id != conv.contact_id or context.contact_id != conv.contact_id
            or operation.organization_id != conv.organization_id
            or conv.channel_account.organization_id != conv.organization_id
            or conv.contact.organization_id != conv.organization_id
            or not goal or goal.organization_id != conv.organization_id or goal.conversation_id != conv.pk
            or goal.name != spec.goal
            or operation.source_turn.organization_id != conv.organization_id
            or operation.source_turn.conversation_id != conv.pk
            or operation.source_message_id != operation.source_turn.anchor_message_id):
        return 'scope_mismatch'
    if not operation.is_active or not conv.channel_account.is_active:
        return 'scope_inactive'
    try:
        if (canonicalize(operation.operation_kind, operation.parameters,
                version=operation.parameters_schema_version) != operation.parameters
                or digest(operation.operation_kind, operation.parameters,
                    version=operation.parameters_schema_version, bindings=digest_bindings(operation))
                    != operation.parameters_digest):
            return 'digest_mismatch'
    except (InvalidParameters, ValueError, TypeError, KeyError):
        return 'digest_mismatch'
    for field in ('owner', 'pet', 'appointment'):
        obj = getattr(operation, field)
        if obj and obj.organization_id != conv.organization_id:
            return 'entity_scope'
        if obj and not obj.is_active:
            return 'entity_inactive'
    if (not operation.owner_id or (operation.operation_kind != 'REGISTER_PET' and not operation.pet_id)
            or (operation.operation_kind in ('CANCEL_APPOINTMENT', 'RESCHEDULE_APPOINTMENT',
                'CONFIRM_ATTENDANCE') and not operation.appointment_id)
            or (operation.pet_id and operation.pet.owner_id != operation.owner_id)
            or (operation.appointment_id and operation.appointment.pet_id != operation.pet_id)):
        return 'entity_scope'
    params = operation.parameters
    if any(params.get(field) != getattr(operation, field) for field in
           ('owner_id', 'pet_id', 'appointment_id') if field in params):
        return 'entity_scope'
    if 'veterinarian_id' in params:
        from apps.users.models import User
        if not User.objects.filter(pk=params['veterinarian_id'], organization_id=conv.organization_id,
                is_active=True, role='VET').exists():
            return 'entity_scope'
    return ''


def _authority_reason(operation, conv, goal, work, context):
    from .models import ConversationGoal, HumanHandoff
    from . import safety, safety_handoff
    if operation.ownership_epoch != conv.ownership_epoch:
        return 'ownership_stale'
    if conv.state != conv.STATE_ACTIVE or conv.claimed_by_id:
        return 'human_takeover'
    if (HumanHandoff.objects.filter(conversation=conv, resolved_at__isnull=True).exists()
            or safety_handoff.pending_signal(conv)
            or safety.assess_context(conv, durable.context_for_work(context.witness)).classification != safety.NO_SIGNAL):
        return 'safety_handoff'
    if operation.identity_revision != conv.contact.authorization_revision:
        return 'identity_stale'
    if operation.binding_revision != goal.binding_revision:
        return 'binding_stale'
    if goal.status not in ConversationGoal.FOREGROUND_STATUSES:
        return 'matter_inactive'
    if operation.replacements.exists():
        return 'operation_replaced'
    if (operation.owner_id, operation.pet_id, operation.appointment_id) != (
            goal.bound_owner_id, goal.bound_pet_id, goal.bound_appointment_id):
        return 'binding_stale'
    permission = operation_permission.actor_permission(conv, goal, context.capability, purpose='execute')
    if permission.result != 'ALLOWED_TO_EXECUTE':
        observe('execution_permission_denied')
        return {'REQUIRES_IDENTITY': 'requires_identity', 'REQUIRES_STEP_UP': 'requires_step_up'}.get(
            permission.result, 'permission_forbidden')
    if durable.has_new_input(work):
        return 'new_input'
    # No processed message can silently erase an earlier revocation/correction.
    from apps.channels.models import Message
    response = operation.authorization_message
    if Message.objects.filter(conversation=conv, direction='in').filter(
            Q(created_at__gt=response.created_at) | Q(created_at=response.created_at, pk__gt=response.pk)).exists():
        return 'authorization_superseded_by_input'
    if operation.expires_at <= durable.db_now():
        return 'operation_expired'
    return ''


def _uncertain(operation, reason):
    _record(operation, 'UNCERTAIN', reason)
    observe('execution_uncertain')
    if operation.operation_kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT'):
        from .appointment_mutation_execution import observe as observe_mutation
        observe_mutation('appointment_mutation_uncertain')
    return ExecutionResult('UNCERTAIN', reason, operation.operation_key, reconciliation_required=True)


def _success(operation, evidence, *, reconciled=False):
    _record(operation, 'SUCCEEDED', 'effect_confirmed', evidence)
    observe('execution_reconciled' if reconciled else 'execution_succeeded')
    if not reconciled and operation.operation_kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT'):
        from .appointment_mutation_execution import observe as observe_mutation
        observe_mutation('appointment_' + ('reschedule' if operation.operation_kind ==
            'RESCHEDULE_APPOINTMENT' else 'cancel') + '_succeeded')
    return ExecutionResult('SUCCEEDED', 'effect_confirmed', operation.operation_key, evidence,
                           duplicate=reconciled)


def _reconcile(adapter, operation, context):
    try:
        # Savepoint makes infrastructure errors recoverable without hiding a
        # broken PostgreSQL transaction; no execute fallback on query failure.
        with transaction.atomic():
            value = adapter.reconcile(operation, context)
        if not isinstance(value, AdapterResult):
            return AdapterResult('UNCERTAIN')
        if value.status in ('ABSENT', 'FAILED') and not value.proves_absence_for(operation):
            return AdapterResult('UNCERTAIN')
        return value
    except Exception:
        return AdapterResult('UNCERTAIN', reason='reconciliation_unavailable')


def _prior_result(operation):
    raw = operation.result or {}
    try:
        if (raw['schema'] != 1 or raw['operation_key'] != str(operation.operation_key)
                or raw['status'] != operation.execution_state or raw['reason'] != operation.result_code):
            raise ValueError('Inconsistent ledger')
        evidence = None
        if operation.execution_state == 'SUCCEEDED':
            data = raw['evidence']
            evidence = EffectEvidence(UUID(data['operation_key']), data['parameters_digest'],
                data['domain_object_id'], datetime.fromisoformat(data['committed_at']))
            if not evidence.matches(operation) or operation.executed_at != evidence.committed_at:
                raise ValueError('Missing result evidence')
        elif raw.get('no_effect_confirmed') is not True:
            raise ValueError('Missing no-effect proof')
        observe('execution_duplicate_suppressed')
        return ExecutionResult(operation.execution_state, operation.result_code, operation.operation_key,
                               evidence, duplicate=True)
    except (KeyError, ValueError, TypeError, AttributeError):
        # Preserve even a damaged terminal ledger for operational investigation.
        observe('execution_uncertain')
        return ExecutionResult('UNCERTAIN', 'ledger_inconsistent', operation.operation_key,
                               reconciliation_required=True)


def execute_authorized_operation(operation_key, context: ExecutionContext):
    """The only autonomous effect entry; no model parameters or adapter argument.

    Registry injection exists exclusively via test monkeypatch, not settings.
    A valid new B3 witness is mandatory, including recovery of old TurnWork.
    """
    from .models import ConversationOperation, ConversationGoal, ContactIdentity, ToolExecution
    if not isinstance(context, ExecutionContext) or not isinstance(operation_key, UUID):
        return _deny(None, 'invalid_execution_context')
    try:
        with transaction.atomic():
            conv, work = durable.lock_witness(context.witness)
            durable.check_turn_deadline(context.witness)
            conv.contact = ContactIdentity.all_objects.select_for_update().get(
                pk=conv.contact_id, organization_id=conv.organization_id)
            # Scope lookup does not lock Operation before Goal (B6 lock order).
            candidate = ConversationOperation.objects.filter(operation_key=operation_key,
                organization_id=conv.organization_id, conversation=conv, contact_id=context.contact_id).first()
            if candidate is None:
                return _deny(None, 'operation_not_found')
            goal = ConversationGoal.objects.select_for_update().filter(pk=candidate.goal_id,
                organization_id=conv.organization_id, conversation=conv).first()
            operation = ConversationOperation.objects.select_for_update().get(pk=candidate.pk)
            operation.conversation, operation.contact, operation.goal = conv, conv.contact, goal
            if operation.operation_kind == 'CREATE_APPOINTMENT':
                from .appointment_execution import observe as observe_appointment
                observe_appointment('appointment_execution_requested')
            elif operation.operation_kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT'):
                from .appointment_mutation_execution import observe as observe_mutation
                observe_mutation('appointment_' + ('reschedule' if operation.operation_kind ==
                    'RESCHEDULE_APPOINTMENT' else 'cancel') + '_requested')
            reason = _definition_reason(operation, conv, goal, context)
            if reason:
                return _deny(operation, reason)
            if operation.consent_state != 'AUTHORIZED':
                return _deny(operation, 'consent_not_authorized')
            if operation.authorization_mode != 'EXPLICIT_CONFIRMATION':
                return _deny(operation, 'authorization_mode_disabled')
            try:
                operation_consent.execution_authorization_evidence(operation)
            except (ValueError, TypeError, KeyError, AttributeError, ObjectDoesNotExist):
                return _deny(operation, 'authorization_evidence_invalid')
            # Historical results are not eligibility checks or new effects.
            permission = operation_permission.actor_permission(conv, goal, context.capability, purpose='execute')
            if permission.result != 'ALLOWED_TO_EXECUTE':
                return _deny(operation, {'REQUIRES_IDENTITY': 'requires_identity',
                    'REQUIRES_STEP_UP': 'requires_step_up'}.get(permission.result, 'permission_forbidden'),
                    event='execution_permission_denied')
            if operation.execution_state in ('SUCCEEDED', 'FAILED'):
                terminal_adapter = REGISTRY[operation.operation_kind].adapter
                if getattr(terminal_adapter, 'reconcile_terminal', False):
                    prior = _reconcile(terminal_adapter, operation, context)
                    ledger = _prior_result(operation)
                    consistent = (
                        operation.execution_state == 'SUCCEEDED' and prior.status == 'SUCCEEDED'
                        and prior.evidence == ledger.evidence and ledger.status == 'SUCCEEDED'
                    ) or (
                        operation.execution_state == 'FAILED' and prior.status == 'ABSENT'
                        and prior.proves_absence_for(operation) and ledger.status == 'FAILED'
                    )
                    if not consistent:
                        if operation.operation_kind == 'CREATE_APPOINTMENT':
                            observe_appointment('appointment_execution_uncertain')
                        else:
                            observe_mutation('appointment_mutation_uncertain')
                        return ExecutionResult('UNCERTAIN', 'appointment_evidence_mismatch',
                            operation.operation_key, reconciliation_required=True)
                    if operation.operation_kind == 'CREATE_APPOINTMENT':
                        observe_appointment('appointment_duplicate_suppressed')
                    return ledger
                return _prior_result(operation)
            entry = REGISTRY[operation.operation_kind]
            # Reconciliation can run after expiry or a closed execution gate. It
            # cannot call execute. No adapter means no invented domain evidence.
            adapter = entry.adapter
            if adapter is not None and getattr(adapter, 'transaction_mode', None) == 'LOCAL_ATOMIC':
                prior = _reconcile(adapter, operation, context)
                if (prior.status == 'SUCCEEDED' and isinstance(prior.evidence, EffectEvidence)
                        and prior.evidence.matches(operation)):
                    return _success(operation, prior.evidence, reconciled=True)
                if operation.execution_state == 'UNCERTAIN':
                    if prior.status == 'FAILED' and prior.proves_absence_for(operation) and prior.reason in FAILURE_REASONS:
                        _record(operation, 'FAILED', prior.reason)
                        observe('execution_reconciled')
                        return ExecutionResult('FAILED', prior.reason, operation.operation_key)
                    return _uncertain(operation, 'reconciliation_required')
                if prior.status != 'ABSENT' or not prior.proves_absence_for(operation):
                    return _uncertain(operation, 'reconciliation_required')
            elif operation.execution_state == 'UNCERTAIN':
                return _uncertain(operation, 'reconciliation_required')
            if (_contradictory_record(operation)
                    or ToolExecution.objects.filter(operation=operation).exclude(policy_decision='denied').exists()):
                return _uncertain(operation, 'contradictory_attempt_evidence')
            # A definitive precondition failure cannot be erased by a retry.
            if operation.result_code in PRECONDITION_REASONS:
                return _deny(operation, operation.result_code, event='execution_precondition_failed')
            reason = _authority_reason(operation, conv, goal, work, context)
            if reason:
                return _deny(operation, reason, event='execution_stale_revision' if reason.endswith('_stale')
                             else 'execution_guard_denied')
            reason = _gate(operation, entry)
            if reason:
                return _deny(operation, reason, event='execution_gate_closed')
            try:
                with transaction.atomic():
                    check = adapter.validate_preconditions(operation, context)
                if not isinstance(check, PreconditionResult):
                    return _deny(operation, 'precondition_contract_invalid')
                if check.allowed is not True:
                    reason = ('precondition_infrastructure' if check.transient else
                        check.reason if check.reason in PRECONDITION_REASONS else 'precondition_failed')
                    return _deny(operation, reason, event='execution_precondition_failed')
            except Exception:
                return _deny(operation, 'precondition_infrastructure', event='execution_precondition_failed')
            # Recheck scope after domain locks; no stale cached FK relationships.
            operation.refresh_from_db()
            operation.conversation, operation.contact, operation.goal = conv, conv.contact, goal
            reason = _definition_reason(operation, conv, goal, context) or _authority_reason(
                operation, conv, goal, work, context)
            if reason:
                return _deny(operation, reason)
            durable.check_turn_deadline(context.witness)
            observe('execution_guard_allowed')
            observe('execution_started')
            ToolExecution.objects.create(organization_id=conv.organization_id, conversation=conv,
                operation=operation, tool_name=context.capability, policy_decision='confirmed',
                triggered_by_message_id=work.anchor_message_id, result_summary_redacted={'execution_started': True})
            try:
                # Savepoint rolls back any local effect on adapter exceptions.
                # Even a timeout is conservatively uncertain: never assume the
                # adapter's downstream system did not commit outside this DB.
                with transaction.atomic():
                    outcome = adapter.execute(operation, context)
            except Exception:
                return _uncertain(operation, 'adapter_exception')
            proof = _reconcile(adapter, operation, context)
            if (proof.status == 'SUCCEEDED' and isinstance(proof.evidence, EffectEvidence)
                    and proof.evidence.matches(operation)):
                result = _success(operation, proof.evidence)
            elif (isinstance(outcome, AdapterResult) and outcome.status == 'FAILED'
                    and outcome.proves_absence_for(operation) and outcome.reason in FAILURE_REASONS
                    and proof.status == 'ABSENT' and proof.proves_absence_for(operation)):
                _record(operation, 'FAILED', outcome.reason)
                observe('execution_failed')
                result = ExecutionResult('FAILED', outcome.reason, operation.operation_key)
            else:
                result = _uncertain(operation, 'effect_unproven')
            # A late worker/expired operation rolls local effect + result back.
            durable.check_turn_deadline(context.witness)
            if durable.db_now() >= operation.expires_at:
                raise TimeoutError('Operation expired at commit boundary')
            return result
    except durable.OwnershipLost:
        return _deny(None, 'ownership_lost')
    except TimeoutError:
        return _deny(None, 'deadline_elapsed')


def execution_stage(operation):
    if operation.execution_state == 'NOT_STARTED' and _contradictory_record(operation):
        return 'INCONSISTENT / RECONCILIATION_PENDING'
    if operation.execution_state == 'UNCERTAIN':
        return 'UNCERTAIN / RECONCILIATION_PENDING'
    if operation.execution_state != 'NOT_STARTED':
        return operation.execution_state
    if operation.result_code in GATE_REASONS:
        return 'BLOCKED_BY_GATE'
    if operation.result_code in PRECONDITION_REASONS or operation.result_code.startswith('precondition_'):
        return 'BLOCKED_BY_PRECONDITIONS'
    if operation.result_code:
        return 'EXECUTION_DENIED'
    return 'AUTHORIZED_NOT_EXECUTED' if operation.consent_state == 'AUTHORIZED' else 'NOT_STARTED'
