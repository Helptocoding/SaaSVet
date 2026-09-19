"""B6's deliberately small correction grammar; not historical reference resolution.

Only exact names of permitted candidates can become bindings. Language outside
this boundary stays unresolved; model confidence never establishes an entity.
"""
import re
import unicodedata
from datetime import timedelta

from django.db import transaction

from . import goals, matter_binding as binding
from .turn_changes import create_local, local_or_locked_conversation

OPERATION_PATTERNS = {
    goals.RESCHEDULE: r'\b(?:reprogram\w*|reagend\w*|mover|mueve\w*|cambiar?\s+la\s+cita)\b',
    goals.CANCEL: r'\bcancel\w*\b',
    goals.SCHEDULE: r'\b(?:agendar?\w*|quiero\s+(?:una\s+)?cita|necesito\s+(?:una\s+)?cita)\b',
    goals.ADD_PET_ONLY: r'\bregistr\w*\b',
}
CORRECTION = r'\b(?:mejor|perdon|quise decir|no es|no para|no es para|esa no|no esa|la otra)\b'
ABANDON = r'\b(?:olvida(?:lo|r)?(?:\s+(?:eso|la cita))?|dejalo|ya no quiero\s+(?:la\s+)?cita)\b'
PUBLIC = r'\b(?:precio|cuesta|costo|direccion|horario|abren|cierran|ubicacion)\b'
WEEKDAYS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')


def normalize(text):
    return ' '.join(re.sub(r'[^\w\s:-]', ' ', ''.join(
        c for c in unicodedata.normalize('NFD', text.casefold())
        if unicodedata.category(c) != 'Mn')).split())


def parse(text, pets=(), *, active=False, today=None):
    text = normalize(text)
    correction = bool(re.search(CORRECTION, text) or re.match(r'^no\b', text))
    abandon = bool(re.search(ABANDON, text))
    kinds = [kind for kind, pattern in OPERATION_PATTERNS.items() if re.search(pattern, text)]
    # 'reagendar' is its own verb; an explicit abandonment isn't a business cancel.
    if abandon and not re.search(r'\bcancel\w*\b', text):
        kinds = [k for k in kinds if k != goals.CANCEL]
    public = bool(re.search(PUBLIC, text)) and not kinds
    contextual = bool(kinds or correction or re.search(
        r'\b(?:para|mascota|cita|vacunas?|su ultima|tiene pendientes|es para)\b', text)
        or (active and len(text.split()) <= 3))
    matches = []
    negated = []
    if contextual and not public:
        for pet in pets:
            name = normalize(pet['name'])
            hits = list(re.finditer(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text))
            for hit in hits:
                before = text[max(0, hit.start() - 24):hit.start()]
                if re.search(r'\bno(?:\s+es)?(?:\s+para)?\s*$', before):
                    negated.append(pet['id'])
                else:
                    matches.append(pet['id'])
    matches = list(dict.fromkeys(matches))
    unresolved = bool(negated and not matches)
    if len(matches) > 1:
        unresolved = True
    # A contextual partial/nickname can request clarification, never resolution.
    if contextual and not matches and not public:
        fragment = re.search(r'\bpara\s+(\w+)\s*$', text)
        if fragment and fragment[1] not in (*WEEKDAYS, 'manana', 'hoy', 'consulta', 'vacunacion'):
            unresolved = True
    updates = {}
    if contextual and (matches or unresolved or negated):
        updates['pet'] = matches[0] if len(matches) == 1 else None
    if today and not public:
        days = [(m.start(), today + timedelta(days=(i - today.weekday()) % 7 or 7))
                for i, name in enumerate(WEEKDAYS)
                for m in re.finditer(r'\b' + name + r'\b', text)]
        days += [(m.start(), today + timedelta(days=1))
                 for m in re.finditer(r'\bmanana\b', text)]
        days += [(m.start(), today) for m in re.finditer(r'\bhoy\b', text)]
        if days:
            updates['date'] = max(days, key=lambda pair: pair[0])[1].isoformat()
        iso = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
        if iso:
            updates['date'] = iso[-1]
        services = list(re.finditer(r'\b(consulta(?: general)?|vacunacion|esterilizacion|revision)\b', text))
        if services:
            updates['service'] = services[-1][1]
            updates['reason'] = services[-1][1]
        times = re.findall(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\b', text)
        if times:
            updates['time'] = times[-1].zfill(5)
    # Public side question never establishes/replaces pet or date.
    return {'kinds': kinds, 'correction': correction, 'abandon': abandon,
            'public': public, 'updates': updates,
            'ambiguous': unresolved or len(matches) > 1,
            'compound': len(kinds) > 1 or (bool(kinds) and len(set(matches)) > 1 and ' y ' in text),
            'appointment_unresolved': correction and bool(re.search(r'\b(?:esa|otra|cita)\b', text))
                                      and not matches,
            'personal': bool(re.search(r'\b(?:vacunas?|citas?|mascotas?)\b', text))}


def permitted_pets(conversation):
    from . import identity
    from apps.patients.models import Pet
    if not identity.is_verification_current(conversation.contact) or not conversation.contact.owner_id:
        return []
    return list(Pet.objects.filter(organization_id=conversation.organization_id,
                owner_id=conversation.contact.owner_id).order_by('pk').values('id', 'name'))


def clarification(conversation, *, appointment=False, compound=False):
    binding.observe('clarification_required')
    if compound:
        return 'Hay más de un asunto. ¿Cuál quieres resolver primero?'
    if appointment:
        return '¿Qué cita quieres consultar? Necesito volver a identificarla antes de continuar.'
    pets = permitted_pets(conversation)
    names = list(dict.fromkeys(p['name'] for p in pets))
    if 1 < len(names) <= 6:
        return '¿Para cuál mascota: ' + ' o '.join(names) + '?'
    if pets and len(names) < len(pets):
        return 'Hay mascotas con el mismo nombre. Necesito que el equipo identifique el expediente correcto.'
    return '¿Para cuál mascota es la consulta?'


def _start(conversation, kind):
    from .models import ConversationGoal
    goal = create_local(ConversationGoal, organization=conversation.organization,
                        conversation=conversation, name=kind)
    binding.observe('matter_started')
    return goal


def process_turn(conversation, context):
    """Called by policy after safety/human gates and before legacy confirmations."""
    from .models import Conversation, ConversationGoal
    from . import confirmations
    from .turn_context import messages_for_turn
    if conversation.state in (Conversation.STATE_HUMAN_ACTIVE, Conversation.STATE_HANDOFF_PENDING):
        return None
    messages_for_turn(conversation, context)
    pets = permitted_pets(conversation)
    # The complete fixed membership is inspected before making any change.
    parsed = [(event, parse(event.text, pets, active=binding.current_goal(conversation) is not None,
                           today=context.clinic_now.date())) for event in context.events
              if event.message_id is not None]
    if not parsed:
        return None
    if any(p['compound'] for _, p in parsed):
        binding.observe('ambiguous_entity')
        return clarification(conversation, compound=True)
    # Two independent operation requests in one burst are also compound unless
    # the later event explicitly replaces/corrects the first.
    kinds = set()
    requested_pets = set()
    for _, p in parsed:
        if p['correction'] or p['abandon']:
            kinds.clear()
            requested_pets.clear()
        kinds.update(p['kinds'])
        if p['kinds'] and p['updates'].get('pet') is not None:
            requested_pets.add(p['updates']['pet'])
    if len(kinds) > 1 or len(requested_pets) > 1:
        return clarification(conversation, compound=True)
    from . import identity
    active_goal = binding.current_goal(conversation)
    if (not identity.is_verification_current(conversation.contact)
            and not (active_goal and binding.metadata(active_goal))
            and not any(p['abandon'] for _, p in parsed)):
        # Identity's existing challenge remains authoritative. No enumeration or
        # guessed binding before verification, nor synthetic provenance for it.
        return None
    reply = None
    # No network/LLM in here. B3 staging keeps these writes in the final commit.
    with transaction.atomic():
        conv = local_or_locked_conversation(conversation)
        for event, parsed_event in parsed:
            goal = binding.current_goal(conv)
            cursor = [event.created_at.isoformat(), event.message_id]
            if goal and binding.metadata(goal).get('last_event_cursor', []) >= cursor:
                continue
            p = parsed_event
            if goal and binding.metadata(goal) and goal.bound_owner_id is not None:
                owner_now = (conv.contact.owner_id
                             if identity.is_verification_current(conv.contact) else None)
                if goal.bound_owner_id != owner_now:
                    binding.change(goal, conv, {'owner': owner_now}, context=context,
                        message_id=event.message_id, expected_revision=goal.binding_revision,
                        correction=True, unresolved=('pet',))
            if p['public']:
                continue
            kind = p['kinds'][0] if p['kinds'] else None
            if goal and (p['abandon'] or (kind and kind != goal.name)):
                goals.close(goal, ConversationGoal.STATUS_ABANDONED, 'matter_replaced' if kind else 'matter_abandoned')
                confirmations.supersede_pending(conv, reason='matter_replaced' if kind else 'matter_abandoned')
                binding.observe('matter_replaced' if kind else 'matter_abandoned')
                goal = None
            if p['abandon'] and not kind:
                reply = 'De acuerdo, dejamos ese asunto pendiente. No se canceló ninguna cita.'
                continue
            if goal is None and (kind or p['personal'] or p['updates'].get('pet') is not None):
                # Identity commitments retain their existing foreground authority.
                if goals.get_identity_commitment(conv) is not None:
                    continue
                goal = _start(conv, kind or ('read_vaccines' if 'vacuna' in normalize(event.text) else 'read_appointments'))
            if goal is None:
                continue
            updates = dict(p['updates'])
            unresolved = set()
            # Only an immediate, singular reference to this matter's current
            # candidate set. Ordinals/historical/"the other one" stay outside B6.
            if (re.search(r'\b(?:esa|muevela)\b', normalize(event.text))
                    and not p['appointment_unresolved']):
                candidates = binding.appointment_candidates(goal, conv)
                if len(candidates) == 1:
                    updates['appointment'] = candidates[0]
                else:
                    updates['appointment'] = None
                    unresolved.add('appointment')
            from . import identity
            if identity.is_verification_current(conv.contact) and conv.contact.owner_id:
                if goal.bound_owner_id != conv.contact.owner_id or not binding.trusted(goal, 'owner'):
                    updates['owner'] = conv.contact.owner_id
            elif goal.bound_owner_id:
                updates.update(owner=None, pet=None, appointment=None)
                unresolved.add('owner')
            if p['ambiguous']:
                updates['pet'] = None
                unresolved.add('pet')
                binding.observe('ambiguous_entity')
            if p['appointment_unresolved']:
                updates['appointment'] = None
                unresolved.add('appointment')
            for slot in ('date', 'time'):
                if slot in updates:
                    validator = goals._v_date if slot == 'date' else goals._v_time
                    ok, value, _ = validator(updates[slot], conv)
                    if ok:
                        updates[slot] = value
                    else:
                        updates[slot] = None
                        unresolved.add(slot)
            prior_values = binding.values(goal)
            replaced = any(
                (getattr(goal, binding.ENTITY_FIELDS[key]) if key in binding.ENTITY_FIELDS
                 else prior_values.get(key)) not in (None, value)
                for key, value in updates.items())
            binding.change(goal, conv, updates, context=context, message_id=event.message_id,
                expected_revision=goal.binding_revision,
                correction=p['correction'] or replaced, unresolved=unresolved)
            if binding.trusted(goal, 'pet'):
                from . import tools
                from apps.patients.models import Pet
                pet = Pet.objects.get(pk=goal.bound_pet_id)
                handle = tools._add_ref(conv, 'mascota', pet.public_id)
                tools._save_refs(conv)
                binding.record_derived(goal, conv, 'pet_handle', handle,
                    context=context, message_id=event.message_id,
                    expected_snapshot=binding.snapshot(goal), source_type='DERIVED')
            if unresolved:
                reply = clarification(conv, appointment='appointment' in unresolved)
            elif (not binding.trusted(goal, 'pet') and re.search(
                    r'\b(?:agendale|muevela|su ultima|tiene vacunas)\b', normalize(event.text))):
                reply = clarification(conv)
        conversation.flow = conv.flow
    return reply
