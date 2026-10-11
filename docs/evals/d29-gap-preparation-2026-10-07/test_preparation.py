"""Offline tests only. No Django setup, database, sleep, provider or load runs."""
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import clock_guard as cg
import evaluation_provider as ep
import reclaim_fixture as rf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / 'docs/evals/d29-dependent-2026-10-07'
BASE = ROOT / 'docs/evals/d29-r102-base-2026-10-07/confirmed-base-receipt.json'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='d29-offline-provider-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.job = dict(case_id='R2-09', variant='uncertain_meta', organization_ids=[1, 2],
                        run_id='offline-unit', slow_multiplier=2, blocked_llm_hold_seconds=120)
        self.provider = ep.Provider(self.folder, 'test', self.job)
        self.witness = SimpleNamespace(turn_work_id=10, organization_id=1, lease_token=UUID(int=1), ownership_epoch=0)
        self.connection = SimpleNamespace(in_atomic_block=False)
        active = Mock()
        active.count.return_value = 1
        active.filter.return_value.exists.return_value = True
        self.active = active
        calls = Mock()
        self.calls = calls
        self.meta = SimpleNamespace(organization_id=1, pk=100, send_admitted_at='committed', refresh_from_db=lambda: None)
        self.provider.meta_message = self.meta
        client = Mock()
        class Reply(dict):
            status_code, content = 200, b'{}'
            headers = {}
        client.get.return_value = Reply()
        modules = {}
        values = {
            'django': {}, 'django.db': dict(connection=self.connection), 'django.test': dict(Client=lambda: client),
            'apps': {}, 'apps.agent': {},
            'apps.agent.durable': dict(db_now=lambda: datetime.now(timezone.utc), active_org_work=lambda org: active),
            'apps.agent.models': dict(LLMCall=SimpleNamespace(objects=calls)),
            'apps.agent.turn_changes': dict(current_changes=lambda: SimpleNamespace(witness=self.witness)),
            'apps.agent.tests': {}, 'apps.agent.tests.b9a_harness': dict(answer=lambda: 'answer', response=lambda value: value, tool=lambda name: name),
        }
        for name, attrs in values.items():
            modules[name] = ModuleType(name)
            modules[name].__dict__.update(attrs)
        modules['apps.agent'].durable = modules['apps.agent.durable']
        self.patches = patch.dict(sys.modules, modules)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.sleep = patch.object(ep.time, 'sleep')
        self.sleeper = self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def request(self, boundary):
        return self.provider.request(None, 'GET', 'https://' + boundary + '.b9a.invalid/test')

    def wire(self):
        return rows(self.folder/'test-wire.jsonl')

    def test_uncertain_only_meta_and_llm_remains_two_successful_calls(self):
        import requests
        self.assertEqual(self.request('llm'), 'get_service_catalog')
        self.assertEqual(self.request('llm'), 'answer')
        with self.assertRaises(requests.Timeout):
            self.request('meta')
        wire = self.wire()
        self.assertTrue(ep.verify_wire(self.job, wire, [10])['passed'])
        self.assertEqual([r['boundary'] for r in wire if r.get('result') == 'UNCERTAIN'], ['meta'])
        self.assertEqual([c.args[0] for c in self.sleeper.call_args_list], [.5, .5, .2])
        self.assertEqual(len({r['call_id'] for r in wire}), 3)

    def test_other_org_meta_and_internal_domain_are_not_faulted(self):
        self.meta.organization_id = 2
        self.assertIn('messages', self.request('meta'))
        result = self.provider.request(None, 'GET', 'http://b9a.internal.test/test')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([c.args[0] for c in self.sleeper.call_args_list], [.2, .1])
        self.assertTrue(ep.verify_wire(self.job, self.wire(), [])['passed'])

    def test_slow_meta_keeps_llm_delay_and_meta_multiplier(self):
        self.job['variant'] = 'slow_meta'
        self.request('llm')
        self.request('meta')
        self.assertEqual([c.args[0] for c in self.sleeper.call_args_list], [.5, .4])

    def test_fault_scope_requires_case_variant_org_and_boundary(self):
        for case, variant, boundary, org in [('R1-03', 'uncertain_meta', 'meta', 1), ('R2-09', 'slow_meta', 'meta', 1),
                                             ('R2-09', 'uncertain_meta', 'llm', 1), ('R2-09', 'uncertain_meta', 'meta', 2)]:
            self.assertFalse(ep.uncertain_target(dict(self.job, case_id=case, variant=variant), boundary, org))

    def test_admission_and_containment_fail_closed(self):
        self.meta.send_admitted_at = None
        with self.assertRaisesRegex(AssertionError, 'committed send admission'):
            self.request('meta')
        self.calls.filter.return_value.first.return_value = None
        with self.assertRaisesRegex(AssertionError, 'exclusive admitted claim'):
            self.request('llm')
        with self.assertRaisesRegex(AssertionError, 'External destination'):
            self.provider.request(None, 'GET', 'https://example.com')
        self.connection.in_atomic_block = True
        with self.assertRaisesRegex(AssertionError, 'HTTP under transaction'):
            self.request('llm')

    def test_witness_corruption_and_missing_service_are_rejected(self):
        self.request('llm')
        original = self.wire()
        self.assertIn('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS', ep.verify_wire(self.job, original, [10, 11])['issues'])
        for key, value in [('boundary', 'meta'), ('result', 'UNCERTAIN'), ('call_id', 'wrong'), ('turn_work_id', 99)]:
            bad = copy.deepcopy(original)
            bad[-1][key] = value
            self.assertFalse(ep.verify_wire(self.job, bad, [10])['passed'], key)
        self.assertFalse(ep.verify_wire(self.job, original + [original[-1]], [10])['passed'])

    def test_overlay_restores_original_provider_even_on_error(self):
        original = object()
        execution = SimpleNamespace(Provider=original)
        with self.assertRaises(RuntimeError):
            with ep.installed(execution):
                self.assertIs(execution.Provider, ep.Provider)
                raise RuntimeError('test cleanup')
        self.assertIs(execution.Provider, original)


class ClockTests(unittest.TestCase):
    def good_rows(self):
        return rows(PRIOR/'individual/individual-R103-unequal/ingress.jsonl')

    def test_old_valid_captures_remain_mathematically_valid(self):
        for role in ('ingress', 'planner_1', 'planner_2', 'sender'):
            state = cg.Continuity()
            for row in rows(PRIOR/'individual/individual-R103-unequal'/(role+'.jsonl')):
                state.feed(row)
            self.assertTrue(state.finish()['mathematical_relation_valid'])

    def test_all_four_old_broken_captures_still_fail(self):
        for role in ('ingress', 'planner_1', 'planner_2', 'sender'):
            state = cg.Continuity()
            with self.assertRaisesRegex(cg.ClockInvalid, 'INVALID_CLOCK_RELATION'):
                for row in rows(PRIOR/'matrix-existing/matrix-existing-R103-unequal'/(role+'.jsonl')):
                    state.feed(row)
            with self.assertRaises(cg.ClockInvalid):
                state.finish()

    def test_identity_sequence_missing_footer_and_backwards_time_rejected(self):
        sample = self.good_rows()
        for key, value in [('os_pid', -1), ('seq', 999), ('monotonic_ns', 0)]:
            state = cg.Continuity()
            state.feed(sample[0])
            with self.assertRaises(cg.ClockInvalid):
                state.feed(dict(sample[1], **{key: value}))
        state = cg.Continuity()
        state.feed(sample[0])
        with self.assertRaises(cg.ClockInvalid):
            state.finish()

    def test_idle_guard_restores_on_exception_without_calling_windows(self):
        calls = []
        def api(value):
            calls.append(value)
            return 0x80000002
        with self.assertRaises(RuntimeError):
            with cg.prevent_idle_sleep(api):
                raise RuntimeError('cleanup')
        self.assertEqual(calls, [0x80000001, 0x80000002])
        with self.assertRaisesRegex(cg.ClockInvalid, 'NOT_ACQUIRED'):
            with cg.prevent_idle_sleep(lambda flags: 0):
                self.fail('failed guard entered')

    def test_host_step_sleep_and_log_loss_rejected(self):
        before = dict(last_record_id=100)
        after = dict(last_record_id=102, oldest_record_id=10, after_record_id=100, events=[])
        self.assertTrue(cg.verify_host_cuts(before, after)['host_event_window_valid'])
        for provider, event_id in [('Microsoft-Windows-Kernel-General', 1), ('Microsoft-Windows-Kernel-Power', 42),
                                    ('Microsoft-Windows-Kernel-Power', 107), ('Microsoft-Windows-Power-Troubleshooter', 1)]:
            bad = dict(after, events=[dict(provider=provider, id=event_id, record_id=101)])
            with self.assertRaises(cg.ClockInvalid):
                cg.verify_host_cuts(before, bad)
        for change in [dict(oldest_record_id=101), dict(last_record_id=99), dict(after_record_id=99), dict(error='denied')]:
            with self.assertRaises(cg.ClockInvalid):
                cg.verify_host_cuts(before, dict(after, **change))

    def test_monitor_detects_invalid_capture_and_latches_stop(self):
        with tempfile.TemporaryDirectory(prefix='d29-offline-clock-') as temp:
            directory = Path(temp)
            data = self.good_rows()[:2]
            data[1]['seq'] = 500
            (directory/'ingress.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in data))
            monitor = cg.JournalMonitor(directory, ('ingress',))
            monitor.start()
            monitor.thread.join(timeout=2)
            with self.assertRaises(cg.ClockInvalid):
                monitor.close()
            self.assertTrue((directory/'stop').exists())
            self.assertEqual(json.loads((directory/'clock-invalid.json').read_text())['status'], 'INVALID_RUN')


class FixtureTests(unittest.TestCase):
    def test_base_is_unchanged_and_window_alignment_does_not_shorten_lease(self):
        plan = rf.base_plan(BASE)
        self.assertEqual(plan['conversations_per_org'], 3)
        self.assertEqual((plan['offer_seconds'], plan['followup_seconds']), (360, 240))
        anchor = rf.anchor_window(plan, 900_000_000_000)
        self.assertEqual(anchor['natural_expiry_db_ns'], 900_000_000_000)
        self.assertEqual(anchor['end_db_ns'] - anchor['start_db_ns'], 360_000_000_000)
        self.assertLess(anchor['start_db_ns'], anchor['natural_expiry_db_ns'])
        self.assertLess(anchor['natural_expiry_db_ns'], anchor['end_db_ns'])

    def test_changed_base_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='d29-offline-base-') as temp:
            path = Path(temp)/'base.json'
            path.write_bytes(BASE.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'IMMUTABLE_BASE_CHANGED'):
                rf.base_plan(path)

    def test_calendar_or_one_sided_offers_do_not_prove_reclaim_overlap(self):
        window = dict(begin_cut=dict(db_ns=10), end_cut=dict(db_ns=100), natural_expiry_db_ns=50)
        def offer(org, msg, at):
            return dict(organization_id=org, message_id=msg, phase='ORDINARY', outcome='ACCEPTED_DURABLE', offered_db_ns_bounds=[at, at+1])
        actual = [offer(1, 1, 20), offer(2, 2, 30), offer(1, 3, 60), offer(2, 4, 70)]
        result = rf.verify_overlap(window, [51, 52], actual, [1, 2], 99)
        self.assertTrue(result['passed'])
        self.assertFalse(result['accreditation'])
        for offers, bounds in [([], [51, 52]), (actual[:2], [51, 52]), (actual, [49, 50]), (actual, [99, 100])]:
            self.assertFalse(rf.verify_overlap(window, bounds, offers, [1, 2], 99)['passed'])
        planned = dict(start_db_ns=10, end_db_ns=100, natural_expiry_db_ns=50)
        self.assertFalse(rf.verify_overlap(planned, [51, 52], actual, [1, 2], 99)['passed'])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    target = HERE / sys.argv[1]
    target.mkdir(exist_ok=False)
    (target/'tests.log').write_text(stream.getvalue(), encoding='utf-8')
    receipt = dict(scope='OFFLINE_EVALUATION_INFRASTRUCTURE_TESTS', tests=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   passed=result.wasSuccessful(), physical_runs=0, database_opened=False,
                   windows_power_api_called=False, synthetic_evidence=True, physical_accreditation=False)
    receipt['source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
    (target/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(stream.getvalue())
    print(json.dumps(receipt))
    raise SystemExit(not result.wasSuccessful())
