"""B8C exact-reference adapters. Registry only; no tool/request parameter path."""
import logging
from datetime import date, time
from django.db import transaction
from apps.appointments.models import AppointmentMutationEffect
from apps.appointments.mutations import (MutationCommand, MutationRejected,
    validate_mutation, mutate_appointment, expected_after)
from apps.appointments.creation import CreationRejected
from .operation_schema import canonicalize

EVENTS = frozenset((
    'appointment_reschedule_requested', 'appointment_reschedule_succeeded',
    'appointment_reschedule_stale', 'appointment_reschedule_slot_unavailable',
    'appointment_cancel_requested', 'appointment_cancel_succeeded', 'appointment_cancel_stale',
    'appointment_mutation_reconciled', 'appointment_mutation_evidence_mismatch',
    'appointment_mutation_uncertain',
))
logger = logging.getLogger('agent.events')


def observe(event):
    if event not in EVENTS:
        raise ValueError('Unknown mutation event')
    transaction.on_commit(lambda: logger.info('AGENT_B8C_' + event.upper(),
        extra={'event': event, 'schema': 1, 'count': 1}), robust=True)


def command_for(operation):
    p = canonicalize(operation.operation_kind, operation.parameters,
                     version=operation.parameters_schema_version)
    pre = operation.preconditions
    old = pre.get('appointment_snapshot')
    if (operation.operation_kind not in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT')
            or p != operation.parameters or p['appointment_id'] != operation.appointment_id
            or pre.get('schema') != 2 or not isinstance(old, dict) or old.get('schema') != 1
            or old.get('appointment_id') != operation.appointment_id
            or old.get('organization_id') != operation.organization_id or old.get('pet_id') != operation.pet_id):
        raise MutationRejected('precondition_failed')
    return MutationCommand(kind=operation.operation_kind, organization_id=operation.organization_id,
        appointment_id=operation.appointment_id, pet_id=operation.pet_id, owner_id=operation.owner_id,
        operation_key=operation.operation_key, parameters_digest=operation.parameters_digest,
        original=old, clinic_timezone=pre['clinic_timezone'],
        date=date.fromisoformat(p['date']) if 'date' in p else None,
        start_time=time.fromisoformat(p['start_time']) if 'start_time' in p else None,
        end_time=time.fromisoformat(p['end_time']) if 'end_time' in p else None,
        veterinarian_id=p.get('veterinarian_id'), cancellation_reason=p.get('cancellation_reason', ''))


class _AppointmentMutationAdapter:
    transaction_mode = 'LOCAL_ATOMIC'
    reconcile_terminal = True

    def _command(self, operation):
        if operation.operation_kind != self.kind:
            raise MutationRejected('precondition_failed')
        return command_for(operation)

    def _absence(self, operation):
        from .operation_execution import AdapterResult
        return AdapterResult('ABSENT', no_effect_confirmed=True,
            operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)

    def validate_preconditions(self, operation, context):
        from .operation_execution import PreconditionResult
        try:
            if operation.contact.owner_id != operation.owner_id:
                raise MutationRejected('entity_scope')
            validate_mutation(self._command(operation))
        except (MutationRejected, CreationRejected) as exc:
            if exc.reason == 'appointment_changed':
                observe(self.prefix + '_stale')
            elif exc.reason == 'slot_unavailable':
                observe('appointment_reschedule_slot_unavailable')
            return PreconditionResult(False, exc.reason)
        return PreconditionResult(True)

    def reconcile(self, operation, context):
        from .operation_execution import AdapterResult, EffectEvidence
        effect = AppointmentMutationEffect.objects.filter(operation_id=operation.operation_key).first()
        if effect is None:
            return self._absence(operation)
        try:
            command = self._command(operation)
            evidence = EffectEvidence(operation.operation_key, effect.parameters_digest,
                command.original['public_id'], effect.committed_at)
            if (effect.organization_id == operation.organization_id and effect.kind == self.kind
                    and effect.appointment_id == operation.appointment_id
                    and effect.parameters_digest == operation.parameters_digest
                    and effect.before == command.original and effect.after == expected_after(command)
                    and effect.before != effect.after and evidence.matches(operation)):
                observe('appointment_mutation_reconciled')
                return AdapterResult('SUCCEEDED', evidence)
        except (ValueError, KeyError, TypeError, CreationRejected):
            pass
        observe('appointment_mutation_evidence_mismatch')
        observe('appointment_mutation_uncertain')
        return AdapterResult('UNCERTAIN', reason='appointment_evidence_mismatch')

    def execute(self, operation, context):
        from .operation_execution import AdapterResult
        try:
            mutate_appointment(self._command(operation))
        except (MutationRejected, CreationRejected) as exc:
            proof = self.reconcile(operation, context)
            if proof.status == 'ABSENT':
                return AdapterResult('FAILED', reason=exc.reason, no_effect_confirmed=True,
                    operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)
            return AdapterResult('UNCERTAIN', reason='appointment_evidence_mismatch')
        return self.reconcile(operation, context)


class RescheduleAppointmentAdapter(_AppointmentMutationAdapter):
    kind = 'RESCHEDULE_APPOINTMENT'
    prefix = 'appointment_reschedule'


class CancelAppointmentAdapter(_AppointmentMutationAdapter):
    kind = 'CANCEL_APPOINTMENT'
    prefix = 'appointment_cancel'
