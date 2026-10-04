"""Opt-in causal claim journal. Observation never grants runtime authority.

Use capture() on each diagnostic worker/ingress thread, outside a transaction.
No environment flag, logger formatting, SQL text/parameters or extra hot-path
queries. The normal path only checks a ContextVar. Journals are append/flush
streams: a missing footer or failed write makes evidence INCOMPLETE.
"""
import hashlib
import json
import os
import re
import threading
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from uuid import uuid4

from django.db import connections


_active = ContextVar('claim_diagnostic_session', default=None)
_scope = ContextVar('claim_diagnostic_scope', default=None)
SCHEMA = 'e4-causal-claim-v1'
TABLES = ('organizations_organization', 'agent_conversation', 'agent_turnwork',
          'channels_message', 'agent_contactidentity', 'agent_agentsettings')


def _iso(value):
    return value.isoformat(timespec='microseconds') if value is not None else None


def _witness(value):
    return dict(turn_work_id=value.turn_work_id, organization_id=value.organization_id,
                conversation_id=value.conversation_id, epoch=value.ownership_epoch,
                lease_fingerprint=hashlib.sha256(value.lease_token.bytes).hexdigest())


class Journal:
    def __init__(self, stream, run_id, worker, connection):
        self.stream, self.connection = stream, connection
        self.run_id, self.worker = run_id, worker
        self.session_id = uuid4().hex
        self.seq = self.failed_writes = self.sql_count = 0
        self.transaction_id = None
        self.raw_connection = None
        self.connection_id = None
        self.spans = []

    def emit(self, event, **data):
        # A diagnostic sink failure must neither roll back a claim nor mask its
        # original exception. The footer/reader refuses incomplete evidence.
        self.seq += 1
        try:
            raw = self.connection.connection
            if raw is not self.raw_connection:
                self.raw_connection = raw
                self.connection_id = uuid4().hex if raw is not None else None
            info = getattr(raw, 'info', None)
            row = dict(schema=SCHEMA, event=event, run_id=self.run_id,
                       session_id=self.session_id, worker=self.worker,
                       os_pid=os.getpid(), thread_id=threading.get_ident(),
                       connection_id=self.connection_id,
                       backend_pid=getattr(info, 'backend_pid', None),
                       savepoint_ids=list(self.connection.savepoint_ids),
                       autocommit=self.connection.autocommit,
                       transaction_id=self.transaction_id, seq=self.seq,
                       monotonic_ns=time.perf_counter_ns(), utc_ns=time.time_ns(),
                       **(_scope.get() or {}))
            row.update(data)
            self.stream.write(json.dumps(row, separators=(',', ':')) + '\n')
            self.stream.flush()
        except Exception:
            self.failed_writes += 1

    @contextmanager
    def span(self, kind, **data):
        parent = _scope.get() or {}
        ctx = dict(parent, span_id=uuid4().hex, parent_span_id=parent.get('span_id'))
        if kind in ('poll', 'selection', 'ingest'):
            ctx[kind + '_id'] = ctx['span_id']
        if kind == 'claim' or (kind == 'claim_locked' and not ctx.get('attempt_id')):
            ctx['attempt_id'] = ctx['span_id']
        ctx.update(data)
        token = _scope.set(ctx)
        count = self.sql_count
        self.spans.append(ctx)
        self.emit(kind + '_start')
        outcome = 'returned'
        try:
            yield ctx
        except BaseException as exc:
            outcome = 'error'
            self.emit(kind + '_error', error_class=type(exc).__name__)
            raise
        finally:
            self.emit(kind + '_end', outcome=outcome, query_count=self.sql_count-count)
            self.spans.pop()
            _scope.reset(token)

    def sql(self, execute, sql, params, many, context):
        self.sql_count += 1
        query_id = self.sql_count
        # Classification only. Never serialize SQL, params, exception text or
        # arbitrary database result values (including RETURNING payloads).
        statement = str(sql).strip().upper()
        operation = statement.split(None, 1)[0] if statement else 'OTHER'
        if operation not in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SAVEPOINT',
                             'RELEASE', 'ROLLBACK', 'SET', 'BEGIN', 'COMMIT'):
            operation = 'OTHER'
        self.emit('sql_start', query_id=query_id, operation=operation, many=bool(many),
                  tables=[name for name in TABLES if '"'+name.upper()+'"' in statement],
                  for_update='FOR UPDATE' in statement,
                  no_key_update='FOR NO KEY UPDATE' in statement,
                  skip_locked='SKIP LOCKED' in statement)
        start = time.perf_counter_ns()
        error = None
        try:
            return execute(sql, params, many, context)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            end = time.perf_counter_ns()
            self.emit('sql_end', query_id=query_id, execute_start_ns=start,
                      execute_end_ns=end, duration_ns=end-start, error_class=error)

    def transaction_method(self, original, kind):
        @wraps(original)
        def call(*args, **kwargs):
            self.emit(kind + '_start')
            start = time.perf_counter_ns()
            error = None
            try:
                return original(*args, **kwargs)
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                end = time.perf_counter_ns()
                self.emit(kind + '_end', duration_ns=end-start,
                          execute_start_ns=start, execute_end_ns=end, error_class=error)
        return call


@contextmanager
def capture(path, *, run_id, worker, using='default'):
    """One thread/connection, full transaction boundaries; no SQL on entry.

    run_id must be shared across the participating processes. worker is a
    technical role label, never a user-supplied identifier or message value.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id + '') or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,40}', worker + ''):
        raise ValueError('Technical run/worker identifiers required')
    connection = connections[using]
    if (_active.get() is not None or connection.in_atomic_block or
            (connection.connection is not None and not connection.autocommit)):
        raise RuntimeError('Start one diagnostic capture outside atomic() per connection')
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream, ExitStack() as stack:
        journal = Journal(stream, run_id, worker, connection)
        token = _active.set(journal)
        stack.callback(_active.reset, token)
        stack.enter_context(connection.execute_wrapper(journal.sql))

        def replace(name, replacement):
            # Restore the instance exactly, including the absence of overrides.
            existed, previous = name in connection.__dict__, connection.__dict__.get(name)
            setattr(connection, name, replacement)
            def restore():
                if existed:
                    setattr(connection, name, previous)
                else:
                    delattr(connection, name)
            stack.callback(restore)

        original_autocommit = connection.set_autocommit
        def autocommit(value, *args, **kwargs):
            previous = journal.transaction_id
            if value:
                # Django runs on_commit callbacks inside set_autocommit(True).
                # Their subsequent SQL is outside the committed transaction.
                journal.transaction_id = None
            try:
                result = original_autocommit(value, *args, **kwargs)
            except BaseException:
                journal.transaction_id = previous
                raise
            if not value:
                journal.transaction_id = uuid4().hex
                journal.emit('transaction_begin')
            else:
                journal.transaction_id = None
            return result
        replace('set_autocommit', autocommit)
        for name, kind in (('_commit', 'commit'), ('_rollback', 'rollback')):
            replace(name, journal.transaction_method(getattr(connection, name), kind))
        replace('connect', journal.transaction_method(connection.connect, 'connection_open'))
        for name, kind in (('_savepoint', 'savepoint'),
                           ('_savepoint_commit', 'savepoint_release'),
                           ('_savepoint_rollback', 'savepoint_rollback')):
            original = getattr(connection, name)
            def savepoint(sid, original=original, kind=kind):
                journal.emit(kind, savepoint_id=sid)
                error = None
                try:
                    return original(sid)
                except BaseException as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    journal.emit(kind + '_end', savepoint_id=sid, error_class=error)
            replace(name, savepoint)
        journal.emit('capture_start', classification='DIAGNOSTIC_ONLY', acceptance_run=False)
        try:
            yield journal
        finally:
            journal.emit('capture_end', query_count=journal.sql_count,
                          failed_writes=journal.failed_writes,
                          open_transaction=journal.transaction_id is not None)


def observed(kind):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            journal = _active.get()
            if journal is None:
                return function(*args, **kwargs)
            data = {}
            if kind == 'claim':
                data['conversation_id'] = args[0] if args else kwargs['conversation_id']
            elif kind == 'claim_locked':
                conv = args[0] if args else kwargs['conv']
                data.update(conversation_id=conv.pk, organization_id=conv.organization_id,
                            epoch=conv.ownership_epoch)
            elif kind == 'turn':
                data.update(_witness(args[0] if args else kwargs['witness']))
            with journal.span(kind, **data) as ctx:
                result = function(*args, **kwargs)
                if kind in ('claim', 'claim_locked'):
                    if result is not None:
                        ctx.update(_witness(result))
                    journal.emit('claim_result', result='claimed' if result else 'miss',
                                  boundary=kind)
                return result
        return wrapped
    return decorate


def select_candidates(factory, *args):
    journal = _active.get()
    if journal is None:
        return list(factory(*args))
    with journal.span('selection') as ctx:
        result = list(factory(*args))
        journal.emit('selection_result', conversation_ids=result)
        selection_id = ctx['selection_id']
    parent = _scope.get()
    if parent is not None:
        parent['selection_id'] = selection_id
    return result


def database_clock(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        journal = _active.get()
        if journal is None:
            return function(*args, **kwargs)
        start, utc_start = time.perf_counter_ns(), time.time_ns()
        result = function(*args, **kwargs)
        end, utc_end = time.perf_counter_ns(), time.time_ns()
        journal.emit('db_clock', db_timestamp=_iso(result), start_ns=start, end_ns=end,
                      utc_start_ns=utc_start, utc_end_ns=utc_end)
        return result
    return wrapped


def persisted(message):
    journal = _active.get()
    if journal:
        journal.emit('message_persisted', message_id=message.pk,
                      organization_id=message.organization_id,
                      conversation_id=message.conversation_id,
                      created_at=_iso(message.created_at), available_at=_iso(message.available_at))


def deadline(conversation, target, now, count):
    journal = _active.get()
    if journal:
        journal.emit('deadline_set', conversation_id=conversation.pk,
                      organization_id=conversation.organization_id, available_at=_iso(target),
                      db_timestamp=_iso(now), affected_rows=count,
                      scope='ordinary_pending_unassigned')


def members(messages):
    journal = _active.get()
    if journal:
        for message in messages:
            journal.emit('membership_candidate', message_id=message.pk,
                          organization_id=message.organization_id,
                          conversation_id=message.conversation_id,
                          created_at=_iso(message.created_at), available_at=_iso(message.available_at),
                          effective_eligible_at=_iso(max(message.created_at,
                              message.available_at or message.created_at)))


def existing_work(work):
    journal = _active.get()
    if journal and work is not None:
        journal.emit('existing_work', turn_work_id=work.pk, status=work.status,
                      epoch=work.ownership_epoch, attempts=work.attempts,
                      next_attempt_at=_iso(work.next_attempt_at),
                      lease_expires_at=_iso(work.lease_expires_at))


def bound(work, token, now, expires, member_ids=None):
    journal = _active.get()
    if journal:
        data = dict(turn_work_id=work.pk, organization_id=work.organization_id,
                    conversation_id=work.conversation_id, epoch=work.ownership_epoch,
                    lease_fingerprint=hashlib.sha256(token.bytes).hexdigest(),
                    claimed_at=_iso(now), lease_expires_at=_iso(expires), attempts=work.attempts)
        ctx = _scope.get()
        if ctx is not None:
            ctx.update({key: data[key] for key in ('turn_work_id', 'organization_id',
                       'conversation_id', 'epoch', 'lease_fingerprint')})
        journal.emit('claim_bound', member_ids=member_ids, **data)
