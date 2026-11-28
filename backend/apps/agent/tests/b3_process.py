"""Bounded B3 process-isolation probe. Used only against the test database."""
import json
import os
import sys
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if not config['NAME'].startswith('test_'):
        raise RuntimeError('B3 probe requires an isolated test database')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent import durable, worker
    mode, conv_id = sys.argv[1], int(sys.argv[2])
    print('B3_READY', flush=True)
    sys.stdin.readline()
    witness = durable.claim_turn(conv_id)
    if mode == 'crash':
        if witness is None:
            raise RuntimeError('Crash probe did not reach claim')
        os._exit(17)  # Process dies after the real claim COMMIT, without cleanup.
    if mode == 'timeout' and witness is not None:
        from unittest.mock import patch
        from django.db import connection
        from apps.agent import planner
        from apps.agent.llm import LLMError, StubLLMClient
        from apps.agent.models import AgentSettings
        from apps.users.services import ensure_agent_user
        conv = worker.Conversation.objects.get(pk=conv_id)
        actor, _ = ensure_agent_user(conv.organization)
        create_enabled_agent_settings(conv.organization, agent_user=actor)
        stub = StubLLMClient(scripted=[])
        def timeout(**kwargs):
            if connection.in_atomic_block:
                raise RuntimeError('LLM called inside a transaction')
            raise LLMError('injected timeout', retryable=False)
        with patch.object(planner, 'get_llm_client', return_value=stub), patch.object(stub, 'complete', side_effect=timeout):
            worker._run_turn(witness)
    elif mode == 'run' and witness is not None:
        worker._run_turn(witness)
    print('B3_RESULT ' + json.dumps({
        'work': witness.turn_work_id if witness else None,
        'token': str(witness.lease_token) if witness else None,
    }), flush=True)
    connections.close_all()


if __name__ == '__main__':
    main()
