"""Independent budget participant on the parent's isolated PostgreSQL database."""
import json
import os
import sys
from uuid import UUID


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connections, connection
    config = json.loads(os.environ['B3_TEST_DATABASE'])
    if (not config['NAME'].startswith('test_') or config['HOST'] not in ('localhost', '127.0.0.1')
            or config['ENGINE'] != 'django.db.backends.postgresql'):
        raise RuntimeError('Isolated local PostgreSQL required')
    connections.close_all()
    connections.databases['default'].update(config)
    from apps.agent.durable import OwnershipWitness, OwnershipLost
    from apps.agent import llm_budget
    from .b9a_process import emit, barrier
    mode, witness_json, key = sys.argv[1:]
    data = json.loads(witness_json); data['lease_token'] = UUID(data['lease_token'])
    witness = OwnershipWitness(**data)
    barrier('READY')
    def boundary(execute, sql, params, many, context):
        if mode == 'hold_before_commit' and sql.startswith('UPDATE "agent_turnwork"'):
            barrier('BOUNDARY')
        return execute(sql, params, many, context)
    with connection.execute_wrapper(boundary):
        try:
            row, fresh = llm_budget.admit(witness, admission_id=UUID(key), purpose='planner',
                max_tokens=600, model_id='controlled', prompt_version='test')
            result = {'admitted': fresh, 'call_id': row.pk}
        except (llm_budget.BudgetRejected, OwnershipLost) as exc:
            result = {'admitted': False, 'reason': type(exc).__name__}
    if mode == 'hold_after_commit': barrier('BOUNDARY')
    emit('RESULT', **result)


if __name__ == '__main__':
    main()
