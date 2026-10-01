"""DIAGNOSTIC_ONLY eligible-to-claim trace; frozen PROFILE runner is untouched.

Reuse the diagnostic fixtures, fake IO and topology. Record only closed events,
timestamps and local technical IDs. No production instrumentation or authority.
"""
import argparse
import json
import os
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from . import e4_profile, w1_mono_diagnostic


@contextmanager
def instrument(output: Path, role: str):
    from django.db import connection, transaction
    from apps.agent import worker
    from . import e4_timing
    events = []
    state = {}
    poll_serial = 0

    def stamp(event, **data):
        events.append(dict(event=event, time=time.time(), poll=state.get('poll'), **data))

    original_poll = worker.process_pending_conversations
    original_candidates = worker._pending_conversation_candidates
    if os.environ.get('E4_CLAIM_CANDIDATE') == 'bounded-yield':
        from .e4_claim_candidate import candidates
        original_candidates = candidates
    original_claim = worker._claim_turn
    original_enter = transaction.Atomic.__enter__

    def poll(*args, **kwargs):
        nonlocal poll_serial
        poll_serial += 1
        state['poll'] = poll_serial
        stamp('planner_start')
        try:
            result = original_poll(*args, **kwargs)
            stamp('planner_end', processed=result)
            return result
        finally:
            state.pop('poll', None)

    def candidates(*args, **kwargs):
        stamp('selection_start')
        result = list(original_candidates(*args, **kwargs))
        stamp('candidates_observed', conversations=result)
        return result

    def enter(atomic):
        result = original_enter(atomic)
        if state.get('claim') is not None and not state.get('transaction_seen'):
            state['transaction_seen'] = True
            stamp('claim_transaction_started', conversation=state['claim'])
        return result

    def claim(conversation, now=None):
        stamp('candidate_selected', conversation=conversation)
        state['claim'] = conversation
        try:
            result = original_claim(conversation, now)
            stamp('claim_commit' if result else 'claim_miss', conversation=conversation,
                  work=result.turn_work_id if result else None)
            return result
        finally:
            state.pop('claim', None)
            state.pop('transaction_seen', None)

    def sql(execute, query, params, many, context):
        started = time.time()
        table = next((name for name in ('organizations_organization', 'agent_conversation',
            'agent_turnwork', 'channels_message') if
            ('FROM "' + name + '"' in query and query.startswith('SELECT')) or
            query.startswith('UPDATE "' + name + '"')), None)
        locked = 'FOR UPDATE' in query or 'FOR NO KEY UPDATE' in query or query.startswith('UPDATE')
        if state.get('claim') is not None and table and locked:
            stamp('lock_requested', table=table, conversation=state['claim'])
        try:
            return execute(query, params, many, context)
        finally:
            elapsed = time.time() - started
            if state.get('claim') is not None and table and locked:
                stamp('lock_sql_returned', table=table, conversation=state['claim'],
                      start=started, duration=elapsed, skip_locked='SKIP LOCKED' in query)
            elif state.get('poll') and 'ROW_NUMBER()' in query:
                stamp('selector_sql_returned', start=started, duration=elapsed)

    with ExitStack() as stack:
        stack.enter_context(patch.object(e4_timing, '_sink', stamp))
        stack.enter_context(connection.execute_wrapper(sql))
        stack.enter_context(patch.object(worker, 'process_pending_conversations', poll))
        stack.enter_context(patch.object(worker, '_pending_conversation_candidates', candidates))
        stack.enter_context(patch.object(worker, '_claim_turn', claim))
        stack.enter_context(patch.object(transaction.Atomic, '__enter__', enter))
        try:
            yield
        finally:
            output.write_text(json.dumps(dict(schema='e4-claim-timing-v1', role=role,
                os_pid=os.getpid(), classification='DIAGNOSTIC_ONLY', events=events), indent=2) + '\n',
                encoding='utf-8')


def observe(*args):
    receipt = w1_mono_diagnostic.observe(*args)
    from apps.channels.models import Message
    from apps.agent.models import Conversation, TurnWork
    from apps.agent import worker
    from django.db import connection
    start, end = receipt['window_utc']
    orgs = args[3]
    with connection.cursor() as cursor:
        cursor.execute('SELECT version(), current_setting(%s), current_setting(%s)',
                       ['fsync', 'synchronous_commit'])
        database = cursor.fetchone()
        cursor.execute('SELECT count(*) FROM channels_message m JOIN agent_turnwork w ON m.turn_work_id=w.id '
                       'WHERE m.organization_id<>w.organization_id OR m.conversation_id<>w.conversation_id')
        cross_tenant_or_membership = cursor.fetchone()[0]
        # Django's qualify/Window wrapper nests QuerySet.explain incorrectly.
        # Explain the fully compiled SELECT, with its bound params, instead.
        selector = worker._pending_conversation_candidates
        if os.environ.get('E4_CLAIM_CANDIDATE') == 'bounded-yield':
            from .e4_claim_candidate import candidates
            selector = candidates
        query, params = selector().query.sql_with_params()
        cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + query, params)
        selector_plan = cursor.fetchone()[0]
    receipt['claim_diagnostic'] = dict(classification='DIAGNOSTIC_ONLY', acceptance_run=False,
        postgresql=database, cross_tenant_or_membership=cross_tenant_or_membership,
        selector_plan=selector_plan,
        healthy_messages=list(Message.objects.filter(direction='in', organization_id__in=orgs[:2],
            created_at__gte=start, created_at__lt=end).values('id', 'organization_id', 'conversation_id',
            'semantic_type', 'created_at', 'available_at', 'turn_work_id', 'turn_work__claimed_at')),
        conversations=list(Conversation.objects.filter(organization_id__in=orgs).values('id', 'organization_id')),
        works=list(TurnWork.objects.filter(organization_id__in=orgs).values('id', 'organization_id',
            'conversation_id', 'claimed_at', 'completed_at', 'status', 'outcome_code', 'llm_calls_admitted')))
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', required=True, choices=('base', 'blocked_llm'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--role')
    parser.add_argument('--stop', type=Path)
    args = parser.parse_args()
    if args.role:
        e4_profile.setup()
        path = args.stop.with_name(args.stop.stem + '-' + args.role + '.claim-timing.json')
        with instrument(path, args.role):
            e4_profile._worker(args.role, args.scenario, args.stop)
        return
    original_popen = e4_profile.subprocess.Popen
    original_observe = e4_profile.observe

    def popen(command, *a, **kw):
        command = list(command)
        command[command.index('apps.agent.tests.e4_profile')] = 'apps.agent.tests.e4_claim_diagnostic'
        return original_popen(command, *a, **kw)

    def extended(*a):
        with patch.object(e4_profile, 'observe', original_observe):
            return observe(*a)

    with patch.object(e4_profile.subprocess, 'Popen', popen), patch.object(e4_profile, 'observe', extended):
        e4_profile.orchestrate(args.scenario, args.output)


if __name__ == '__main__':
    main()
