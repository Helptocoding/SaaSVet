"""B6: bounded semantic dependencies, causal provenance and atomic corrections.

No authorization, operations, generic entity framework or dependency engine.
All trusted writers pass this boundary; legacy slots remain diagnostic only.
"""
import copy
import logging
from contextlib import contextmanager

from django.db import transaction

from .turn_changes import current_changes, local_or_locked_conversation, save_local

logger = logging.getLogger('agent.events')
SCHEMA = 1
SOURCE_TYPES = frozenset({'USER_EXPLICIT', 'USER_CORRECTION', 'TOOL_RESULT',
                          'DERIVED', 'SYSTEM_DEFAULT'})
ENTITY_FIELDS = {'owner': 'bound_owner_id', 'pet': 'bound_pet_id',
                 'appointment': 'bound_appointment_id'}
BASE_FIELDS = frozenset({'owner', 'pet', 'appointment', 'date', 'time', 'service', 'reason'})
# Conservative endpoint dependencies. Explicit date/service/time are independent.
DEPENDENCY_RULES = {
    'owner': {'pet', 'appointment', 'pet_handle', 'appointment_handle',
              'appointment_candidates', 'vaccine_facts', 'personal_facts',
              'availability', 'selected_slot', 'appointment_facts'},
    'pet': {'appointment', 'pet_handle', 'appointment_handle',
            'appointment_candidates', 'vaccine_facts', 'personal_facts',
            'availability', 'selected_slot', 'appointment_facts'},
    'appointment': {'appointment_handle', 'appointment_facts', 'availability',
                    'selected_slot'},
    'date': {'availability', 'selected_slot'},
    'time': {'selected_slot'},
    'service': {'availability', 'selected_slot', 'price', 'service_facts'},
    'reason': {'availability', 'selected_slot', 'price', 'service_facts'},
}
SLOT_DEPENDENCIES = {
    'appointment_candidates': ('owner', 'pet'),
    'appointment_facts': ('owner', 'pet', 'appointment'),
    'vaccine_facts': ('owner', 'pet'), 'personal_facts': ('owner', 'pet'),
    'availability': ('owner', 'pet', 'appointment', 'date', 'service', 'reason'),
    'selected_slot': ('owner', 'pet', 'appointment', 'date', 'time', 'service', 'reason'),
    'price': ('service', 'reason'), 'service_facts': ('service', 'reason'),
    'pet_handle': ('owner', 'pet'),
    'appointment_handle': ('owner', 'pet', 'appointment'),
}
TOOL_SLOTS = {'get_appointments': 'appointment_candidates',
              'get_vaccine_status': 'vaccine_facts',
              'find_available_slots': 'availability',
              'check_appointment_slot': 'selected_slot'}
PERSONAL_TOOLS = frozenset({'list_my_pets', 'get_appointments', 'get_vaccine_status',
                            'get_recent_product_queries'})


class BindingConflict(ValueError):
    """Caller must re-read/replan; never overwrite the winning revision."""


def observe(event, *, count=1):
    # Bounded event/field codes only: no entity IDs, names, message text or phone.
    logger.info('AGENT_B6_%s', event.upper(), extra={
        'event': 'AGENT_B6_' + event.upper(), 'count': count, 'schema': SCHEMA})


def metadata(goal):
    data = (goal.working_state or {}).get('binding', {})
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        return {}
    if (not isinstance(data.get('revisions'), dict)
            or not all(k in BASE_FIELDS and type(v) is int and v >= 0
                       for k, v in data['revisions'].items())
            or not isinstance(data.get('sources'), dict)
            or not all(k in ENTITY_FIELDS and isinstance(v, dict)
                       and v.get('schema') == SCHEMA
                       and v.get('source_type') in SOURCE_TYPES
                       and type(v.get('source_message_id')) is int
                       and isinstance(v.get('dependencies'), dict)
                       for k, v in data['sources'].items())
            or not isinstance(data.get('unresolved'), list)
            or not all(isinstance(k, str) for k in data['unresolved'])):
        return {}
    return data


def snapshot(goal):
    return {'schema': SCHEMA, 'goal_id': goal.pk, 'kind': goal.name,
            'organization_id': goal.organization_id,
            'conversation_id': goal.conversation_id,
            'contact_id': goal.conversation.contact_id,
            'binding_revision': goal.binding_revision,
            **{key: getattr(goal, attr) for key, attr in ENTITY_FIELDS.items()}}


def source(goal, context, message_id, source_type, dependencies=(), *, tool=None):
    context.assert_scope(goal.conversation)
    if source_type not in SOURCE_TYPES or message_id not in context.inbound_ids:
        raise ValueError('B6 source requires a real member of TurnContext')
    revisions = metadata(goal).get('revisions', {})
    changes = current_changes()
    return {'schema': SCHEMA, 'source_type': source_type,
            'source_message_id': message_id,
            'source_event_id': message_id,
            'source_turn_anchor': context.anchor.message_id,
            'source_turn_work_id': changes.witness.turn_work_id if changes else None,
            'binding_revision': goal.binding_revision,
            'validated_revision': goal.binding_revision,
            'scope': snapshot(goal),
            'dependencies': {key: revisions.get(key, 0) for key in dependencies},
            'tool': tool}


def valid_provenance(goal, provenance):
    if not isinstance(provenance, dict) or provenance.get('schema') != SCHEMA:
        return False
    data = metadata(goal)
    scope, deps = provenance.get('scope'), provenance.get('dependencies')
    if (not data or provenance.get('source_type') not in SOURCE_TYPES
            or type(provenance.get('source_message_id')) is not int
            or provenance['source_message_id'] <= 0
            or provenance.get('source_event_id') != provenance['source_message_id']
            or type(provenance.get('source_turn_anchor')) is not int
            or type(provenance.get('binding_revision')) is not int
            or not 0 <= provenance['binding_revision'] <= goal.binding_revision
            or provenance.get('validated_revision') != goal.binding_revision
            or not isinstance(scope, dict) or not isinstance(deps, dict)):
        return False
    if any(scope.get(k) != v for k, v in snapshot(goal).items()
           if k in ('goal_id', 'organization_id', 'conversation_id', 'contact_id', 'kind')):
        return False
    return all(key in BASE_FIELDS and type(revision) is int and revision == data['revisions'].get(key, 0)
               and (key not in ENTITY_FIELDS or scope.get(key) == getattr(goal, ENTITY_FIELDS[key]))
               for key, revision in deps.items())


def values(goal):
    result = {}
    for key, entry in (goal.slots or {}).items():
        if (isinstance(entry, dict) and entry.get('status') == 'valid'
                and valid_provenance(goal, entry.get('provenance'))):
            if entry.get('value') is not None:
                result[key] = entry['value']
    return result


def trusted(goal, entity):
    return (getattr(goal, ENTITY_FIELDS[entity]) is not None
            and valid_provenance(goal, metadata(goal).get('sources', {}).get(entity)))


def validate_entities(goal, conversation, updates):
    from apps.patients.models import Owner, Pet
    from apps.appointments.models import Appointment
    from . import identity
    if (goal.organization_id != conversation.organization_id
            or goal.conversation_id != conversation.pk):
        raise ValueError('B6 cross-scope goal')
    owner = updates.get('owner', goal.bound_owner_id)
    pet = updates.get('pet', goal.bound_pet_id)
    appointment = updates.get('appointment', goal.bound_appointment_id)
    if owner is not None and (not identity.is_verification_current(conversation.contact)
            or owner != conversation.contact.owner_id
            or not Owner.objects.filter(pk=owner, organization_id=goal.organization_id).exists()):
        raise ValueError('B6 owner outside current identity')
    if pet is not None and not Pet.objects.filter(
            pk=pet, organization_id=goal.organization_id, owner_id=owner).exists():
        raise ValueError('B6 pet outside owner/tenant')
    if appointment is not None and (pet is None or not Appointment.objects.filter(
            pk=appointment, organization_id=goal.organization_id,
            pet_id=pet, pet__owner_id=owner).exists()):
        raise ValueError('B6 appointment outside pet/owner/tenant')


@contextmanager
def edit(goal, conversation, expected_revision):
    """B3 stages changes; direct callers lock and CAS in one short transaction."""
    from .models import ConversationGoal
    if current_changes() is not None:
        current_changes().scope(goal)
        if goal.binding_revision != expected_revision:
            raise BindingConflict('B6 revision changed')
        yield goal, conversation
        return
    with transaction.atomic():
        locked_conversation = local_or_locked_conversation(conversation)
        locked = ConversationGoal.objects.select_for_update().get(
            pk=goal.pk, organization_id=conversation.organization_id,
            conversation_id=conversation.pk)
        if locked.binding_revision != expected_revision:
            raise BindingConflict('B6 revision changed')
        yield locked, locked_conversation
    goal.refresh_from_db()
    conversation.flow = locked_conversation.flow


def change(goal, conversation, updates, *, context, message_id,
           expected_revision, correction=False, unresolved=()):
    """Replace base values, invalidate dependent values and legacy pending atomically.

    Omission means preserve. An explicit None means remove/unresolve.
    Entity IDs are server resolved, never accepted from a model's JSON.
    """
    from . import confirmations, goals
    from .turn_context import messages_for_turn
    messages_for_turn(conversation, context)
    if not set(updates).issubset(BASE_FIELDS) or not set(unresolved).issubset(BASE_FIELDS):
        raise ValueError('B6 unknown base field')
    if message_id not in context.inbound_ids:
        raise ValueError('B6 non-causal correction')
    with edit(goal, conversation, expected_revision) as (target, conv):
        updates = dict(updates)
        prior = metadata(target)
        changed = {key for key, value in updates.items()
                   if (getattr(target, ENTITY_FIELDS[key]) if key in ENTITY_FIELDS
                       else values(target).get(key)) != value}
        # Recapture a legacy value is a semantic change even if the raw ID matches.
        changed.update(k for k in updates if k in ENTITY_FIELDS and not trusted(target, k))
        changed.update(set(unresolved) - set(prior.get('unresolved', ())))
        if not changed and prior:
            return target
        for field in ('owner', 'pet'):
            if field in changed:
                for dependent in ('pet', 'appointment') if field == 'owner' else ('appointment',):
                    if dependent not in updates:
                        updates[dependent] = None
                        changed.add(dependent)
        validate_entities(target, conv, updates)
        appointment_evidence = None
        if updates.get('appointment') is not None and 'appointment' in changed:
            if updates['appointment'] not in appointment_candidates(target, conv):
                raise ValueError('B6 appointment requires a current compatible tool candidate')
            appointment_evidence = copy.deepcopy(target.slots['appointment_candidates']['provenance'])
        data = copy.deepcopy(prior) if prior else {
            'schema': SCHEMA, 'revisions': {}, 'sources': {},
            'unresolved': [], 'invalidations': []}
        target.binding_revision += 1
        for field in changed:
            data['revisions'][field] = data['revisions'].get(field, 0) + 1
        data['unresolved'] = sorted((set(data['unresolved']) - set(updates)) | set(unresolved))
        data['last_event_id'] = message_id
        data['last_change_is_correction'] = correction
        event = next(event for event in context.events if event.message_id == message_id)
        data['last_event_cursor'] = [event.created_at.isoformat(), message_id]
        # Exclude private historical text after any semantic correction. Explicit
        # independent slots already have their own provenance and remain projected.
        if correction or changed & set(ENTITY_FIELDS):
            data['history_floor'] = message_id
            data['history_floor_cursor'] = data['last_event_cursor']
        target.working_state = {**(target.working_state or {}), 'binding': data}
        for field, attr in ENTITY_FIELDS.items():
            if field in updates:
                setattr(target, attr, updates[field])
        invalidated = []
        forced = set().union(*(DEPENDENCY_RULES.get(k, set()) for k in changed))
        for key, entry in (target.slots or {}).items():
            if not isinstance(entry, dict):
                continue
            prov = entry.get('provenance')
            deps = prov.get('dependencies', {}) if isinstance(prov, dict) else {}
            if not prov or key in forced or set(deps) & changed:
                entry['status'] = 'invalidated'
                invalidated.append(key)
            else:
                # Explicit revalidation of independent evidence; calculation
                # revision is retained, never fabricated as a new tool result.
                prov['validated_revision'] = target.binding_revision
        for entity, prov in list(data['sources'].items()):
            if entity in changed or set(prov.get('dependencies', {})) & changed:
                data['sources'].pop(entity)
            else:
                prov['validated_revision'] = target.binding_revision
        source_type = 'USER_CORRECTION' if correction else 'USER_EXPLICIT'
        for key, value in updates.items():
            if value is None:
                target.slots.pop(key, None)
                continue
            deps = {'owner': ('owner',), 'pet': ('owner', 'pet'),
                    'appointment': ('owner', 'pet', 'appointment')}.get(key, ())
            prov = source(target, context, message_id,
                          'DERIVED' if key == 'owner' else source_type, deps)
            if key == 'owner':
                prov['basis'] = 'current_verified_contact'
            if key == 'appointment' and appointment_evidence:
                prov['candidate_evidence'] = appointment_evidence
            if key in ENTITY_FIELDS:
                data['sources'][key] = prov
            else:
                target.slots[key] = {'value': value, 'confidence': 1.0,
                                     'status': 'valid', 'provenance': prov}
        data['invalidations'] = (data['invalidations'] + [
            {'revision': target.binding_revision, 'fields': sorted(invalidated),
             'source_message_id': message_id}])[-16:]
        target.low_confidence = []
        target.missing = goals.missing_slots(target)
        target.return_to = next(iter(target.missing or data['unresolved']), 'matter')
        # Both writes belong to this transaction / B3 publication. A DB failure
        # here rolls back revision too, rather than leaving confirmable old args.
        confirmations.supersede_pending(conv, reason='binding_changed')
        save_local(target, update_fields=['binding_revision', 'bound_owner', 'bound_pet',
                    'bound_appointment', 'slots', 'working_state', 'missing', 'low_confidence', 'return_to'])
        observe('binding_unresolved' if unresolved else 'binding_changed')
        if invalidated:
            observe('invalidation_count', count=len(invalidated))
    return goal


def record_derived(goal, conversation, key, value, *, context, message_id,
                   expected_snapshot, source_type='TOOL_RESULT', tool=None, dependencies=None,
                   tool_execution_id=None, observed_at=None):
    from .turn_context import messages_for_turn
    messages_for_turn(conversation, context)
    if expected_snapshot != snapshot(goal):
        observe('stale_slot_rejected')
        raise BindingConflict('B6 stale result')
    deps = SLOT_DEPENDENCIES.get(key) if dependencies is None else tuple(dependencies)
    if (key not in SLOT_DEPENDENCIES and key not in BASE_FIELDS
            or deps is None or not set(deps).issubset(BASE_FIELDS)
            or source_type not in ('TOOL_RESULT', 'DERIVED', 'SYSTEM_DEFAULT')):
        raise ValueError('B6 unknown derived slot/dependency contract')
    with edit(goal, conversation, expected_snapshot['binding_revision']) as (target, conv):
        if snapshot(target) != expected_snapshot:
            raise BindingConflict('B6 stale result scope')
        target.slots = copy.deepcopy(target.slots or {})
        provenance = source(target, context, message_id, source_type, deps, tool=tool)
        if source_type == 'TOOL_RESULT':
            provenance['tool_execution_id'] = tool_execution_id
            provenance['observed_at'] = observed_at.isoformat() if observed_at else None
        target.slots[key] = {'value': value, 'confidence': 1.0, 'status': 'valid',
                            'provenance': provenance}
        save_local(target, update_fields=['slots'])


def current_goal(conversation):
    from . import goals
    goal = goals.get_open_goal(conversation)
    return goal if goal and goal.name not in goals.IDENTITY_GOALS else None


def projection(conversation):
    goal = current_goal(conversation)
    if goal is None:
        return None
    data = metadata(goal)
    try:
        validate_entities(goal, conversation, {})
    except ValueError:
        return {'kind': goal.name, 'binding_revision': goal.binding_revision,
                'bindings': {key: None for key in ENTITY_FIELDS}, 'slots': {},
                'unresolved': ['owner'], 'schema': SCHEMA}
    return {'kind': goal.name, 'binding_revision': goal.binding_revision,
            'bindings': {k: getattr(goal, attr) if trusted(goal, k) else None
                         for k, attr in ENTITY_FIELDS.items()},
            'slots': values(goal), 'unresolved': data.get('unresolved', ['binding']),
            'schema': SCHEMA}


def outcome_current(conversation, outcome):
    stamp = outcome.scope.get('binding')
    if stamp is None:
        return True  # public outcomes and B2 errors carry no entity context
    goal = current_goal(conversation)
    if goal is None or stamp != snapshot(goal):
        observe('stale_slot_rejected')
        return False
    from .models import ConversationGoal
    changes = current_changes()
    expected_db_revision = (changes.binding_revisions.get(goal.pk)
                            if changes else stamp['binding_revision'])
    if expected_db_revision is not None:
        if not ConversationGoal.objects.filter(pk=goal.pk,
                binding_revision=expected_db_revision).exists():
            observe('stale_slot_rejected')
            return False
    return True


def appointment_candidates(goal, conversation):
    from apps.appointments.models import Appointment
    from . import tools
    entry = (goal.slots or {}).get('appointment_candidates', {})
    prov = entry.get('provenance', {})
    if (not trusted(goal, 'pet') or not valid_provenance(goal, prov)
            or prov.get('source_type') != 'TOOL_RESULT' or prov.get('tool') != 'get_appointments'
            or entry.get('status') != 'valid'):
        return []
    refs = [tools.resolve_handle(conversation, row.get('handle'))
            for row in entry.get('value', []) if isinstance(row, dict)]
    return list(Appointment.objects.filter(organization_id=conversation.organization_id,
        pet_id=goal.bound_pet_id, pet__owner_id=goal.bound_owner_id,
        public_id__in=[ref for ref in refs if ref]).values_list('pk', flat=True))


def guard_arguments(conversation, name, args, *, context=None):
    """Validate candidates against current entity authority before any HTTP."""
    from . import tools
    goal = current_goal(conversation)
    sensitive = name in PERSONAL_TOOLS or name in TOOL_SLOTS
    if not sensitive:
        return dict(args), None, None
    if goal is None:
        if context is not None and name == 'get_vaccine_status':
            return {}, None, 'binding_required'
        return dict(args), None, None
    if not metadata(goal):
        if name in PERSONAL_TOOLS:
            observe('legacy_binding_rejected')
            return {}, None, 'binding_required'
        return dict(args), None, None
    changes = current_changes()
    if changes and goal.pk in changes.binding_revisions:
        from .models import ConversationGoal
        if not ConversationGoal.objects.filter(pk=goal.pk,
                binding_revision=changes.binding_revisions[goal.pk]).exists():
            observe('stale_slot_rejected')
            return {}, None, 'stale_binding'
    try:
        validate_entities(goal, conversation, {})
    except ValueError:
        return {}, None, 'binding_required'
    args = dict(args)
    if name in PERSONAL_TOOLS and not trusted(goal, 'owner'):
        return {}, None, 'binding_required'
    if name in ('get_vaccine_status', 'get_appointments'):
        if trusted(goal, 'pet'):
            from apps.patients.models import Pet
            pet = Pet.objects.get(pk=goal.bound_pet_id)
            supplied = args.get('pet_handle')
            if supplied and str(tools.resolve_handle(conversation, supplied)) != str(pet.public_id):
                observe('stale_slot_rejected')
                return {}, None, 'binding_required'
            args['pet_handle'] = tools._add_ref(conversation, 'mascota', pet.public_id)
            tools._save_refs(conversation)
        elif name == 'get_vaccine_status' or args.get('pet_handle'):
            return {}, None, 'binding_required'
        elif 'pet' in metadata(goal)['unresolved']:
            return {}, None, 'binding_required'
    active_values = values(goal)
    for key in ('date', 'time'):
        if name in ('find_available_slots', 'check_appointment_slot'):
            if key in args and args[key] != active_values.get(key):
                observe('stale_slot_rejected')
                return {}, None, 'binding_required'
    return args, snapshot(goal), None


def consume_outcome(conversation, name, outcome, stamp, *, context=None, tool_execution_id=None):
    from .tools import ToolOutcome
    if stamp is None or outcome.kind != 'READ':
        return outcome
    outcome.scope['binding'] = stamp
    if not outcome_current(conversation, outcome):
        return ToolOutcome(kind='ERROR', client_error='stale_binding', error_kind='conflict')
    if any(outcome.scope.get(key) != stamp[key]
           for key in ('organization_id', 'conversation_id', 'contact_id')):
        observe('stale_slot_rejected')
        return ToolOutcome(kind='ERROR', client_error='stale_binding', error_kind='conflict')
    if name in ('get_vaccine_status', 'get_appointments') and stamp['pet'] is not None:
        from apps.patients.models import Pet
        pet_ref = str(Pet.objects.get(pk=stamp['pet']).public_id)
        valid_pet_scope = (outcome.scope.get('pet') == pet_ref if name == 'get_vaccine_status'
                           else tuple(outcome.scope.get('pets', ())) == (pet_ref,))
        if not valid_pet_scope:
            observe('stale_slot_rejected')
            return ToolOutcome(kind='ERROR', client_error='stale_binding', error_kind='conflict')
    if not outcome.validated or context is None or not context.inbound_ids:
        return outcome
    slot = TOOL_SLOTS.get(name)
    if slot:
        goal = current_goal(conversation)
        try:
            record_derived(goal, conversation, slot, outcome.data, context=context,
                           message_id=context.anchor.message_id, expected_snapshot=stamp,
                           tool=name, tool_execution_id=tool_execution_id,
                           observed_at=outcome.observed_at)
        except BindingConflict:
            return ToolOutcome(kind='ERROR', client_error='stale_binding', error_kind='conflict')
    return outcome
