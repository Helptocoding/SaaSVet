"""B8E: exact authorized individual Pet INSERT; no tools, HTTP or owner lookup."""
import logging
from datetime import date

from django.db import OperationalError, transaction
from django.core.exceptions import ValidationError as ModelValidationError
from rest_framework.exceptions import ValidationError

from apps.patients import creation
from apps.patients.models import Pet, PetRegistrationEffect
from .operation_schema import canonicalize, digest

logger = logging.getLogger('agent.events')
EVENTS = frozenset(('pet_registration_requested', 'pet_registration_succeeded',
    'pet_registration_precondition_failed', 'pet_registration_reconciled',
    'pet_registration_evidence_mismatch', 'pet_registration_uncertain'))


def observe(event):
    if event not in EVENTS:
        raise ValueError('Unknown pet registration event')
    transaction.on_commit(lambda: logger.info('AGENT_B8E_' + event.upper(),
        extra={'event': event, 'count': 1, 'schema': 1}), robust=True)


def registration_contract(operation):
    pre = operation.preconditions
    snapshot = pre.get('owner_snapshot', {})
    return (operation.operation_kind == 'REGISTER_PET' and pre.get('schema') == 4
        and pre.get('registration_contract') == 1 and isinstance(snapshot, dict)
        and snapshot.get('schema') == 1 and snapshot.get('id') == operation.owner_id
        and snapshot.get('organization_id') == operation.organization_id
        and snapshot.get('is_active') is True and snapshot.get('is_generic') is False
        and not operation.pet_id and not operation.appointment_id)


def fields_for(operation):
    if not registration_contract(operation):
        raise creation.PetCreationRejected('invalid_pet_data')
    params = canonicalize(operation.operation_kind, operation.parameters,
        version=operation.parameters_schema_version)
    if params != operation.parameters or params['owner_id'] != operation.owner_id:
        raise creation.PetCreationRejected('invalid_pet_data')
    fields = {k: v for k, v in params.items() if k != 'owner_id'}
    if 'birth_date' in fields:
        fields['birth_date'] = date.fromisoformat(fields['birth_date'])
    return fields


def definition_for(operation):
    fields = fields_for(operation)
    return {'name': fields['name'], 'species': fields.get('species', ''),
        'birth_date': operation.parameters.get('birth_date'), 'sex': 'unknown',
        'breed': '', 'color': '', 'legacy_id': '', 'extra_data': [],
        'is_generic': False, 'is_active': True}


def definition_digest_matches(operation):
    from .operations import digest_bindings
    try:
        return operation.parameters_digest == digest(operation.operation_kind,
            operation.parameters, version=operation.parameters_schema_version,
            bindings=digest_bindings(operation))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


class RegisterPetAdapter:
    transaction_mode = 'LOCAL_ATOMIC'
    reconcile_terminal = True

    def validate_preconditions(self, operation, context):
        from .operation_execution import PreconditionResult
        try:
            fields = fields_for(operation)
            # Owner.save can revoke ContactIdentity while holding Owner. Do not
            # wait for that inverse domain->identity path under B8A identity locks.
            with transaction.atomic():
                org, owner = creation.lock_creation_scope(operation.organization_id,
                    operation.owner_id, owner_nowait=True)
            if (operation.contact.owner_id != owner.pk
                    or operation.contact.organization_id != org.pk
                    or operation.goal.bound_owner_id != owner.pk or owner.is_generic):
                raise creation.PetCreationRejected('entity_scope')
            if (org.timezone != operation.preconditions['clinic_timezone']
                    or creation.owner_snapshot(owner) != operation.preconditions['owner_snapshot']):
                raise creation.PetCreationRejected('precondition_failed')
            if creation.validate_fields(fields, org) != fields:
                raise creation.PetCreationRejected('invalid_pet_data')
            Pet(organization=org, owner=owner, **fields).full_clean()
        except OperationalError as exc:
            if getattr(exc.__cause__, 'sqlstate', None) != '55P03':
                raise
            observe('pet_registration_precondition_failed')
            return PreconditionResult(False, 'domain_conflict', transient=True)
        except (creation.PetCreationRejected, ValidationError, ModelValidationError, ValueError) as exc:
            observe('pet_registration_precondition_failed')
            return PreconditionResult(False, getattr(exc, 'reason', 'invalid_pet_data'))
        return PreconditionResult(True)

    def reconcile(self, operation, context):
        from .operation_execution import AdapterResult, EffectEvidence
        # Global exact UUID detects contradictions; never search Pet by similarity.
        effect = PetRegistrationEffect.objects.filter(operation_id=operation.operation_key).first()
        if effect is None:
            return AdapterResult('ABSENT', no_effect_confirmed=True,
                operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)
        try:
            pet = Pet.all_objects.get(pk=effect.pet_id)
            proof = EffectEvidence(operation.operation_key, effect.parameters_digest,
                str(pet.public_id), effect.committed_at)
            if (definition_digest_matches(operation)
                    and effect.organization_id == operation.organization_id == pet.organization_id
                    and effect.owner_id == operation.owner_id
                    and effect.definition == definition_for(operation)
                    and proof.matches(operation)):
                # Mutable Pet values do not define historical creation. Never restore.
                observe('pet_registration_reconciled')
                return AdapterResult('SUCCEEDED', proof)
        except (ValueError, TypeError, KeyError, Pet.DoesNotExist):
            pass
        observe('pet_registration_evidence_mismatch')
        return AdapterResult('UNCERTAIN', reason='pet_registration_evidence_mismatch')

    def execute(self, operation, context):
        from .durable import db_now
        pet = creation.create_pet(organization_id=operation.organization_id,
            owner_id=operation.owner_id, fields=fields_for(operation))
        PetRegistrationEffect.objects.create(operation_id=operation.operation_key,
            organization_id=operation.organization_id, owner_id=operation.owner_id, pet=pet,
            parameters_digest=operation.parameters_digest, definition=definition_for(operation),
            committed_at=db_now())
        return self.reconcile(operation, context)
