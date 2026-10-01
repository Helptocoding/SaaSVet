"""Independent PG planner with a controlled eligibility clock and OS barriers."""
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from .b9a_process import barrier, emit


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections
    from django.db.models import F
    from apps.agent import durable, worker
    from apps.agent.models import Conversation, LLMCall, TurnWork
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('127.0.0.1','localhost')
            or config['ENGINE']!='django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all(); connections.databases['default'].update(config)
    clock = datetime.fromisoformat(os.environ['E4_YIELD_TEST_CLOCK'])
    attempts = []
    actual_claim = worker._claim_turn

    def claim(conversation, now=None):
        attempts.append(conversation)
        if len(attempts)==1:
            barrier('SELECTED')
        return actual_claim(conversation, now)

    def run(witness):
        barrier('CLAIMED')
        durable.finalize_turn(witness)

    barrier('READY')
    preliminary = worker.process_pending_conversations(batch=1, now=clock)
    emit('FORECAST', processed=preliminary, admissions=LLMCall.objects.count(),
         active=TurnWork.objects.filter(status=TurnWork.PROCESSING).count())
    barrier('FORECAST_WAIT')
    with patch.object(worker, '_claim_turn', side_effect=claim), patch.object(worker, '_run_turn', side_effect=run):
        processed = worker.process_pending_conversations(batch=1, now=clock+timedelta(seconds=1))
    emit('RESULT', processed=processed, attempts=attempts,
        active={str(org):durable.active_org_work(org).count() for org in
                Conversation.objects.values_list('organization_id',flat=True).distinct()},
        scope_violations=TurnWork.objects.exclude(organization_id=F('conversation__organization_id')).count(),
        admissions=LLMCall.objects.count())


if __name__=='__main__':
    main()
