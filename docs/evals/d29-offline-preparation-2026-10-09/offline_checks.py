"""Only pure offline verifier tests. No Django setup, databases or services."""
from copy import deepcopy
import json
import sys
import unittest

from common import HERE, PRIOR, save, sha, utc
from r106_verifier import NS, Interval, classify, reconcile, verify_directory


def model():
    """Synthetic verifier model; never evidence of physical capacity/load."""
    episodes = []
    for wid, members, ready, claim in ((1,[1,2],1,2),(2,[3],5,6)):
        episodes.append(dict(episode_id=str(wid),organization_id=1,conversation_id=1,
                             member_ids=members,ready_ns_bounds=[ready*NS]*2,
                             claim_commit_ns_bounds=[claim*NS]*2,turn_work_id=wid,issues=[]))
    report = dict(episodes=episodes,issues=[],uncertain_transactions=[],cut_ns_bounds=[20*NS]*2,
                  population={'accepted_durable_inputs':3})
    messages = [dict(id=i,organization_id=1,conversation_id=1,direction='in',semantic_type='ordinary',
                     turn_work_id=1 if i<3 else 2) for i in (1,2,3)]
    messages.append(dict(id=4,organization_id=1,conversation_id=1,direction='out',turn_work_id=2,
                         provider_accepted_at='observed',send_admitted_at='observed'))
    works = [dict(id=i,organization_id=1,conversation_id=1,status='COMPLETED',ownership_epoch=i,
                  llm_calls_admitted=2,lease_fingerprint=str(i),
                  anchor_message_id=2 if i==1 else 3,anchor_created_at='1970-01-01T00:00:02+00:00' if i==1 else '1970-01-01T00:00:03+00:00',
                  outcome_code='deferred_to_new_input' if i==1 else 'completed') for i in (1,2)]
    wire=[]
    for wid in (1,2):
        for num in (1,2):
            d=dict(event='dispatch',call_id=str(wid)+':'+str(num),run_id='OFFLINE_SYNTHETIC',role='planner',os_pid=1,
                   boundary='llm',organization_id=1,turn_work_id=wid,call_number=num,epoch=wid,
                   lease_fingerprint=str(wid),db_ns=(2 if wid==1 else 6)*NS+num*NS,
                   monotonic_ns=wid*NS+num*NS,external_destination=False,in_atomic=False,admission_verified=True)
            wire.extend([d,dict(d,event='result',result='ACCEPTED',monotonic_ns=d['monotonic_ns']+NS//2,elapsed_ns=NS//2)])
    d=dict(event='dispatch',call_id='meta',run_id='OFFLINE_SYNTHETIC',role='sender',os_pid=2,
           boundary='meta',organization_id=1,message_id=4,monotonic_ns=10*NS,
           external_destination=False,in_atomic=False,admission_verified=True)
    wire.extend([d,dict(d,event='result',result='ACCEPTED',monotonic_ns=10*NS+NS//5,elapsed_ns=NS//5)])
    ledger=[dict(id=wid*2+n,turn_work_id=wid,organization_id=1,conversation_id=1,
                 admitted_at='observed',recorded_at='observed',error='') for wid in (1,2) for n in (1,2)]
    base=dict(turn_work_id=1,organization_id=1,conversation_id=1,epoch=1,lease_fingerprint='1',transaction_identity=['session','tx'])
    guard=dict(base,has_new_input=True,new_input_ids=[3],observed_ns_bounds=[4*NS]*2,
               anchor_message_id=2,anchor_created_at='1970-01-01T00:00:02+00:00',input_creation_cursors={'3':[3*NS,3]},
               input_commit_ns_bounds={'3':[3*NS]*2})
    terminal=dict(base,outcome_code='deferred_to_new_input',cas_affected=1,observed_ns_bounds=[4*NS+1]*2,commit_ns_bounds=[4*NS+2]*2)
    context=dict(turn_work_id=2,organization_id=1,conversation_id=1,epoch=2,lease_fingerprint='2',
                 phase='BEFORE_FIRST_LLM',capture_boundary='ACTUAL_PACKED_CONTEXT',consumed_input_ids=[1,2,3],observed_ns_bounds=[6*NS+1]*2)
    return report,messages,works,wire,ledger,([guard],[terminal],[context])


class ReconciliationControls(unittest.TestCase):
    def setUp(self):
        self.b = model()

    def codes(self):
        return reconcile(*self.b)['errors']

    def require(self, prefix):
        self.assertTrue(any(e.startswith(prefix) for e in self.codes()), self.codes())

    def test_positive_model_is_verifier_only(self):
        self.assertEqual(self.codes(), [])
        self.assertEqual(reconcile(*self.b)['counts']['inputs'],3)
        self.assertEqual(reconcile(*self.b)['counts']['episodes'],2)

    def test_lost_input(self):
        self.b[0]['episodes'][0]['member_ids'].remove(2)
        self.require('INPUT_POPULATION_NOT_CONSERVED')

    def test_originless_episode(self):
        self.b[0]['episodes'][0]['ready_ns_bounds']=[None,None]
        self.require('EPISODE_WITHOUT_ORIGIN')

    def test_age_reset(self):
        self.b[0]['episodes'][0]['ready_ns_bounds']=[2*NS]*2
        r=reconcile(*self.b,origins={'1':[NS]*2})
        self.assertIn('ORIGINAL_READY_CHANGED:1',r['errors'])

    def test_reconstructed_retraction_remains_failure(self):
        self.b[0]['issues'].append('READY_RETRACTED_BY_DEADLINE')
        self.require('READY_RETRACTED_BY_DEADLINE')

    def test_claim_without_witness(self):
        self.b[3][:]=[r for r in self.b[3] if r.get('turn_work_id')!=1]
        self.require('CLAIMED_WORK_WITHOUT_SERVICE_WITNESS')

    def test_deferral_without_successor(self):
        self.b[5][0][0]['new_input_ids']=[99]
        self.require('DEFERRAL_SUCCESSOR_NOT_DEMONSTRATED')

    def test_later_response_is_not_sufficient(self):
        self.b[5][2].clear()
        self.require('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED')

    def test_prior_inputs_not_consumed(self):
        self.b[5][2][0]['consumed_input_ids']=[3]
        self.require('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED')

    def test_guard_without_native_witness(self):
        self.b[5][0].clear()
        self.require('DEFERRAL_NATIVE_GUARD_OR_COMMIT_MISSING')

    def test_guard_wrong_transaction(self):
        self.b[5][0][0]['transaction_identity']=['other','tx']
        self.require('DEFERRAL_CAUSAL_WITNESS_INVALID')

    def test_trigger_after_guard(self):
        self.b[5][0][0]['input_commit_ns_bounds']['3']=[5*NS]*2
        self.require('DEFERRAL_TRIGGER_COMMIT_NOT_PROVEN')

    def test_successor_claim_before_terminal_commit(self):
        self.b[5][1][0]['commit_ns_bounds']=[7*NS]*2
        self.require('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED')

    def test_context_after_service(self):
        self.b[5][2][0]['observed_ns_bounds']=[9*NS]*2
        self.require('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED')

    def test_uncertain_not_accepted(self):
        self.b[3][-1]['result']='UNCERTAIN'
        self.require('OUTPUT_ACCEPTANCE_NOT_PROVEN')

    def test_accepted_wire_without_durable_acceptance(self):
        self.b[1][-1]['provider_accepted_at']=None
        self.require('OUTPUT_ACCEPTANCE_NOT_PROVEN')

    def test_121_seconds_rejected(self):
        self.b[0]['episodes'][0]['claim_commit_ns_bounds']=[122*NS]*2
        self.require('BOUND_OR_ORIGIN_NOT_ACCREDITED:1:OBSERVED_EXCESS')

    def test_interval_crossing_120_not_pass(self):
        self.b[0]['episodes'][0]['claim_commit_ns_bounds']=[120*NS,122*NS]
        self.require('BOUND_OR_ORIGIN_NOT_ACCREDITED:1:INDETERMINATE')

    def test_120_seconds_inclusive_unchanged(self):
        self.assertEqual(classify(Interval(NS,NS),Interval(121*NS,121*NS),Interval(122*NS,122*NS))['disposition'],'OBSERVED_WITHIN_TARGET')

    def test_cross_organization(self):
        self.b[1][0]['organization_id']=2
        self.require('INPUT_MEMBERSHIP_OR_SCOPE_INVALID')

    def test_service_cost_not_invented(self):
        self.b[3][1]['elapsed_ns']=1
        self.require('BASE_LLM_COST_NOT_COMPLETELY_OBSERVED')

    def test_wire_duplicate(self):
        self.b[3].append(deepcopy(self.b[3][0]))
        self.require('DISPATCH_RESULT_NOT_ONE_TO_ONE')

    def test_available_history_is_not_consumed_context(self):
        self.b[5][2][0]['capture_boundary']='LATER_HISTORY_QUERY'
        self.require('DEFERRAL_SUCCESSOR_CONTEXT_NOT_DEMONSTRATED')

    def test_terminal_cas_not_successful(self):
        self.b[5][1][0]['cas_affected']=0
        self.require('DEFERRAL_CAUSAL_WITNESS_INVALID')

    def test_old_input_cannot_trigger_native_new_input(self):
        self.b[5][0][0]['input_creation_cursors']['3']=[NS,3]
        self.require('DEFERRAL_TRIGGER_NOT_AFTER_NATIVE_ANCHOR')


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    receipt=dict(at_utc=utc(),source_kind='OFFLINE_SYNTHETIC_VERIFIER_CONTROLS',physical_accreditation=False,
                 test_count=result.testsRun,failures=[{'test':str(t),'trace':s} for t,s in result.failures],
                 errors=[{'test':str(t),'trace':s} for t,s in result.errors],passed=result.wasSuccessful(),
                 source_sha256={p.name:sha(p) for p in HERE.glob('*.py')},execution_authorized=False)
    attempts=list(HERE.glob('offline-tests-attempt-*.json'))
    save('offline-tests-attempt-%02d.json'%(len(attempts)+1),receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)
