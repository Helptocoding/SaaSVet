"""In-memory local changes for a B3 turn, discarded on crash or lost witness.

Explicit adapter for existing conversation/identity/goal/handoff writers.
There is no durable draft, ORM interception, or new business authority here.
Only finalize_turn may flush this buffer, under Conversation + TurnWork locks.
"""
import copy
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connection
from django.utils import timezone

from .durable import assert_witness, check_turn_deadline, lock_witness

_current = ContextVar('agent_turn_changes', default=None)
_LOCAL_MODELS = frozenset({
    'Conversation', 'ContactIdentity', 'ConversationGoal', 'HumanHandoff',
    'TurnDecision', 'TurnOperationAssessment', 'TurnOperationAssessmentMessage',
    'LLMCall', 'ToolExecution',
})


def current_changes():
    return _current.get()


class TurnChanges:
    def __init__(self, witness, conversation):
        from .models import ConversationGoal, HumanHandoff
        self.witness = witness
        self.conversation = conversation
        self.identity_revision = conversation.contact.authorization_revision
        self.outputs = []
        self.actions = []
        self.callbacks = []
        self.executions = {}
        self.goals = list(ConversationGoal.objects.for_organization(witness.organization_id)
                          .filter(conversation_id=witness.conversation_id).order_by('id'))
        self.binding_revisions = {g.pk: g.binding_revision for g in self.goals}
        self.handoffs = list(HumanHandoff.objects.for_organization(witness.organization_id)
                            .filter(conversation_id=witness.conversation_id,
                                    resolved_at__isnull=True).order_by('id'))

    @contextmanager
    def activate(self):
        check_turn_deadline(self.witness)
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    def scope(self, obj):
        if obj.__class__.__name__ not in _LOCAL_MODELS:
            raise ValueError('Unsupported B3 local model')
        if obj.organization_id != self.witness.organization_id:
            raise ValueError('Cross-organization local change')
        name = obj.__class__.__name__
        if name == 'Conversation':
            valid = obj.pk == self.witness.conversation_id
        elif name == 'ContactIdentity':
            valid = obj.pk == self.conversation.contact_id
        elif name == 'TurnOperationAssessmentMessage':
            valid = (obj.assessment.conversation_id == self.witness.conversation_id
                     and obj.message.conversation_id == self.witness.conversation_id
                     and obj.message.organization_id == self.witness.organization_id)
        else:
            valid = obj.conversation_id == self.witness.conversation_id
        if not valid:
            raise ValueError('Cross-conversation local change')

    def save(self, obj, *, update_fields=None, **kwargs):
        self.scope(obj)
        check_turn_deadline(self.witness)
        new = not obj.pk
        if new:
            # Sequence reservation is NOT a durable row or evidence. It lets
            # existing local references point to one another before final commit.
            # Gaps after rollback/crash are normal PostgreSQL sequence behavior.
            with connection.cursor() as cursor:
                cursor.execute("SELECT nextval(pg_get_serial_sequence(%s, 'id'))",
                               [obj._meta.db_table])
                obj.pk = cursor.fetchone()[0]
            obj.created_at = timezone.now()
            if type(obj).__name__ == 'ConversationGoal':
                self.goals.append(obj)
            elif type(obj).__name__ == 'HumanHandoff':
                self.handoffs.append(obj)
        fields = [f for f in obj._meta.concrete_fields if new or update_fields is None
                  or f.name in update_fields or f.attname in update_fields or f.primary_key]
        values = {f.attname: copy.deepcopy(getattr(obj, f.attname)) for f in fields}
        self.actions.append((type(obj), values, new, update_fields))
        if type(obj).__name__ == 'ToolExecution':
            self.executions[obj.pk] = obj
        return obj

    def flush(self, *, deferred=False):
        if not connection.in_atomic_block:
            raise RuntimeError('B3 flush requires the final transaction')
        lock_witness(self.witness)
        # B6 corrections outside this attempt must not be overwritten by a
        # recovered/stale in-memory goal. Locks follow Conversation/TurnWork.
        from .models import ConversationGoal, ContactIdentity
        from .matter_binding import BindingConflict
        contact = ContactIdentity.all_objects.select_for_update().get(
            pk=self.conversation.contact_id, organization_id=self.witness.organization_id)
        if contact.authorization_revision != self.identity_revision:
            raise BindingConflict('Identity changed before B3 publication')
        for goal in ConversationGoal.objects.select_for_update().filter(
                pk__in=self.binding_revisions).order_by('pk'):
            if goal.binding_revision != self.binding_revisions[goal.pk]:
                raise BindingConflict('B6 staged revision changed before publication')
        for model, values, new, fields in self.actions:
            values = dict(values)
            if deferred and model.__name__ == 'ContactIdentity':
                values.pop('privacy_notice_sent_at', None)
                if fields:
                    fields = [f for f in fields if f != 'privacy_notice_sent_at']
                    if not fields:
                        continue
            if model.__name__ == 'TurnDecision':
                values['facts_produced'] = {**values.get('facts_produced', {}),
                    'turn_work_id': self.witness.turn_work_id,
                    'ownership_epoch': self.witness.ownership_epoch,
                    'deferred_to_new_input': deferred}
            if new:
                obj = model(**values)
            else:
                obj = model.objects.for_organization(self.witness.organization_id).get(pk=values['id'])
                for field, value in values.items():
                    setattr(obj, field, value)
            # Scope was validated on staging; normal model validation still
            # runs on INSERT. UPDATE contains only the explicitly staged fields.
            obj.save(force_insert=new, update_fields=None if new else fields)
        # B7A definitions consume committed B6 state under the existing witness.
        # No renderer output is published here, no legacy reply is consent.
        if not deferred:
            from .operations import prepare_current
            prepare_current(self.witness)


def save_local(obj, **kwargs):
    changes = current_changes()
    if changes is None:
        return obj.save(**kwargs)
    return changes.save(obj, **kwargs)


def create_local(model, **kwargs):
    if current_changes() is None:
        return model.objects.create(**kwargs)
    obj = model(**kwargs)
    save_local(obj)
    return obj


def local_goals(conversation):
    changes = current_changes()
    if changes is not None:
        changes.scope(conversation)
        return changes.goals
    from .models import ConversationGoal
    return list(ConversationGoal.objects.for_organization(conversation.organization_id)
                .filter(conversation=conversation).order_by('id'))


def open_handoff(conversation):
    changes = current_changes()
    if changes is not None:
        changes.scope(conversation)
        return next((h for h in changes.handoffs if h.resolved_at is None), None)
    from .models import HumanHandoff
    return HumanHandoff.objects.for_organization(conversation.organization_id).filter(
        conversation=conversation, resolved_at__isnull=True).order_by('id').first()


def local_or_locked_conversation(conversation):
    changes = current_changes()
    if changes is not None:
        changes.scope(conversation)
        assert_witness(changes.witness)
        return changes.conversation
    from .models import Conversation
    return Conversation.objects.select_for_update().get(
        pk=conversation.pk, organization_id=conversation.organization_id)


def refresh_local(obj):
    if current_changes() is None:
        obj.refresh_from_db()


def after_local_commit(callback):
    changes = current_changes()
    if changes is None:
        callback()
    else:
        changes.callbacks.append(callback)
