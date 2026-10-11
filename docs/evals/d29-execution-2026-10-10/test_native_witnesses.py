"""Real PostgreSQL adapter checks, separate from physical accreditation."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from apps.agent.tests.scheduling_characterization.runner import bootstrap, network_denied
bootstrap()
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from apps.agent import claim_diagnostics, durable, worker
from apps.agent.tests.b9a_harness import SETTINGS
from apps.agent.tests.test_b9a_e2e import seed_domain
from apps.agent.tests.scheduling_characterization.runner import Recorder
from apps.agent.tests.scheduling_characterization import execution
from evaluation_provider import installed as provider_installed
from native_witnesses import installed


class NativeWitnessTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='d29-witness-test-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.fixture = seed_domain('WitnessTest')
        self.recorder = Recorder(self.folder, 'witness-test')

    def rows(self):
        return [json.loads(x) for x in (self.folder / 'test.jsonl').read_text().splitlines()]

    def claim(self, row):
        # Unit-fixture eligibility only. Never used by a physical entry point.
        return durable.claim_turn(row.conversation_id, eligible_at=durable.db_now() + timedelta(seconds=40))

    def test_guard_false_and_native_terminal_are_same_transaction(self):
        with self.recorder.capture('test'), installed():
            row = self.recorder.offer(self.fixture[1])
            witness = self.claim(row)
            self.assertEqual(durable.finalize_turn(witness), 'completed')
        events = self.rows()
        guard = next(e for e in events if e['event'] == 'new_input_guard')
        terminal = next(e for e in events if e['event'] == 'work_terminal')
        self.assertFalse(guard['has_new_input'])
        self.assertEqual(guard['new_input_ids'], [])
        self.assertEqual(terminal['cas_affected'], 1)
        self.assertEqual(guard['transaction_id'], terminal['transaction_id'])
        self.assertTrue(any(e['event'] == 'commit_end' and e['transaction_id'] == terminal['transaction_id'] for e in events))

    def test_trigger_from_native_query_and_actual_successor_packed_context(self):
        job = dict(run_id='witness-test', case_id='R1-06', variant='backlog', organization_ids=[self.fixture[0].pk])
        with network_denied(), self.recorder.capture('test'), installed(), provider_installed(execution), \
                override_settings(**dict(SETTINGS, AGENT_SAFETY_AUTOMATION_ENABLED=True)):
            first = self.recorder.offer(self.fixture[1])
            witness = self.claim(first)
            second = self.recorder.offer(self.fixture[1])
            self.assertEqual(durable.finalize_turn(witness, outputs=[{'body': 'must defer'}]), 'deferred_to_new_input')
            successor = self.claim(second)
            provider = execution.Provider(self.folder, 'planner_1', job)
            import requests
            with patch.object(requests.Session, 'request', lambda session, method, url, **kw: provider.request(session, method, url, **kw)):
                worker._run_turn(successor)
        events = self.rows()
        guard = next(e for e in events if e['event'] == 'new_input_guard' and e['turn_work_id'] == witness.turn_work_id)
        context = next(e for e in events if e['event'] == 'context_consumed')
        self.assertTrue(guard['has_new_input'])
        self.assertEqual(guard['new_input_ids'], [second.pk])
        self.assertEqual(guard['input_source_cursors'][str(second.pk)], [second.created_at.isoformat(), second.pk])
        self.assertEqual(context['consumed_input_ids'], sorted([first.pk, second.pk]))
        self.assertEqual(context['turn_work_id'], successor.turn_work_id)
        wire = [json.loads(x) for x in (self.folder / 'planner_1-wire.jsonl').read_text().splitlines()]
        self.assertLess(context['monotonic_ns'], wire[0]['monotonic_ns'])
        self.assertEqual(len([r for r in wire if r['event'] == 'result']), 2)

    def test_rollback_keeps_observation_but_never_creates_commit(self):
        class Abort(Exception):
            pass
        with self.recorder.capture('test'), installed():
            row = self.recorder.offer(self.fixture[1])
            witness = self.claim(row)
            try:
                with transaction.atomic():
                    durable.finalize_turn(witness)
                    raise Abort()
            except Abort:
                pass
        events = self.rows()
        terminal = next(e for e in events if e['event'] == 'work_terminal')
        tx = [e for e in events if e['transaction_id'] == terminal['transaction_id']]
        self.assertTrue(any(e['event'] == 'rollback_end' for e in tx))
        self.assertFalse(any(e['event'] == 'commit_end' for e in tx))
        self.assertEqual(durable.TurnWork.objects.get(pk=witness.turn_work_id).status, 'PROCESSING')

    def test_unrelated_exists_is_not_a_guard_and_hooks_restore(self):
        from django.db.models.query import QuerySet
        original = QuerySet.exists
        with self.recorder.capture('test'), installed():
            self.assertFalse(durable.TurnWork.objects.exists())
        self.assertIs(QuerySet.exists, original)
        self.assertFalse(any(e['event'] in ('new_input_guard', 'work_terminal', 'context_consumed') for e in self.rows()))


if __name__ == '__main__':
    from django.conf import settings
    from django.db import connection, connections
    from django.test.runner import DiscoverRunner
    name = connection.settings_dict['NAME']
    settings.DATABASES['default']['TEST']['NAME'] = name
    connection.settings_dict['TEST']['NAME'] = name
    connections.close_all()
    runner = DiscoverRunner(keepdb=True, verbosity=2)
    raise SystemExit(bool(runner.run_tests(['test_native_witnesses.NativeWitnessTests'])))
