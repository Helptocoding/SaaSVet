"""Fail-closed tests against captured physical receipts; no replay substitute."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from apps.agent.tests.scheduling_characterization.frontier_infrastructure import preparation, prepare_burst, publish, reconcile_cut, schedule, start_prepared_backlog
from apps.agent.tests.scheduling_characterization.frontier_verify import verify
from apps.agent.tests.scheduling_characterization.frontiers import execute


class FrontierPreparationTests(unittest.TestCase):
    def test_dependent_preparations_cannot_claim_base_or_accreditation(self):
        for case in ('R1-05', 'R1-06'):
            value = preparation(case)
            self.assertEqual(value['status'], 'PENDING')
            self.assertEqual(value['prerequisites'][0]['status'], 'PENDING')
            self.assertEqual(value['evidence_physical'], [])
            self.assertFalse(value['future_execution_authorized'])

    def test_dependent_case_is_rejected_before_bootstrap(self):
        for case in ('R1-05', 'R1-06'):
            with self.assertRaisesRegex(ValueError, 'Only the three'):
                execute(Path('must-not-be-created'), case, 'rejected')

    def test_calendar_rejects_unobservable_release_windows(self):
        with self.assertRaisesRegex(ValueError, 'release windows'):
            schedule([(0, 0), (1, 0)], [0, 0], [0, 1])

    def test_complete_gate_cannot_overwrite_observed_barrier(self):
        with tempfile.TemporaryDirectory(prefix='d29-gate-') as directory:
            path = Path(directory) / 'gate.json'
            publish(path, {'stage': 'first'})
            with self.assertRaises(FileExistsError):
                publish(path, {'stage': 'replacement'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'stage': 'first'})
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['gate.json'])

    def test_supplied_burst_calendars_cannot_produce_confirmed_base(self):
        phases = [dict(phase=name, assignments=[(0, 0), (1, 0)], offsets_ns=[0, 1],
                       ends_ns=[1, 2], caller_status='CONFIRMED_BASE')
                  for name in ('before-burst', 'burst', 'base-return')]
        with tempfile.TemporaryDirectory(prefix='d29-burst-preparation-') as directory:
            value = prepare_burst(SimpleNamespace(directory=Path(directory)), 'simultaneous', phases)
            self.assertEqual(value['status'], 'PENDING')
            self.assertIsNone(value['confirmed_base'])
            self.assertFalse(value['future_execution_authorized'])
            self.assertEqual(value['schedule_provenance'], 'UNACCREDITED_CALLER_SUPPLIED')

    def test_initial_backlog_rejects_workers_started_before_cut(self):
        with self.assertRaisesRegex(ValueError, 'initially not started'):
            start_prepared_backlog(SimpleNamespace(children=[object()]), [])


class PhysicalVerifierNegativeTests(unittest.TestCase):
    def setUp(self):
        root = os.environ.get('D29_FRONTIER_RECEIPTS')
        if not root:
            self.skipTest('Requires the preserved physical receipts; never uses a replay fixture')
        self.receipts = Path(root)
        self.temp = tempfile.TemporaryDirectory(prefix='d29-frontier-negative-')
        self.addCleanup(self.temp.cleanup)

    def copied(self, case):
        selection = json.loads((self.receipts / 'selection.json').read_text(encoding='utf-8'))
        source = self.receipts / selection[case]
        target = Path(self.temp.name) / case
        shutil.copytree(source, target)
        self.assertEqual(verify(target)['status'], 'PHYSICALLY_ACCREDITED')
        return target

    def mutate(self, directory, filename, change, *, reseal=True):
        path = directory / filename
        value = json.loads(path.read_text(encoding='utf-8'))
        change(value)
        path.write_text(json.dumps(value) + '\n', encoding='utf-8')
        if reseal:
            receipt_path = directory / 'receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt['artifacts'][filename] = hashlib.sha256(path.read_bytes()).hexdigest()
            receipt_path.write_text(json.dumps(receipt) + '\n', encoding='utf-8')
        result = verify(directory)
        self.assertEqual(result['status'], 'NOT_ACCREDITED', result)
        return result

    def test_missing_coexisting_conversation_fails_even_with_resealed_hash(self):
        self.mutate(self.copied('R1-01'), 'coexistence.json', lambda v: v['member_ids'].pop())

    def test_common_calendar_change_fails_even_with_resealed_hash(self):
        self.mutate(self.copied('R1-03'), 'unequal-calendar.json',
                    lambda v: v['slots'][0].update(offset_ns=1))

    def test_later_snapshot_cannot_replace_pre_query_causal_witness(self):
        directory = self.copied('R1-04')
        receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
        self.mutate(directory, 'forecast-one-causal.json',
                    lambda v: v.update(pre_query_snapshot=receipt['final_snapshot']))

    def test_forecast_miss_cannot_be_renamed_claim_miss(self):
        self.mutate(self.copied('R1-04'), 'forecast-miss.json', lambda v: v.update(claim_miss=True))

    def test_model_pass_cannot_override_unobserved_frontier(self):
        directory = self.copied('R1-04')
        self.mutate(directory, 'forecast-one-causal.json',
                    lambda v: v.update(forecast_due_ns=0, status='PASS'))

    def test_base_prerequisite_cannot_be_removed(self):
        self.mutate(self.copied('R1-03'), 'receipt.json', lambda v: v.update(prerequisites=[]), reseal=False)

    def test_synthetic_provenance_cannot_accredit(self):
        self.mutate(self.copied('R1-01'), 'receipt.json',
                    lambda v: v.update(source_kind='SYNTHETIC_REPLAY'), reseal=False)

    def test_zero_ready_queue_does_not_erase_unfinished_work(self):
        directory = self.copied('R1-01')
        receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
        cut = json.loads((directory / receipt['final_snapshot']).read_text(encoding='utf-8'))
        offers = [json.loads(x) for x in (directory / 'offers.jsonl').read_text(encoding='utf-8').splitlines()]
        ids = [o['message_id'] for o in offers]
        cut['works'][0]['status'] = 'PROCESSING'
        result = reconcile_cut(offers, cut, ids)
        self.assertFalse(result['all_obligations_resolved'])
        self.assertTrue(any(o['work_obligations'] for o in result['organizations'].values()))
        self.assertFalse(any(o['ready_queue_ids'] for o in result['organizations'].values()))

    def test_missing_accepted_input_cannot_disappear_at_drain(self):
        directory = self.copied('R1-01')
        receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
        cut = json.loads((directory / receipt['final_snapshot']).read_text(encoding='utf-8'))
        offers = [json.loads(x) for x in (directory / 'offers.jsonl').read_text(encoding='utf-8').splitlines()]
        ids = [o['message_id'] for o in offers]
        result = reconcile_cut(offers[:-1], cut, ids)
        self.assertFalse(result['all_obligations_resolved'])
        self.assertEqual(result['missing_accepted_ids'], [ids[-1]])


if __name__ == '__main__':
    unittest.main()
