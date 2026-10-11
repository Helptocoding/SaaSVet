"""Opt-in evaluation witnesses. Never imported by production.

The guard uses its original predicate, LIMIT and native bool conversion. Only
the SELECT projection is extended on that very query to retain its witness
ID/cursor; there is no second query or retrospective history lookup.
"""
import copy
import hashlib
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from unittest.mock import patch

_guard = ContextVar('d29_native_guard', default=None)
_packing = ContextVar('d29_context_packing', default=None)


def authority(value):
    return dict(turn_work_id=value.turn_work_id, organization_id=value.organization_id,
                conversation_id=value.conversation_id, epoch=value.ownership_epoch,
                lease_fingerprint=hashlib.sha256(value.lease_token.bytes).hexdigest())


@contextmanager
def installed():
    from django.db import connection
    from django.db.models import F
    from django.db.models.query import QuerySet
    from django.db.models.sql.compiler import SQLCompiler
    from django.db.models.sql.constants import SINGLE
    from apps.agent import claim_diagnostics as trace, durable, planner, prompts
    from apps.agent.turn_changes import current_changes

    native_exists, native_results = QuerySet.exists, SQLCompiler.has_results
    native_update = QuerySet.update
    native_render, native_assemble = prompts._render_message, prompts.assemble_messages
    native_complete = planner._complete_with_retry
    packed, emitted = {}, set()

    def results(compiler):
        state = _guard.get()
        if state is None:
            return native_results(compiler)
        # Same single native existence query: no additional statement, locks,
        # predicate, ordering, pacing or boolean decision is introduced.
        query = compiler.query.clone()
        query.add_annotation(F('id'), '_d29_input_id', select=True)
        query.add_annotation(F('created_at'), '_d29_input_created', select=True)
        row = query.get_compiler(using=compiler.using, connection=compiler.connection).execute_sql(SINGLE)
        state['row'] = row
        return bool(row)

    def exists(queryset):
        caller = inspect.currentframe().f_back
        if (caller.f_code is not durable.has_new_input.__code__
                or caller.f_back.f_code is not durable.finalize_turn.__code__):
            return native_exists(queryset)
        if not connection.in_atomic_block or queryset._result_cache is not None:
            raise RuntimeError('NATIVE_GUARD_NOT_IN_LOCKED_TRANSACTION')
        work = caller.f_locals['work']
        state = {}
        token = _guard.set(state)
        try:
            value = native_exists(queryset)
        finally:
            _guard.reset(token)
        row = state['row']
        if bool(row) != value:
            raise RuntimeError('NATIVE_GUARD_RESULT_CHANGED')
        journal = trace._active.get()
        if journal is None or journal.transaction_id is None:
            raise RuntimeError('NATIVE_GUARD_CAPTURE_MISSING')
        journal.emit('new_input_guard', **authority(caller.f_back.f_locals['witness']),
                     has_new_input=value, new_input_ids=[row[1]] if row else [],
                     input_source_cursors={str(row[1]): [row[2].isoformat(), row[1]]} if row else {},
                     anchor_message_id=work.anchor_message_id,
                     anchor_created_at=work.anchor_created_at.isoformat(),
                     capture_boundary='NATIVE_EXISTENCE_QUERY', projection_only=True)
        return value

    def update(queryset, **kwargs):
        caller = inspect.currentframe().f_back
        count = native_update(queryset, **kwargs)
        if (caller.f_code is durable.finalize_turn.__code__
                and kwargs.get('status') == durable.TurnWork.COMPLETED):
            journal = trace._active.get()
            if journal is None or journal.transaction_id is None:
                raise RuntimeError('NATIVE_TERMINAL_CAPTURE_MISSING')
            journal.emit('work_terminal', **authority(caller.f_locals['witness']),
                         outcome_code=kwargs['outcome_code'], cas_affected=count,
                         capture_boundary='NATIVE_TERMINAL_CAS')
        return count

    def render(message):
        value = native_render(message)
        bucket = _packing.get()
        if bucket is not None and value:
            bucket.append((message.pk, message.direction, message.organization_id, message.conversation_id))
        return value

    def assemble(conversation, **kwargs):
        bucket = []
        token = _packing.set(bucket)
        try:
            value = native_assemble(conversation, **kwargs)
        finally:
            _packing.reset(token)
        changes = current_changes()
        if changes is not None:
            context = kwargs['turn_context']
            witness = changes.witness
            ids = [e.message_id for e in context.events if e.text and e.message_id is not None]
            ids += [mid for mid, direction, org, conv in bucket
                    if direction == 'in' and (org, conv) == (witness.organization_id, witness.conversation_id)]
            packed[witness.turn_work_id] = (copy.deepcopy(value), sorted(set(ids)), context)
        return value

    def complete(conversation, client, **kwargs):
        changes = current_changes()
        if changes is not None and changes.witness.turn_work_id not in emitted:
            witness = changes.witness
            value, ids, context = packed[witness.turn_work_id]
            if kwargs['messages'][:len(value)] != value:
                raise RuntimeError('ACTUAL_LLM_PACKED_CONTEXT_CHANGED')
            journal = trace._active.get()
            if journal is None:
                raise RuntimeError('CONTEXT_CAPTURE_MISSING')
            cursor = context.history_before
            journal.emit('context_consumed', **authority(witness), phase='BEFORE_FIRST_LLM',
                         capture_boundary='ACTUAL_PACKED_CONTEXT', consumed_input_ids=ids,
                         member_ids=list(context.inbound_ids),
                         history_before=[cursor.created_at.isoformat(), cursor.message_id] if cursor else None)
            emitted.add(witness.turn_work_id)
        return native_complete(conversation, client, **kwargs)

    with patch.object(SQLCompiler, 'has_results', results), patch.object(QuerySet, 'exists', exists), \
            patch.object(QuerySet, 'update', update), patch.object(prompts, '_render_message', render), \
            patch.object(prompts, 'assemble_messages', assemble), patch.object(planner, '_complete_with_retry', complete):
        yield
