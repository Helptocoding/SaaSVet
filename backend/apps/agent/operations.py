"""B7A persistent operation definition. No consent adapter, HTTP, or business WRITE.

Locks: Conversation -> TurnWork -> ContactIdentity -> Goal -> Operation.
Identity-only writers lock ContactIdentity and retire Operation without acquiring
Conversation. This preserves the existing B3/B6 and reset/takeover lock order.
"""
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from . import matter_binding as binding
from .capabilities import OPERATIONS
from .operation_permission import actor_permission
from .operation_schema import canonicalize, digest, InvalidParameters

logger = logging.getLogger('agent.events')
TTL = timedelta(minutes=30)
STAGE_KEY = 'business_definition_v1'
_preparing = ContextVar('b7a_preparing', default=False)


class PreparationDenied(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def observe(event, *, count=1):
    # Fixed event names/count only. No IDs, names, phones, text or hashes.
    logger.info('AGENT_B7A_%s', event.upper(), extra={
        'event': 'AGENT_B7A_' + event.upper(), 'count': count, 'schema': 1})


def invalidate_pending(*, organization_id, reason, **scope):
    from .models import ConversationOperation
    count = ConversationOperation.objects.for_organization(organization_id).filter(
        **scope).retire_pending('INVALIDATED', reason)
    if count:
        transaction.on_commit(lambda: observe('operation_invalidated', count=count))
    return count


def digest_bindings(operation):
    result = {'organization_id': operation.organization_id,
            'conversation_id': operation.conversation_id, 'contact_id': operation.contact_id,
            'owner_id': operation.owner_id, 'pet_id': operation.pet_id,
            'appointment_id': operation.appointment_id,
            'expected_state': operation.preconditions.get('expected_state'),
            'clinic_timezone': operation.preconditions.get('clinic_timezone')}
    if operation.preconditions.get('schema') in (2, 3):
        result['appointment_snapshot'] = operation.preconditions.get('appointment_snapshot')
    if operation.preconditions.get('schema') == 3:
        result['attendance_contract'] = operation.preconditions.get('attendance_contract')
    if operation.preconditions.get('schema') == 4:
        result['registration_contract'] = operation.preconditions.get('registration_contract')
        result['owner_snapshot'] = operation.preconditions.get('owner_snapshot')
    return result


def _appointment_state(appointment):
    return {'status': appointment.status, 'date': appointment.date.isoformat(),
            'start_time': appointment.start_time.isoformat(timespec='minutes'),
            'end_time': appointment.end_time.isoformat(timespec='minutes'),
            'veterinarian_id': appointment.veterinarian_id, 'pet_id': appointment.pet_id}


def _slot_vet(conversation, parameters, *, exclude_appointment_id=None):
    from apps.appointments.models import Appointment
    from .models import AgentSettings
    from .tools import _scheduling_vets
    from . import clinic_context
    day = datetime.fromisoformat(parameters['date']).date()
    start, end = parameters['start_time'], parameters['end_time']
    if not any(a <= start and end <= b for a, b in clinic_context.day_ranges(
            conversation.organization, day)):
        raise PreparationDenied('slot_unavailable')
    config = AgentSettings.objects.filter(organization_id=conversation.organization_id).first()
    for vet in _scheduling_vets(conversation.organization, config):
        if vet.organization_id != conversation.organization_id:
            continue
        if not Appointment.objects.for_organization(conversation.organization_id).filter(
                veterinarian=vet, date=day, status__in=('scheduled', 'confirmed', 'in_progress'),
                start_time__lt=end, end_time__gt=start).exclude(pk=exclude_appointment_id).exists():
            return vet
    raise PreparationDenied('slot_unavailable')


def definition_from_matter(conversation, goal, capability):
    """Only B6 supplies entity IDs and source-validated semantic parameters."""
    spec = OPERATIONS[capability]
    if goal.name != spec.goal or not binding.metadata(goal) or binding.metadata(goal)['unresolved']:
        raise PreparationDenied('matter_not_ready')
    required = ['owner']
    if spec.operation_kind != 'REGISTER_PET':
        required.append('pet')
    if spec.operation_kind in ('CANCEL_APPOINTMENT', 'RESCHEDULE_APPOINTMENT', 'CONFIRM_ATTENDANCE'):
        required.append('appointment')
    if not all(binding.trusted(goal, entity) for entity in required):
        raise PreparationDenied('binding_provenance_required')
    binding.validate_entities(goal, conversation, {})
    values = binding.values(goal)
    from apps.channels.models import Message
    sources = [binding.metadata(goal)['sources'][entity] for entity in required]
    sources.extend(entry['provenance'] for key, entry in goal.slots.items() if key in values)
    for source in sources:
        members = Message.objects.for_organization(conversation.organization_id).filter(
            pk=source['source_message_id'], conversation=conversation, direction='in')
        if source.get('source_turn_work_id'):
            members = members.filter(turn_work_id=source['source_turn_work_id'])
        if not members.exists():
            raise PreparationDenied('provenance_message_scope')
    params = {}
    preconditions = {'schema': 1, 'clinic_timezone': conversation.organization.timezone,
                     'labels': {}}
    if goal.bound_pet_id:
        preconditions['labels']['pet'] = goal.bound_pet.name
    if 'appointment' in required:
        appointment = goal.bound_appointment
        if appointment.status not in ('scheduled', 'confirmed'):
            raise PreparationDenied('appointment_not_mutable')
        params['appointment_id'] = appointment.pk
        preconditions['expected_state'] = _appointment_state(appointment)
        if spec.operation_kind in ('RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT', 'CONFIRM_ATTENDANCE'):
            from apps.appointments.mutations import appointment_snapshot
            preconditions['schema'] = 2
            preconditions['appointment_snapshot'] = appointment_snapshot(appointment)
            if spec.operation_kind == 'CONFIRM_ATTENDANCE':
                if appointment.status != 'scheduled':
                    raise PreparationDenied('appointment_not_mutable')
                preconditions.update(schema=3, attendance_contract=1)
        preconditions['labels']['original_veterinarian'] = (
            appointment.veterinarian.get_full_name() or appointment.veterinarian.username
            if appointment.veterinarian_id else 'sin asignar')
    if spec.operation_kind in ('CREATE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'):
        # B6 date/time represent the target, including corrections to reschedule.
        day, start = values.get('date'), values.get('time')
        observed = values.get('selected_slot')
        provenance = goal.slots.get('selected_slot', {}).get('provenance', {})
        if (not isinstance(observed, dict) or observed.get('available') is not True
                or observed.get('date') != day or observed.get('time') != start
                or provenance.get('source_type') != 'TOOL_RESULT'
                or provenance.get('tool') != 'check_appointment_slot'
                or not provenance.get('observed_at')):
            raise PreparationDenied('exact_slot_observation_required')
        params.update(date=day, start_time=start, end_time=observed.get('end_time'))
        # Validate time syntax before querying the domain.
        probe = {**params, 'veterinarian_id': 1}
        if spec.operation_kind == 'CREATE_APPOINTMENT':
            params.update(pet_id=goal.bound_pet_id, reason=values.get('reason') or values.get('service'))
            probe.update(pet_id=params['pet_id'], reason=params['reason'])
        canonicalize(spec.operation_kind, probe)
        vet = _slot_vet(conversation, params, exclude_appointment_id=(
            goal.bound_appointment_id if spec.operation_kind == 'RESCHEDULE_APPOINTMENT' else None))
        params['veterinarian_id'] = vet.pk
        preconditions['labels']['veterinarian'] = vet.get_full_name() or vet.username
        preconditions['slot_observation'] = {k: provenance.get(k) for k in
            ('source_message_id', 'source_turn_work_id', 'tool_execution_id', 'observed_at')}
    elif spec.operation_kind == 'CONFIRM_ATTENDANCE':
        params['target_status'] = 'confirmed'
    elif spec.operation_kind == 'CANCEL_APPOINTMENT':
        if values.get('reason'):
            params['cancellation_reason'] = values['reason']
    elif spec.operation_kind == 'REGISTER_PET':
        from apps.patients.creation import owner_snapshot, validate_fields
        from datetime import date
        if goal.bound_pet_id or goal.bound_appointment_id or goal.bound_owner.is_generic:
            raise PreparationDenied('registration_scope')
        params = {'owner_id': goal.bound_owner_id, 'name': values.get('pet_name')}
        for field, slot in (('species', 'pet_species'), ('birth_date', 'pet_birth_date')):
            if values.get(slot):
                params[field] = values[slot]
        for slot in ('pet_name', 'pet_species', 'pet_birth_date'):
            if values.get(slot) and goal.slots[slot]['provenance']['source_type'] not in (
                    'USER_EXPLICIT', 'USER_CORRECTION'):
                raise PreparationDenied('explicit_pet_data_required')
        params = canonicalize(spec.operation_kind, params)
        fields = {key: value for key, value in params.items() if key != 'owner_id'}
        if 'birth_date' in fields:
            fields['birth_date'] = date.fromisoformat(fields['birth_date'])
        from rest_framework.exceptions import ValidationError
        try:
            if validate_fields(fields, conversation.organization) != fields:
                raise PreparationDenied('noncanonical_pet_data')
        except ValidationError as exc:
            raise PreparationDenied('invalid_pet_data') from exc
        preconditions.update(schema=4, registration_contract=1,
            owner_snapshot=owner_snapshot(goal.bound_owner))
    return canonicalize(spec.operation_kind, params), preconditions


def _stale_reason(operation, conversation, goal):
    from .models import ConversationGoal, HumanHandoff
    if HumanHandoff.objects.for_organization(conversation.organization_id).filter(
            conversation=conversation, resolved_at__isnull=True).exists():
        return 'human_handoff'
    if not goal or goal.status not in ConversationGoal.FOREGROUND_STATUSES:
        return 'matter_inactive'
    capability = operation.permission_snapshot['capability']
    if goal.name != OPERATIONS[capability].goal:
        return 'matter_changed'
    if operation.binding_revision != goal.binding_revision:
        return 'binding_changed'
    if (operation.owner_id, operation.pet_id, operation.appointment_id) != (
            goal.bound_owner_id, goal.bound_pet_id, goal.bound_appointment_id):
        return 'entity_changed'
    if operation.identity_revision != conversation.contact.authorization_revision:
        return 'identity_changed'
    if operation.ownership_epoch != conversation.ownership_epoch:
        return 'ownership_changed'
    if actor_permission(conversation, goal, capability).result != 'ALLOWED_TO_PROPOSE':
        return 'permission_changed'
    if operation.parameters_digest != digest(operation.operation_kind, operation.parameters,
            version=operation.parameters_schema_version, bindings=digest_bindings(operation)):
        observe('digest_schema_validation_failure')
        return 'definition_corrupted'
    if operation.appointment_id:
        if operation.preconditions.get('schema') in (2, 3):
            from apps.appointments.mutations import appointment_snapshot
            if appointment_snapshot(operation.appointment) != operation.preconditions.get('appointment_snapshot'):
                return 'appointment_changed'
        if _appointment_state(operation.appointment) != operation.preconditions.get('expected_state'):
            return 'appointment_changed'
        old = operation.preconditions['expected_state']
        original_time = datetime.fromisoformat(old['date'] + 'T' + old['start_time']).replace(
            tzinfo=ZoneInfo(operation.preconditions['clinic_timezone']))
        if original_time <= timezone.now():
            return 'appointment_elapsed'
    try:
        current_params, current_preconditions = definition_from_matter(conversation, goal, capability)
        current_bindings = {**digest_bindings(operation),
            'expected_state': current_preconditions.get('expected_state'),
            'clinic_timezone': current_preconditions['clinic_timezone']}
        if operation.preconditions.get('schema') in (2, 3):
            current_bindings['appointment_snapshot'] = current_preconditions.get('appointment_snapshot')
        if operation.preconditions.get('schema') == 4:
            current_bindings['owner_snapshot'] = current_preconditions.get('owner_snapshot')
            current_bindings['registration_contract'] = current_preconditions.get('registration_contract')
        if digest(operation.operation_kind, current_params, bindings=current_bindings) != operation.parameters_digest:
            return 'definition_changed'
    except (PreparationDenied, InvalidParameters, ValueError):
        return 'preconditions_changed'
    if operation.parameters.get('date'):
        params = operation.parameters
        target = datetime.fromisoformat(params['date'] + 'T' + params['start_time']).replace(
            tzinfo=ZoneInfo(operation.preconditions['clinic_timezone']))
        if target <= timezone.now():
            return 'schedule_elapsed'
    return None


def revalidate(operation):
    """Persist expiry/staleness under the same preparation locks; no consent."""
    from .models import Conversation, ContactIdentity, ConversationGoal, ConversationOperation
    with transaction.atomic():
        conv = Conversation.all_objects.select_for_update().get(
            pk=operation.conversation_id, organization_id=operation.organization_id)
        conv.contact = ContactIdentity.all_objects.select_for_update().get(
            pk=conv.contact_id, organization_id=conv.organization_id)
        goal = ConversationGoal.objects.select_for_update().filter(
            pk=operation.goal_id, organization_id=conv.organization_id, conversation=conv).first()
        operation = ConversationOperation.objects.select_for_update().get(
            pk=operation.pk, organization_id=conv.organization_id)
        if operation.consent_state != 'PENDING':
            return operation
        reason = _stale_reason(operation, conv, goal)
        state = 'INVALIDATED' if reason else ('EXPIRED' if operation.expires_at <= timezone.now() else None)
        if state:
            ConversationOperation.objects.filter(pk=operation.pk, organization_id=conv.organization_id).retire_pending(
                state, reason or 'ttl_elapsed')
            operation.refresh_from_db()
            transaction.on_commit(lambda: observe('operation_expired' if state == 'EXPIRED' else 'operation_invalidated'))
        return operation


def prepare_operation(*, witness, goal_id, capability, expected_binding_revision, expected_identity_revision):
    """No trusted arguments from LLM. Recovery must hold a new valid B3 witness."""
    from . import durable
    from .models import ContactIdentity, ConversationGoal, ConversationOperation, HumanHandoff
    spec = OPERATIONS.get(capability)
    if not spec or not spec.operation_kind:
        raise PreparationDenied('unsupported_capability')
    with transaction.atomic():
        conv, work = durable.lock_witness(witness)
        contact = ContactIdentity.all_objects.select_for_update().get(
            pk=conv.contact_id, organization_id=conv.organization_id)
        conv.contact = contact
        context = durable.context_for_work(witness)
        if durable.has_new_input(work):
            raise PreparationDenied('new_input')
        if contact.authorization_revision != expected_identity_revision:
            raise PreparationDenied('identity_revision_stale')
        goal = ConversationGoal.objects.select_for_update().get(
            pk=goal_id, conversation=conv, organization_id=conv.organization_id)
        goal.conversation = conv
        if goal.binding_revision != expected_binding_revision:
            observe('stale_binding_rejected')
            raise PreparationDenied('binding_revision_stale')
        if goal.status not in ConversationGoal.FOREGROUND_STATUSES:
            raise PreparationDenied('matter_inactive')
        if HumanHandoff.objects.for_organization(conv.organization_id).filter(
                conversation=conv, resolved_at__isnull=True).exists():
            raise PreparationDenied('human_handoff')
        permission = actor_permission(conv, goal, capability)
        if permission.result != 'ALLOWED_TO_PROPOSE':
            observe({'REQUIRES_IDENTITY': 'permission_requires_identity',
                     'REQUIRES_STEP_UP': 'permission_requires_step_up'}.get(permission.result, 'permission_denied'))
            raise PreparationDenied(permission.result)
        try:
            params, preconditions = definition_from_matter(conv, goal, capability)
        except InvalidParameters:
            observe('digest_schema_validation_failure')
            raise
        candidate = ConversationOperation(organization_id=conv.organization_id,
            conversation=conv, contact=contact, source_turn=work, source_message_id=context.anchor.message_id,
            stage_key=STAGE_KEY, goal=goal, operation_kind=spec.operation_kind,
            authorization_mode=spec.authorization_mode, parameters=params,
            preconditions=preconditions, permission_snapshot=permission.evidence,
            owner_id=goal.bound_owner_id, pet_id=goal.bound_pet_id, appointment_id=goal.bound_appointment_id,
            binding_revision=goal.binding_revision, identity_revision=contact.authorization_revision,
            ownership_epoch=witness.ownership_epoch, expires_at=timezone.now() + TTL)
        candidate.parameters_digest = digest(spec.operation_kind, params, bindings=digest_bindings(candidate))
        stale = _stale_reason(candidate, conv, goal)
        if stale:
            raise PreparationDenied(stale)
        existing = ConversationOperation.objects.for_organization(conv.organization_id).filter(
            source_turn=work, stage_key=STAGE_KEY).first()
        if existing:
            if (existing.parameters_digest != candidate.parameters_digest or existing.goal_id != goal.pk
                    or existing.binding_revision != goal.binding_revision
                    or existing.identity_revision != contact.authorization_revision):
                raise PreparationDenied('causal_payload_conflict')
            # Never revive invalidated or expired operations on retry.
            existing = revalidate(existing)
            if existing.consent_state != 'PENDING':
                raise PreparationDenied('causal_operation_retired')
            transaction.on_commit(lambda: observe('operation_reused'))
            return existing
        previous = ConversationOperation.objects.for_organization(conv.organization_id).filter(
            conversation=conv, goal=goal).order_by('-pk').first()
        if previous:
            invalidate_pending(organization_id=conv.organization_id, goal_id=goal.pk, reason='replaced')
            candidate.replaces = ConversationOperation.objects.get(pk=previous.pk)
        token = _preparing.set(True)
        try:
            candidate.save(force_insert=True)
        finally:
            _preparing.reset(token)
        # Includes lease expiry during local preparation; row locks alone do
        # not extend a B3 witness. A failure rolls back replacement and INSERT.
        durable.check_turn_deadline(witness)
        # Reference only. No duplicate parameters, legacy consent, or Message emission.
        flow = dict(conv.flow or {})
        flow.pop('pending_action', None)
        flow['conversation_operation_key'] = str(candidate.operation_key)
        type(conv).objects.filter(pk=conv.pk, organization_id=conv.organization_id).update(flow=flow)
        transaction.on_commit(lambda: observe('operation_replaced' if previous else 'operation_created'))
        return candidate


def prepare_current(witness):
    """Planner/B3 adapter, after B6 publication. Incomplete matters stay incomplete."""
    from .models import Conversation, ConversationGoal
    conv = Conversation.objects.select_related('contact').get(
        pk=witness.conversation_id, organization_id=witness.organization_id)
    goal = ConversationGoal.objects.for_organization(conv.organization_id).filter(
        conversation=conv, status__in=ConversationGoal.FOREGROUND_STATUSES).first()
    if not goal:
        return None
    capability = next((name for name, spec in OPERATIONS.items() if spec.goal == goal.name), None)
    if not capability:
        return None
    # A side question/READ does not replace a still-current exact definition.
    # This lookup is continuation, never causal preparation idempotency.
    pending = current_pending(organization_id=conv.organization_id,
        conversation_id=conv.pk, goal_id=goal.pk)
    if pending:
        return pending
    from .models import ConversationOperation
    if ConversationOperation.objects.filter(organization_id=conv.organization_id, conversation=conv,
            goal=goal, consent_state__in=('AUTHORIZED', 'REJECTED'),
            binding_revision=goal.binding_revision, identity_revision=conv.contact.authorization_revision,
            ownership_epoch=conv.ownership_epoch).exists():
        # A completed consent decision is not a request for another proposal.
        return None
    try:
        return prepare_operation(witness=witness, goal_id=goal.pk, capability=capability,
            expected_binding_revision=goal.binding_revision,
            expected_identity_revision=conv.contact.authorization_revision)
    except (PreparationDenied, InvalidParameters):
        return None


def by_key(*, organization_id, conversation_id, operation_key):
    from .models import ConversationOperation
    return ConversationOperation.objects.for_organization(organization_id).filter(
        conversation_id=conversation_id, operation_key=operation_key).first()


def for_matter(*, organization_id, goal_id):
    from .models import ConversationOperation
    return ConversationOperation.objects.for_organization(organization_id).filter(goal_id=goal_id).order_by('pk')


def current_pending(*, organization_id, conversation_id, goal_id):
    operation = for_matter(organization_id=organization_id, goal_id=goal_id).filter(
        conversation_id=conversation_id, consent_state='PENDING').first()
    if operation:
        operation = revalidate(operation)
        return operation if operation.consent_state == 'PENDING' else None
    return None


def render(operation):
    """Deterministic definition text. Rendering never means Message emission."""
    p, pre = operation.parameters, operation.preconditions
    pet = pre['labels'].get('pet', '')
    old = pre.get('expected_state', {})
    if pre.get('schema') in (2, 3):
        # Preserve v1 rendering verbatim. New proposals also expose any original
        # sub-minute precision accepted by the human API, without truncation.
        old = {**old, **{key: pre['appointment_snapshot'][key]
                       for key in ('date', 'start_time', 'end_time')}}
        old['start_time'] = old['start_time'].removesuffix(':00')
        old['end_time'] = old['end_time'].removesuffix(':00')
    original = (f"{pet}, {old.get('date')} {old.get('start_time')}–{old.get('end_time')}"
                f" ({pre['clinic_timezone']}), veterinario {pre['labels'].get('original_veterinarian', 'sin asignar')}")
    kind = operation.operation_kind
    if kind in ('CREATE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'):
        target = f"{p['date']} {p['start_time']}–{p['end_time']} ({pre['clinic_timezone']}), veterinario {pre['labels']['veterinarian']}"
        if kind == 'CREATE_APPOINTMENT':
            return f"Agendar cita para {pet}: {target}; motivo: {p['reason']}."
        return f"Reprogramar {original} a {target}."
    if kind == 'CANCEL_APPOINTMENT':
        reason = f" Motivo: {p['cancellation_reason']}." if p.get('cancellation_reason') else ''
        return f"Cancelar {original}." + reason
    if kind == 'CONFIRM_ATTENDANCE':
        if pre.get('schema') == 3:
            return (f"Confirmar que asistirás a la cita de {original}; "
                    f"referencia {pre['appointment_snapshot']['public_id']}.")
        return f"Confirmar asistencia: {original}; estado: confirmed."
    if pre.get('schema') == 4:
        return (f"Registrar mascota {p['name']} para el propietario {pre['owner_snapshot']['name']}; "
            f"especie: {p.get('species', 'pendiente (no proporcionada)')}; "
            f"nacimiento: {p.get('birth_date', 'desconocido (no proporcionado)')}; "
            'sexo: desconocido; raza y color: sin especificar. Solo se registra la mascota.')
    text = f"Registrar mascota {p['name']} en tu expediente; especie: {p.get('species', 'sin especificar')}."
    if p.get('birth_date'):
        text += f" Nacimiento: {p['birth_date']}."
    return text
