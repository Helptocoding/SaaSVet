"""Fast offline validation of causal brackets and ambiguous wait attribution."""
from datetime import datetime, timezone
from unittest import TestCase

from apps.agent.claim_diagnostic_report import attach_waits, reconstruct


class ClaimDiagnosticReportingTests(TestCase):
    def journal(self, session='s1'):
        base = dict(session_id=session, run_id='fixture', transaction_id='tx',
                    backend_pid=12, connection_id='c1', worker='planner',
                    savepoint_ids=[], organization_id=2, conversation_id=3,
                    attempt_id='a1', seq=0, monotonic_ns=0)
        def row(event, **data):
            return dict(base, event=event, **data)
        return [
            row('poll_start', poll_id='p1', monotonic_ns=100),
            row('selection_start', selection_id='sel', span_id='sel', monotonic_ns=200),
            row('selection_end', selection_id='sel', span_id='sel', monotonic_ns=300),
            row('claim_start', monotonic_ns=400),
            row('db_clock', db_timestamp='2026-10-03T12:00:10+00:00', start_ns=500, end_ns=600),
            row('membership_candidate', message_id=1, created_at='2026-10-03T12:00:00+00:00',
                available_at='2026-10-03T12:00:08+00:00'),
            row('claim_bound', turn_work_id=4, epoch=0, attempts=1, lease_fingerprint='hash',
                claimed_at='2026-10-03T12:00:10+00:00', selection_id='sel', poll_id='p1'),
            row('commit_end', monotonic_ns=700, error_class=None),
        ]

    def test_clock_uncertainty_is_preserved_and_history_is_not_inferred(self):
        report = reconstruct([self.journal()])
        claim = report['claims'][0]
        metric = claim['message_timelines'][0]
        self.assertEqual(metric['persisted_to_eligible_seconds'], 8)
        self.assertEqual(metric['persisted_to_claimed_at_seconds'], 10)
        lo, hi = metric['eligible_to_selection_seconds_bounds']
        self.assertLessEqual(lo, 2)
        self.assertLessEqual(hi, 2)
        self.assertLessEqual(lo, hi)
        self.assertFalse(report['acceptance_run'])
        self.assertEqual(report['historical_turnwork_86_causality'], 'NOT_INFERRED')
        self.assertEqual(claim['ingress_source'], 'NOT_OBSERVED')

    def test_wait_crossing_queries_is_ambiguous_and_unobserved_is_not_zero(self):
        claim = dict(session_id='s', connection_id='c', backend_pid=10,
            claim_sql=[dict(session_id='s', query_id=1, execute_start_ns=100,
                            execute_end_ns=200, duration_ns=100),
                       dict(session_id='s', query_id=2, execute_start_ns=205,
                            execute_end_ns=300, duration_ns=95)], selection_sql=[])
        report = dict(run_id='run', claims=[claim])
        sample = dict(run_id='run', session_id='s', connection_id='c', backend_pid=10,
            sample_start_ns=190, sample_end_ns=220, wait_event_type='Lock', blocking_pids=[9])
        result = attach_waits(report, [sample])['waits']
        self.assertEqual(len(result['ambiguous']), 1)
        self.assertEqual(result['matched'], [])
        self.assertIsNone(result['exact_lock_wait_seconds'])
        sample.update(sample_start_ns=120, sample_end_ns=150)
        result = attach_waits(report, [sample])['waits']
        self.assertEqual(result['matched'][0]['query_id'], 1)
        self.assertEqual(result['lock_queries'][0]['lock_wait_total_ns_bounds'], [0,100])
        sample['connection_id'] = 'different-connection'
        self.assertEqual(len(attach_waits(report, [sample])['waits']['unassigned']), 1)

    def test_mixed_runs_are_rejected(self):
        journal = self.journal('s2')
        journal[0]['run_id'] = 'other'
        with self.assertRaises(ValueError):
            reconstruct([self.journal(), journal])

    def test_effective_eligibility_does_not_precede_new_member_persistence(self):
        journal = self.journal()
        member = next(r for r in journal if r['event'] == 'membership_candidate')
        member['created_at'] = '2026-10-03T12:00:09+00:00'
        metric = reconstruct([journal])['claims'][0]['message_timelines'][0]
        self.assertEqual(metric['persisted_to_eligible_seconds'], 0)
        self.assertEqual(metric['persisted_to_claimed_at_seconds'], 1)

    def test_savepoint_attempt_requires_successful_acknowledgement(self):
        for error, expected in ((None, 'rolled_back'), ('RuntimeError', 'committed')):
            journal = self.journal()
            bound = next(r for r in journal if r['event'] == 'claim_bound')
            bound['savepoint_ids'] = ['sp']
            journal[-1:-1] = [dict(bound, event='savepoint_rollback', savepoint_id='sp'),
                dict(bound, event='savepoint_rollback_end', savepoint_id='sp', error_class=error)]
            self.assertEqual(reconstruct([journal])['claims'][0]['status'], expected)
        # A marker without any acknowledgement must not overrule a real COMMIT.
        journal.pop(-2)
        self.assertEqual(reconstruct([journal])['claims'][0]['status'], 'committed')
