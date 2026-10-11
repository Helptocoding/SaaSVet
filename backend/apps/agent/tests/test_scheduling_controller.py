"""Failure-driven tests of adaptive control, evidence gates and recipe boundaries."""
import json
import tempfile
import unittest
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from apps.agent.tests.scheduling_characterization.assessment import disposition, window_gate
from apps.agent.tests.scheduling_characterization.controller import Controller, Parameters, digest, seal_plan, validate_plan
from apps.agent.tests.scheduling_characterization.execution import LiveBackend, queued_samples
from apps.agent.tests.scheduling_characterization.recipes import RECIPES, verify_recipe
from apps.agent.tests.scheduling_characterization.replay import ReplayBackend, level_fixture, recipe_fixture, schedule


class ControllerTests(unittest.TestCase):
    def run_model(self, backend=None, cases=('R1-01',), parameters=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        plan = seal_plan('finite', cases, parameters=parameters, reason='fixture' if parameters else None,
                         evidence='unit-history' if parameters else None)
        engine = Controller(plan, backend or ReplayBackend(), Path(tmp.name) / 'new-series')
        return engine, engine.run()

    def test_refinement_and_three_confirmations_use_new_run_ids(self):
        engine, result = self.run_model()
        self.assertEqual(result['status'], 'CONTROLLER_COMPLETE')
        self.assertTrue(any(j['plan']['phase'] == 'REFINE' for j in engine.jobs))
        self.assertEqual(len([j for j in engine.jobs if j['plan']['phase'] == 'CONFIRM']), 3)
        self.assertEqual(len({j['plan']['run_id'] for j in engine.jobs}), len(engine.jobs))
        self.assertFalse(result['benchmark_executed'])
        self.assertIsNone(result['sustainable_envelope'])
        self.assertFalse(result['contract_accepted'])

    def test_one_failed_confirmation_discards_set_and_confirms_lower_candidate(self):
        backend = ReplayBackend(threshold=10., confirmation_failures={('R1-01', 9., 2)})
        engine, result = self.run_model(backend)
        self.assertEqual(result['confirmed']['R1-01']['rates'], [6.])
        self.assertEqual(result['confirmed']['R1-01']['bracket'], [6., 9.])
        self.assertEqual(result['confirmed']['R1-01']['confirmation_rejected_rates'], [9.])
        confirm = [j['plan'] for j in engine.jobs if j['plan']['phase'] == 'CONFIRM']
        self.assertEqual([(j['offered_rates_per_minute'][0], j['repetition']) for j in confirm],
                         [(9., 1), (9., 2), (6., 1), (6., 2), (6., 3)])

    def test_indeterminate_stops_without_bumping_rate_or_relabeling(self):
        backend = ReplayBackend(indeterminate_at=2)
        engine, result = self.run_model(backend)
        self.assertEqual(result['status'], 'CONTROLLER_STOPPED')
        self.assertEqual(len(engine.jobs), 2)
        self.assertEqual(result['completed_cases'], [])
        self.assertIn('INDETERMINATE', engine.jobs[-1]['receipt']['model_dispositions'])

    def test_no_upper_frontier_is_not_maximum_capacity(self):
        _, result = self.run_model(ReplayBackend(threshold=1000.), parameters=replace(Parameters(), max_levels=2))
        self.assertEqual(result['status'], 'CONTROLLER_COMPLETE')
        self.assertFalse(result['confirmed']['R1-01']['located_frontier'])

    def test_first_incompatible_level_cannot_be_confirmed(self):
        engine, result = self.run_model(ReplayBackend(threshold=1.))
        self.assertEqual(result['status'], 'CONTROLLER_STOPPED')
        self.assertNotIn('CONFIRM', [j['plan']['phase'] for j in engine.jobs])

    def test_all_17_cases_and_all_variants_are_prepared_and_replayed(self):
        engine, result = self.run_model(cases=tuple(RECIPES))
        self.assertEqual(result['status'], 'CONTROLLER_COMPLETE')
        for case, recipe in RECIPES.items():
            variants = {j['plan']['variant'] for j in engine.jobs if j['plan']['case_id'] == case}
            self.assertEqual(variants, set(recipe.variants))
        for job in engine.jobs:
            self.assertEqual(job['receipt']['source_kind'], 'SYNTHETIC_REPLAY')
            self.assertNotIn('OBSERVED_COMPATIBLE', job['receipt']['dispositions'])

    def test_unequal_case_preserves_confirmed_balanced_global_offer(self):
        engine, result = self.run_model(cases=('R1-02', 'R1-03'))
        unequal = next(j['plan'] for j in engine.jobs if j['plan']['case_id'] == 'R1-03')
        a, b = unequal['offered_rates_per_minute']
        self.assertAlmostEqual(a, 2 * b)
        self.assertAlmostEqual(a + b, sum(result['confirmed']['R1-02']['rates']))

    def test_plan_tampering_and_source_drift_are_rejected(self):
        plan = seal_plan('sealed', ['R1-01'])
        plan['bound_seconds'] = 121
        with self.assertRaises(ValueError):
            validate_plan(plan)
        plan['plan_sha256'] = digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_adaptive_parameters_require_prospective_reason_and_evidence(self):
        with self.assertRaises(ValueError):
            seal_plan('changed', ['R1-01'], parameters=replace(Parameters(), max_levels=9))
        plan = seal_plan('changed', ['R1-01'], parameters=replace(Parameters(), max_levels=9),
                         reason='frontier not located', evidence='previous-run')
        self.assertEqual(validate_plan(plan).max_levels, 9)
        self.assertEqual(plan['bound_seconds'], 120)

    def test_invalid_parameters_and_missing_base_are_rejected(self):
        for params in (replace(Parameters(), multiplier=1), replace(Parameters(), max_levels=True),
                       replace(Parameters(), initial_fraction=float('nan')), replace(Parameters(), screen_seconds=120)):
            with self.assertRaises(ValueError):
                params.validate()
        with self.assertRaises(ValueError):
            seal_plan('no-base', ['R2-04'])
        with self.assertRaises(ValueError):
            seal_plan('wrong-order', ['R2-04', 'R1-02'])

    def test_last_refinement_step_can_finish_within_declared_bracket(self):
        _, result = self.run_model(parameters=replace(Parameters(), max_refinements=1))
        self.assertEqual(result['status'], 'CONTROLLER_COMPLETE')

    def test_reused_output_cannot_overwrite_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = seal_plan('unique', ['R1-01'])
            output = Path(tmp) / 'series'
            Controller(plan, ReplayBackend(), output)
            with self.assertRaises(FileExistsError):
                Controller(plan, ReplayBackend(), output)

    def test_foreign_receipt_or_live_replay_mixture_stops(self):
        class Foreign(ReplayBackend):
            def execute(self, job):
                r = super().execute(job)
                r['run_id'] = 'foreign'
                return r
        _, result = self.run_model(Foreign())
        self.assertEqual(result['reason'], 'RECEIPT_ID_OR_SEALED_JOB_MISMATCH')
        class Mixed(ReplayBackend):
            def execute(self, job):
                r = super().execute(job)
                r['source_kind'] = 'ISOLATED_LIVE'
                return r
        _, result = self.run_model(Mixed())
        self.assertEqual(result['reason'], 'RECEIPT_PROVENANCE_MISMATCH')


class EvidenceGateTests(unittest.TestCase):
    def fixture(self, case='R1-02', variant='balanced', duration=360):
        plan = dict(case_id=case, variant=variant, run_id='test', organization_count=2,
                    offered_rates_per_minute=[6., 6.], offer_seconds=duration, followup_seconds=240,
                    burst_seconds=120, burst_multiplier=2., blocked_llm_hold_seconds=120,
                    boundary_case=False, job_sha256='fixture')
        return plan, level_fixture(plan)

    def test_pending_and_unknown_never_pass(self):
        plan, _ = self.fixture()
        report = level_fixture(plan, pending=True)
        self.assertNotEqual(report['model_dispositions'], ['OBSERVED_COMPATIBLE'])
        self.assertIn('OBSERVED_INCOMPATIBLE_WITH_TARGET', report['model_dispositions'])
        report = level_fixture(plan, clock_error=True)
        self.assertIn('INDETERMINATE', report['model_dispositions'])

    def test_coalesced_messages_are_not_the_declared_episode_load(self):
        plan, _ = self.fixture()
        report = level_fixture(plan, coalesced=True)
        self.assertIn('INVALID_RUN', report['model_dispositions'])
        self.assertIn('COALESCED_DEMAND_NOT_DECLARED_READY_EPISODE_LOAD', report['gates']['demand']['violations'])

    def test_one_organization_growth_is_not_hidden_by_global_average(self):
        plan, report = self.fixture()
        queues = [dict(offset_seconds=i * 120, counts={'1': [i, i], '2': [3-i, 3-i], 'global': [3, 3]}, correlated_clock=True) for i in range(4)]
        gate = window_gate(plan, report, queues, [1, 2])
        self.assertEqual(gate['backlog']['1'], 'OBSERVED_BACKLOG_GROWTH')
        self.assertEqual(gate['backlog']['global'], 'NO_GROWTH_OBSERVED')

    def test_partial_confirmation_window_is_kept_and_does_not_count_as_full(self):
        plan, report = self.fixture(duration=900)
        offsets = [0, 120, 240, 360, 480, 600, 720, 840, 900]
        queues = [dict(offset_seconds=t, counts={'1': [0, 0], '2': [0, 0], 'global': [0, 0]}, correlated_clock=True) for t in offsets]
        gate = window_gate(plan, report, queues, [1, 2])
        self.assertFalse(gate['missing'])
        queues.pop()
        self.assertIn('QUEUE_CUTS_NOT_COMPLETE_OR_ALIGNED', window_gate(plan, report, queues, [1, 2])['missing'])

    def test_late_missing_duplicate_or_foreign_offer_fails_demand(self):
        from apps.agent.tests.scheduling_characterization.assessment import demand_gate
        plan, report = self.fixture()
        slots = schedule(plan)
        offers = [dict(schedule_id=s['id'], outcome='ACCEPTED_DURABLE', message_id=i+1,
                       organization_id=s['organization_index']+1, started_monotonic_ns=s['due_monotonic_ns']+1) for i, s in enumerate(slots)]
        # The raw population used here is deliberately incomplete: it must
        # never be healed by the schedule or a nominal rate assertion.
        offers[0]['started_monotonic_ns'] = slots[0]['end_monotonic_ns']
        offers[0]['message_id'] = 999
        gate = demand_gate(plan, report, offers, slots, [1, 2], (0, 360 * 10**9))
        self.assertTrue(any('MISSED_PACING' in v for v in gate['violations']))
        self.assertIn('POPULATION_NOT_CONSERVED', gate['missing'])
        offers.pop()
        self.assertTrue(any('MISSING_OR_DUPLICATE' in v for v in demand_gate(plan, report, offers, slots, [1, 2], (0, 1))['violations']))

    def test_invariant_failure_overrides_complete_timing(self):
        _, report = self.fixture()
        gates = deepcopy(report['gates'])
        gates['invariants']['violations'].append('N1_OR_OWNERSHIP_AT_DISPATCH')
        labels = disposition(report, gates, synthetic=True)['model_dispositions']
        self.assertIn('INVARIANT_FAILURE', labels)
        self.assertNotIn('OBSERVED_COMPATIBLE', labels)

    def test_no_service_witness_cannot_pass(self):
        _, report = self.fixture()
        gates = deepcopy(report['gates'])
        gates['invariants']['missing'].append('SERVICE_COST_NOT_OBSERVED')
        self.assertIn('INDETERMINATE', disposition(report, gates, synthetic=True)['model_dispositions'])

    def test_fault_observation_never_approves_fault_contract_coverage(self):
        _, report = self.fixture('R2-01', 'slow')
        self.assertEqual(report['model_dispositions'], ['FAULT_OBSERVATION_COMPLETE_COVERAGE_PENDING'])
        self.assertFalse(report['contract_accepted'])

    def test_burst_schedule_has_two_rates_and_returns_to_base(self):
        plan, _ = self.fixture('R1-05', 'concentrated')
        slots = schedule(plan)
        counts = {o: sum(s['organization_index'] == o for s in slots) for o in (0, 1)}
        self.assertEqual(counts, {0: 48, 1: 36})
        first = [s for s in slots if s['organization_index'] == 0]
        self.assertEqual(first[0]['end_monotonic_ns'] - first[0]['due_monotonic_ns'], 5 * 10**9)
        self.assertEqual(first[-1]['end_monotonic_ns'] - first[-1]['due_monotonic_ns'], 10 * 10**9)


class RecipeTests(unittest.TestCase):
    def test_every_recipe_requires_observed_boundaries(self):
        for case, recipe in RECIPES.items():
            for variant in recipe.variants:
                plan = dict(case_id=case, variant=variant, run_id='recipe', organization_count=2,
                            burst_seconds=120, blocked_llm_hold_seconds=120)
                events = recipe_fixture(plan)
                self.assertFalse(verify_recipe(plan, events)['missing'], (case, variant))
                self.assertTrue(verify_recipe(plan, events[:-1])['missing'], (case, variant))

    def test_natural_recovery_cannot_be_replaced_by_shortened_lease(self):
        plan = dict(case_id='R2-04', variant='postcommit', run_id='r', organization_count=2)
        events = recipe_fixture(plan)
        next(e for e in events if e['event'] == 'natural_expiry')['runtime_clock_or_deadline_changed'] = True
        self.assertIn('RECOVERY_FRONTIER_ARTIFICIALLY_ADVANCED', verify_recipe(plan, events)['violations'])

    def test_retry_reset_and_stale_effect_are_invariant_failures(self):
        plan = dict(case_id='R2-04', variant='postcommit', run_id='r', organization_count=2)
        events = recipe_fixture(plan)
        next(e for e in events if e['event'] == 'same_work_reclaimed')['budget_reset'] = True
        next(e for e in events if e['event'] == 'old_witness_fenced')['effect_published'] = True
        violations = verify_recipe(plan, events)['violations']
        self.assertIn('RECOVERY_BUDGET_RESET_OR_UNKNOWN', violations)
        self.assertIn('STALE_WITNESS_PUBLISHED_OR_UNKNOWN', violations)

    def test_lost_ack_requires_independent_resolution(self):
        plan = dict(case_id='R2-07', variant='lost_ack', run_id='r', organization_count=2)
        events = recipe_fixture(plan)
        events[1]['observed'] = False
        self.assertIn('SCENARIO_BOUNDARY_UNACCREDITED:independent_visibility', verify_recipe(plan, events)['missing'])

    def test_foreign_run_and_reordered_events_cannot_satisfy_recipe(self):
        plan = dict(case_id='R2-03', variant='precommit', run_id='r', organization_count=2)
        events = recipe_fixture(plan)
        for e in events:
            e['run_id'] = 'foreign'
        self.assertTrue(verify_recipe(plan, events)['missing'])
        events = recipe_fixture(plan)[::-1]
        self.assertTrue(verify_recipe(plan, events)['missing'])

    def test_deadline_variants_and_safety_after_require_their_own_boundary(self):
        plan = dict(case_id='R1-07', variant='deadline_after', run_id='r', organization_count=2)
        events = recipe_fixture(dict(plan, variant='w1_w2'))
        self.assertIn('SCENARIO_BOUNDARY_NOT_OBSERVED:accepted_after_deadline', verify_recipe(plan, events)['missing'])
        plan = dict(case_id='R2-08', variant='safety_after', run_id='r', organization_count=2)
        events = recipe_fixture(dict(plan, variant='safety_before'))
        self.assertIn('SCENARIO_BOUNDARY_NOT_OBSERVED:ordinary_claim_committed', verify_recipe(plan, events)['missing'])


class ExecutionGuardTests(unittest.TestCase):
    def test_missing_live_adapter_stops_before_database_allocation(self):
        backend = LiveBackend('test_schema', Path('unused'))
        plan = seal_plan('matrix', list(RECIPES))
        with patch('apps.agent.tests.scheduling_characterization.execution.verify_sources') as verify:
            with self.assertRaisesRegex(ValueError, 'Live injection adapters required'):
                backend.preflight(plan)
            verify.assert_not_called()

    def test_cli_rejects_modified_source_before_any_db_or_load(self):
        from apps.agent.tests.scheduling_characterization.runner import BASELINE
        with tempfile.TemporaryDirectory() as tmp:
            job = dict(baseline=BASELINE, bound_seconds=120, source_hashes={'forged.py': 'bad'})
            job['job_sha256'] = digest(job)
            path = Path(tmp) / 'job.json'
            path.write_text(json.dumps(job), encoding='utf-8')
            result = subprocess.run(['rtk', 'proxy', sys.executable, '-X', 'utf8', '-m',
                'apps.agent.tests.scheduling_characterization.execution', 'finite-probe', '--job', str(path),
                '--output', str(Path(tmp) / 'new')], capture_output=True, text=True,
                env=dict(os.environ, B3_TEST_DATABASE='{}'), timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Job sources changed after sealing', result.stderr)
            self.assertFalse((Path(tmp) / 'new').exists())


if __name__ == '__main__':
    unittest.main()
