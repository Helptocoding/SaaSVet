"""Barrier-controlled independent planner, real selector/claim/finalization."""
import json
import os
import sys
from unittest.mock import patch
from .b9a_process import barrier, emit


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connection, connections
    from django.db.models import F
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1', 'localhost')
            or config['ENGINE'] != 'django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all(); connections.databases['default'].update(config)
    from apps.agent import worker, durable
    from apps.agent.models import Conversation, TurnWork
    from .b9a_harness import ApplicationHarness, answer
    conv = Conversation.objects.select_related('channel_account').get(pk=int(sys.argv[1]))
    harness = ApplicationHarness(conv.channel_account, llm=[answer()])
    actual_claim, actual_run = worker._claim_turn, worker._run_turn
    attempts, claimed = [], []
    def claim(pk, now=None):
        attempts.append(pk)
        if len(attempts) == 1: barrier('SELECTED')
        return actual_claim(pk, now)
    def run(witness):
        claimed.append(witness.turn_work_id)
        barrier('CLAIMED')
        actual_run(witness)
    with harness.running(), patch.object(worker, '_claim_turn', side_effect=claim), patch.object(worker, '_run_turn', side_effect=run):
        barrier('READY')
        processed = worker.process_pending_conversations(batch=1)
    emit('RESULT', processed=processed, attempts=attempts, claimed=claimed,
        active={str(org): durable.active_org_work(org).count()
            for org in Conversation.objects.values_list('organization_id', flat=True).distinct()},
        scope_violations=TurnWork.objects.exclude(organization_id=F('conversation__organization_id')).count())


if __name__ == '__main__': main()
