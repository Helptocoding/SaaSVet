"""Offline negative controls for inactive clock/fixture/temporal protocols."""
from copy import deepcopy
from fractions import Fraction as F
import json
import sys
import unittest

from common import HERE, PRIOR, lines, read, save, sha, utc
from clock_recovery_protocol import recovery_action, safe_start
from offline_checks import ReconciliationControls, model
from r104_temporal import feasible_chain
from r106_verifier import NS, Interval, invariant_gate, load_clock_guard, population_gate, reconstruct, transactions
from r209_preparation import definite_overlap, initial_cohort_gate, plan, provider_gate, validate_plan


class ClockControls(unittest.TestCase):
    def setUp(self):
        self.before={'state':'RUNNING','start_type':'AUTOMATIC','host_scope_authorized':True,'main_restore_access_verified':True}
        self.helper={k:True for k in ('own_restore_access_verified','separate_process','ready_ack','durable_lease',
                                     'parent_pid_creation_time_verified','restore_deadline_registered','state_readable',
                                     'outside_main_kill_job_verified')}

    def test_safe_start_model(self):
        self.assertTrue(safe_start(self.before,self.helper)['may_start'])

    def test_every_missing_precondition_blocks(self):
        for k in self.helper:
            with self.subTest(k=k):
                helper=dict(self.helper,**{k:False})
                self.assertFalse(safe_start(self.before,helper)['may_start'])

    def test_permission_missing_blocks(self):
        self.before['main_restore_access_verified']=False
        self.assertFalse(safe_start(self.before,self.helper)['may_start'])

    def test_no_approval_blocks(self):
        self.before['host_scope_authorized']=False
        self.assertFalse(safe_start(self.before,self.helper)['may_start'])

    def test_pending_service_state_blocks(self):
        self.before['state']='START_PENDING'
        self.assertFalse(safe_start(self.before,self.helper)['may_start'])

    def test_all_exit_paths_restore_intent(self):
        for reason in ('NORMAL','ERROR','INTERRUPTION','PARENT_DIED','DEADLINE_EXCEEDED'):
            with self.subTest(reason=reason):
                self.assertEqual(recovery_action(self.before,reason=reason,currently='STOPPED')['action'],'RESTORE_RUNNING')

    def test_restore_idempotent(self):
        self.assertTrue(recovery_action(self.before,reason='NORMAL',currently='RUNNING')['restored'])

    def test_preserve_original_stopped(self):
        self.before['state']='STOPPED'
        self.assertEqual(recovery_action(self.before,reason='ERROR',currently='RUNNING')['action'],'RESTORE_STOPPED')

    def test_pid_reuse_not_liveness(self):
        self.assertTrue(recovery_action(self.before,reason='PARENT_DIED',currently='STOPPED',same_parent_identity=False)['parent_pid_reuse_not_used_as_liveness'])

    def test_clock_step_gate_not_relaxed(self):
        guard=load_clock_guard();state=guard.Continuity()
        base={'run_id':'SYNTHETIC','worker':'ingress','os_pid':1,'session_id':'s'}
        state.feed(dict(base,event='capture_start',seq=1,monotonic_ns=0))
        state.feed(dict(base,event='db_clock',seq=2,monotonic_ns=10,start_ns=0,end_ns=10,db_timestamp='1970-01-01T00:00:01+00:00'))
        with self.assertRaises(guard.ClockInvalid):
            state.feed(dict(base,event='db_clock',seq=3,monotonic_ns=30,start_ns=20,end_ns=30,db_timestamp='1970-01-01T00:00:02+00:00'))


class TemporalControls(unittest.TestCase):
    def setUp(self):
        def at(s):return [F(s)]*2
        self.geometry=dict(ready=at('24'),cap=at('25'),old_deadline=at('24.5'),prequery=at('24.1'),
                           yield_end=at('24.15'),correction_db_now=at('24.18'),correction_commit=at('24.2'),
                           corrected_deadline=at('25'),miss_poll=at('24.7'),corrected_claim=at('25.1'),waiter_claim=at('26'))

    def test_conditional_geometry_never_physical_pass(self):
        result=feasible_chain(**self.geometry)
        self.assertTrue(result['interval_constraints_satisfied'])
        self.assertFalse(result['physical_accreditation'])

    def test_commit_late(self):
        self.geometry['correction_commit']=[F('24.6')]*2
        self.assertIn('CORRECTION_NOT_COMMITTED_BEFORE_OLD_DEADLINE',feasible_chain(**self.geometry)['errors'])

    def test_correction_before_yield(self):
        self.geometry['correction_commit']=[F('24.12')]*2
        self.assertIn('CORRECTION_NOT_AFTER_YIELD',feasible_chain(**self.geometry)['errors'])

    def test_clock_uncertainty_closes_window(self):
        self.geometry['correction_commit']=[F('24.2'),F('24.6')]
        self.assertFalse(feasible_chain(**self.geometry)['interval_constraints_satisfied'])

    def test_eight_second_projection_gap_rejected(self):
        self.geometry['cap']=self.geometry['corrected_deadline']=[F('32.2')]*2
        self.assertIn('CORRECTED_FORECAST_CAN_LEAVE_H_AFTER_W_READY',feasible_chain(**self.geometry)['errors'])

    def test_unknown_bound_cannot_pass(self):
        self.geometry['yield_end']=[None,None]
        self.assertFalse(feasible_chain(**self.geometry)['interval_constraints_satisfied'])

    def test_later_query_does_not_prove_old_forecast_miss(self):
        self.geometry['miss_poll']=[F('25.2')]*2
        self.assertIn('OLD_FORECAST_MISS_NOT_OBSERVED_BEFORE_CAP',feasible_chain(**self.geometry)['errors'])

    def test_correction_native_clock_before_yield(self):
        self.geometry['correction_db_now']=[F('24.1')]*2
        self.assertIn('CORRECTION_NATIVE_NOW_NOT_AFTER_YIELD',feasible_chain(**self.geometry)['errors'])


class MetaPreparationControls(unittest.TestCase):
    def test_both_plan_variants(self):
        for v in ('uncertain_meta','slow_meta'):
            self.assertTrue(validate_plan(plan(v))['offline_plan_valid'])

    def test_no_added_population(self):
        p=plan('slow_meta');p['initial_cohort'].append(deepcopy(p['initial_cohort'][0]))
        self.assertFalse(validate_plan(p)['offline_plan_valid'])

    def test_no_multiplier_increase(self):
        p=plan('slow_meta');p['provider_parameters']['slow_multiplier']=3
        self.assertFalse(validate_plan(p)['offline_plan_valid'])

    def test_plan_cannot_authorize_itself(self):
        p=plan('uncertain_meta');p['execution_authorized']=True
        self.assertFalse(validate_plan(p)['offline_plan_valid'])

    def test_definite_overlap(self):
        self.assertEqual(definite_overlap([1,2],[9,10],[3,4],[7,8],[0,20]),[4,7])

    def test_possible_overlap_only_rejected(self):
        self.assertIsNone(definite_overlap([1,2],[5,9],[4,6],[7,8],[0,20]))

    def test_outside_base_offer_rejected(self):
        self.assertIsNone(definite_overlap([1,2],[9,10],[3,4],[7,8],[10,20]))

    def cohort(self):
        eps=[{'organization_id':o,'conversation_id':c,'member_ids':[o*10+c],
              'ready_ns_bounds':[1,2],'claim_commit_ns_bounds':[10,11]} for o in (1,2) for c in (1,2,3)]
        ids=[e['member_ids'][0] for e in eps]
        launch=[{'role':'planner_'+str(i),'start_ns_bounds':[6,7],'hold_after_start':False} for i in (1,2)]
        return eps,ids,[3,4],launch,{'ready_ns_bounds':[4,5]},{1:[1,2,3],2:[1,2,3]}

    def test_prestart_positive_model_only(self):
        self.assertEqual(initial_cohort_gate(*self.cohort())['errors'],[])

    def test_sender_started_late(self):
        args=list(self.cohort());args[4]={'ready_ns_bounds':[7,8]}
        self.assertIn('SENDER_NOT_PREPARED_BEFORE_PLANNERS',initial_cohort_gate(*args)['errors'])

    def test_worker_prestart_claim_rejected(self):
        args=list(self.cohort());args[0][0]['claim_commit_ns_bounds']=[2,3]
        self.assertIn('INITIAL_EPISODE_ALREADY_CLAIMED_AT_CUT',initial_cohort_gate(*args)['errors'])

    def test_artificial_hold_rejected(self):
        args=list(self.cohort());args[3][0]['hold_after_start']=True
        self.assertIn('ARTIFICIAL_POSTSTART_HOLD',initial_cohort_gate(*args)['errors'])

    def meta_model(self):
        report,messages,works,wire,ledger,causal=model()
        outbox=[m for m in messages if m['direction']=='out']
        outbox[0]['provider_accepted_at']=None
        for row in wire[-2:]:
            row['fault_id']=row['call_id']+':uncertain-meta';row['injected_fault']='UNCERTAIN_META'
        wire[-1]['result']='UNCERTAIN'
        return wire,works,outbox,'uncertain_meta',1

    def test_meta_only_fault(self):
        self.assertEqual(provider_gate(*self.meta_model())['errors'],[])

    def test_injection_cannot_timeout_llm(self):
        args=list(self.meta_model());args[0][1]['result']='UNCERTAIN'
        self.assertIn('META_INJECTION_CONTAMINATED_LLM',provider_gate(*args)['errors'])

    def test_no_llm_witness(self):
        args=list(self.meta_model());args[0]=[r for r in args[0] if r.get('turn_work_id')!=1]
        self.assertIn('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS_OR_ORPHAN_SERVICE',provider_gate(*args)['errors'])

    def test_meta_wrong_outbox(self):
        args=list(self.meta_model());args[2][0]['id']=999
        self.assertIn('META_DISPATCH_OUTBOX_ADMISSION_NOT_CORRELATED',provider_gate(*args)['errors'])

    def test_uncertain_not_accepted(self):
        args=list(self.meta_model());args[2][0]['provider_accepted_at']='invented'
        self.assertIn('UNCERTAIN_OUTPUT_COUNTED_AS_ACCEPTED',provider_gate(*args)['errors'])

    def test_blind_retry_detected(self):
        args=list(self.meta_model());repeat=deepcopy(args[0][-2:])
        for r in repeat:r['call_id']='retry';r['fault_id']='retry:uncertain-meta'
        args[0].extend(repeat)
        self.assertIn('BLIND_RETRY_OR_DUPLICATE_DISPATCH',provider_gate(*args)['errors'])

    def test_fault_id_correlates_exact_call(self):
        args=list(self.meta_model())
        for row in args[0][-2:]:row['fault_id']='unrelated'
        self.assertIn('FAULT_OUTSIDE_DECLARED_META_FRONTIER',provider_gate(*args)['errors'])


class UnchangedRawInvariantControls(unittest.TestCase):
    """Corrupt copies in memory only; never rewrite a historical capture."""
    @classmethod
    def setUpClass(cls):
        cls.directory=PRIOR/'r1-06/authorized-r106-2x4-20261007-0002'
        cls.final=read(cls.directory/'full-durable-final.json')
        cls.journals=[lines(cls.directory/(r+'.jsonl')) for r in ('ingress','planner_1','planner_2','sender')]
        cls.offers=lines(cls.directory/'schedule-offers.jsonl')
        cls.report=reconstruct(cls.journals,cls.offers,cls.final['messages'],Interval(cls.final['db_ns'],cls.final['db_ns']),run_id='OFFLINE_RAW_MUTATION_CONTROL')
        cls.dispatches=[r for role in ('planner_1','planner_2','sender') for r in lines(cls.directory/(role+'-wire.jsonl')) if r['event']=='dispatch']

    def invariant_errors(self, **change):
        wire=deepcopy(self.dispatches)
        first=next(r for r in wire if r['boundary']=='llm');first.update(change)
        gate=invariant_gate(self.report,self.journals,self.final['messages'],self.final['works'],wire,[1,2])
        return gate['missing']+gate['violations']

    def test_original_native_witnesses_read_only(self):
        self.assertEqual(self.invariant_errors(),[])

    def test_n1_not_relaxed(self):
        self.assertIn('N1_OR_OWNERSHIP_AT_DISPATCH',self.invariant_errors(active_org_work=2))

    def test_http_transaction_not_relaxed(self):
        self.assertIn('HTTP_UNDER_TRANSACTION',self.invariant_errors(in_atomic=True))

    def test_containment_not_relaxed(self):
        self.assertIn('UNCONTAINED_DESTINATION',self.invariant_errors(external_destination=True))

    def test_admission_not_relaxed(self):
        self.assertIn('DURABLE_WIRE_ADMISSION_NOT_WITNESSED',self.invariant_errors(admission_verified=False))

    def test_outer_commit_not_relaxed(self):
        self.assertIn('DISPATCH_BEFORE_RESOLVED_OUTER_COMMIT',self.invariant_errors(db_ns=0))

    def test_wrong_epoch_not_relaxed(self):
        self.assertIn('DISPATCH_BEFORE_RESOLVED_OUTER_COMMIT',self.invariant_errors(epoch=999))

    def test_wrong_population_phase_not_accepted(self):
        population=lines(self.directory/'population-slots.jsonl')
        population[-1]['slot']=3
        pre=next(c for c in lines(self.directory/'snapshots.jsonl') if c['stage']=='backlog_ready_before_workers')
        self.assertIn('FOURTH_SLOT_USED_FOR_ORDINARY_OFFER',population_gate(population,self.offers,self.final['messages'],pre,[1,2])['errors'])


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    receipt={'at_utc':utc(),'source_kind':'OFFLINE_SYNTHETIC_VERIFIER_AND_PREPARATION_CONTROLS',
             'physical_accreditation':False,'passed':result.wasSuccessful(),'tests':result.testsRun,
             'failures':[{'test':str(t),'trace':s} for t,s in result.failures],
             'errors':[{'test':str(t),'trace':s} for t,s in result.errors],
             'source_sha256':{p.name:sha(p) for p in HERE.glob('*.py')},
             'service_mutations':0,'physical_probes':0,'application_suites':0}
    attempts=list(HERE.glob('preparation-tests-attempt-*.json'))
    save('preparation-tests-attempt-%02d.json'%(len(attempts)+1),receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)
