"""Independent diagnostic test worker. OS barriers, real PG, synthetic IO."""
import json
import hashlib
import os
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, connection
    from apps.agent import durable, worker
    from apps.agent.claim_diagnostics import capture
    from apps.agent.models import TurnWork
    from apps.channels.models import ChannelAccount
    from .b9a_harness import ApplicationHarness, answer
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1', 'localhost')
            or config['ENGINE'] != 'django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all()
    connections.databases['default'].update(config)
    mode, conversation_id, channel_id, path, run_id, enabled = sys.argv[1:]
    connection.ensure_connection()

    def emit(kind, **data):
        print('TRACE_' + kind + ' ' + json.dumps(data), flush=True)

    def barrier(kind, **data):
        emit(kind, **data)
        if sys.stdin.readline().strip() != 'go':
            raise RuntimeError('Missing test barrier')

    harness = ApplicationHarness(ChannelAccount.objects.get(pk=channel_id), llm=[answer(), answer()])
    held = False
    def callback(kind, event):
        nonlocal held
        if mode == 'llm' and kind == 'llm' and not held:
            held = True
            barrier('LLM_BLOCKED', in_atomic=connection.in_atomic_block)
    harness.callback = callback
    statements = []
    def record(execute, sql, params, many, context):
        normalized = re.sub(r'"s[0-9]+_x[0-9]+"', '"savepoint"', sql)
        statements.append(hashlib.sha256(normalized.encode()).hexdigest())
        return execute(sql, params, many, context)
    commits = []
    original_commit = connection._commit
    def commit():
        if mode == 'claim_hold_commit' and not commits:
            barrier('COMMIT_HELD', in_atomic=connection.in_atomic_block)
        commits.append('commit')
        return original_commit()
    with harness.running(), patch.object(connection, '_commit', side_effect=commit), \
            (capture(Path(path), run_id=run_id, worker=mode) if enabled == 'on' else nullcontext()) as journal:
        barrier('READY', backend_pid=connection.connection.info.backend_pid,
                session_id=journal.session_id if journal else 'off-session',
                connection_id=journal.connection_id if journal else 'off-connection')
        with connection.execute_wrapper(record):
            if mode.startswith('claim'):
                result = durable.claim_turn(int(conversation_id))
                work = result.turn_work_id if result else None
            else:
                worker.process_pending_conversations(batch=1)
                work = None
    state = TurnWork.objects.filter(conversation_id=conversation_id).first()
    signature = None if state is None else dict(status=state.status, attempts=state.attempts,
        epoch=state.ownership_epoch, admitted=state.llm_calls_admitted,
        reserved=state.llm_output_tokens_reserved,
        lease_seconds=(state.lease_expires_at-state.claimed_at).total_seconds()
            if state.lease_expires_at and state.claimed_at else None,
        membership=list(state.messages.filter(direction='in').order_by('created_at','pk')
            .values_list('process_attempts', flat=True)))
    emit('RESULT', turn_work_id=work, sql_sequence=statements, commits=commits, state=signature)


if __name__ == '__main__':
    main()
