"""Isolated SQL test domain. Never an Appointment/Pet adapter or runtime plugin."""
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4
from django.db import connection
from django.test import override_settings
from apps.agent import operation_execution as execution


def setup_domain():
    if connection.vendor != 'postgresql' or not connection.settings_dict['NAME'].startswith('test_'):
        raise RuntimeError('B8A fake domain requires an isolated PostgreSQL test database')
    with connection.cursor() as c:
        c.execute('CREATE TABLE IF NOT EXISTS b8a_test_effect ('
            'operation_key uuid PRIMARY KEY, digest varchar(64) NOT NULL, organization_id bigint NOT NULL, '
            'object_id uuid NOT NULL, committed_at timestamptz NOT NULL)')
        c.execute('DELETE FROM b8a_test_effect')


def effect_count():
    with connection.cursor() as c:
        c.execute('SELECT count(*) FROM b8a_test_effect')
        return c.fetchone()[0]


class LocalTestAdapter:
    transaction_mode = 'LOCAL_ATOMIC'

    def validate_preconditions(self, operation, context):
        # This is only a test domain. Slot/appointment algorithms are NOT tested.
        return execution.PreconditionResult(True)

    def reconcile(self, operation, context):
        with connection.cursor() as c:
            c.execute('SELECT digest, organization_id, object_id, committed_at FROM b8a_test_effect '
                'WHERE operation_key = %s', [operation.operation_key])
            row = c.fetchone()
        if row is None:
            return execution.AdapterResult('ABSENT', no_effect_confirmed=True,
                operation_key=operation.operation_key, parameters_digest=operation.parameters_digest)
        if row[:2] != (operation.parameters_digest, operation.organization_id):
            return execution.AdapterResult('UNCERTAIN', reason='mismatched_domain_row')
        return execution.AdapterResult('SUCCEEDED', execution.EffectEvidence(operation.operation_key,
            row[0], str(row[2]), row[3]))

    def execute(self, operation, context):
        with connection.cursor() as c:
            c.execute('INSERT INTO b8a_test_effect VALUES (%s, %s, %s, %s, statement_timestamp())',
                [operation.operation_key, operation.parameters_digest, operation.organization_id, uuid4()])
        return self.reconcile(operation, context)


@contextmanager
def enabled_test_adapter(adapter=None):
    from .b9d_support import approved_test_release
    adapter = adapter or LocalTestAdapter()
    registry = dict(execution.REGISTRY)
    registry['CREATE_APPOINTMENT'] = replace(registry['CREATE_APPOINTMENT'], enabled=True, adapter=adapter)
    with approved_test_release(), patch.object(execution, 'REGISTRY', registry), patch(
            'apps.agent.intake.write_is_contained', return_value=False), override_settings(
            AGENT_OPERATION_EXECUTION_ENABLED={'CREATE_APPOINTMENT': True}):
        yield adapter
