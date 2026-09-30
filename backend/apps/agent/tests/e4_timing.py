"""Test-only timing. Closed event types; local technical IDs, never content.

SQL execution durations bound lock waits; they are NOT labelled as lock waits.
All journals stay in memory until the worker stops, avoiding per-event disk IO.
"""
import json
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

_sink = None


def record(event, **data):
    if _sink:
        _sink(event, **data)


@contextmanager
def instrument(output, role):
    global _sink
    from django.db import connection
    from django.db.models import Q
    from django.utils import timezone
    from apps.agent import durable, worker, llm_budget, tools
    from apps.agent.models import TurnWork
    from apps.agent.turn_changes import current_changes
    from apps.channels.models import Message
    events = []
    claim_context = {}
    poll_context = {}

    def stamp(event, **data):
        events.append(dict(event=event, time=time.time(), **data))

    _sink = stamp

    def sql(execute, query, params, many, context):
        start = time.time()
        result = execute(query, params, many, context)
        end = time.time()
        if claim_context:
            table = next((name for name in ('organizations_organization',
                'agent_conversation', 'agent_turnwork', 'channels_message')
                if (query.startswith('SELECT') and 'FROM "' + name + '"' in query)
                or query.startswith('UPDATE "' + name + '"')), None)
            if table:
                locked = 'FOR UPDATE' in query or 'FOR NO KEY UPDATE' in query or query.startswith('UPDATE')
                if locked:
                    stamp('claim_sql', table=table, start=start, duration=end-start,
                          conversation=claim_context['conversation'], skip_locked='SKIP LOCKED' in query)
                if 'FOR NO KEY UPDATE' in query:
                    stamp('capacity_check_start', start=start,
                          conversation=claim_context['conversation'])
        if poll_context and query.startswith('SELECT') and '"agent_conversation"' in query and (
                query.startswith('SELECT DISTINCT') or 'ROW_NUMBER()' in query):
            stamp('candidate_query', start=start, duration=end-start)
        return result

    original_poll = worker.process_pending_conversations
    if __import__('os').environ.get('E4_SELECTOR') in ('fair', 'efficient'):
        from .e4_selector import process_pending_conversations
        original_poll = process_pending_conversations
    def poll(*args, **kwargs):
        started = time.time()
        now = timezone.now()
        rows = list(Message.objects.filter(direction='in', status='pending',
            turn_work__isnull=True).values('pk', 'organization_id', 'conversation_id', 'available_at'))
        active = set(TurnWork.objects.filter(status=TurnWork.PROCESSING,
            lease_expires_at__gt=now, conversation__ownership_epoch=__import__(
                'django.db.models', fromlist=['F']).F('ownership_epoch'))
            .values_list('organization_id', flat=True))
        queue = {}
        for row in rows:
            org = row['organization_id']
            counts = queue.setdefault(org, dict(pending=0, eligible=0, blocked=0, claimable=0))
            counts['pending'] += 1
            eligible = row['available_at'] is None or row['available_at'] <= now
            if eligible:
                counts['eligible'] += 1
                counts['blocked' if org in active else 'claimable'] += 1
        stamp('poll', start=started, queue=queue,
            healthy_eligible=[row['pk'] for row in rows if
                (row['available_at'] is None or row['available_at'] <= now)
                and row['organization_id'] != int(__import__('os').environ['B9E_NOISY_ORG_ID'])],
            observer_seconds=time.time()-started)
        poll_context['active'] = True
        try:
            result = original_poll(*args, **kwargs)
            stamp('poll_end', processed=result)
            return result
        finally:
            poll_context.clear()

    original_claim = worker._claim_turn
    def claim(conversation, now=None):
        stamp('candidate_selected', conversation=conversation)
        claim_context['conversation'] = conversation
        try:
            result = original_claim(conversation, now)
            stamp('claim_commit' if result else 'claim_miss', conversation=conversation,
                  work=result.turn_work_id if result else None)
            return result
        finally:
            claim_context.clear()

    def wrap(original, event, witness_arg=False):
        def wrapped(*args, **kwargs):
            changes = current_changes()
            witness = args[0] if witness_arg else (changes.witness if changes else None)
            work = witness.turn_work_id if witness else None
            stamp(event + '_start', work=work)
            try:
                return original(*args, **kwargs)
            finally:
                stamp(event + '_end', work=work)
        return wrapped

    with ExitStack() as stack:
        stack.enter_context(connection.execute_wrapper(sql))
        stack.enter_context(patch.object(worker, 'process_pending_conversations', poll))
        stack.enter_context(patch.object(worker, '_claim_turn', claim))
        stack.enter_context(patch.object(durable, 'finalize_turn', wrap(durable.finalize_turn, 'finalize', True)))
        stack.enter_context(patch.object(llm_budget, 'complete', wrap(llm_budget.complete, 'llm')))
        stack.enter_context(patch.object(tools, 'run_tool', wrap(tools.run_tool, 'tool')))
        try:
            yield
        finally:
            output.write_text(json.dumps(dict(schema='e4-timing-v2', role=role,
                classification='DIAGNOSTIC_ONLY', events=events), indent=2) + '\n', encoding='utf-8')
            _sink = None
