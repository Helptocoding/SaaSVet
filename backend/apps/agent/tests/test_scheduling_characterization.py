"""Measurement failure modes and population conservation; no app/DB setup."""
import unittest
from datetime import datetime,timezone

from apps.agent.tests.scheduling_characterization.evidence import (
    NS,Interval,backlog_disposition,classify,reconstruct,transactions)
from apps.agent.tests.scheduling_characterization.runner import validate_level_plan,BASELINE


def iso(seconds):
    return datetime.fromtimestamp(seconds,tz=timezone.utc).isoformat()


class JournalFixture:
    def __init__(self,session='s'):
        self.session=session
        self.rows=[]
        self.add('db_clock',at=0,start_ns=0,end_ns=0,db_timestamp=iso(1000))

    def add(self,event,at=0,tx=None,**data):
        row=dict(event=event,run_id='test',session_id=self.session,transaction_id=tx,
                 monotonic_ns=int(at*NS),savepoint_ids=[],**data)
        self.rows.append(row)
        return row

    def ingress(self,mid,at=1,deadline=10,conv=1,org=1,tx=None):
        tx=tx or 'i'+str(mid)
        self.add('message_persisted',at=at,tx=tx,message_id=mid,organization_id=org,
                 conversation_id=conv,available_at=iso(1000+deadline) if deadline is not None else None)
        self.add('deadline_set',at=at,tx=tx,organization_id=org,conversation_id=conv,
                 available_at=iso(1000+deadline) if deadline is not None else None)
        self.commit(tx,at)

    def commit(self,tx,at,error=None):
        return self.add('commit_end',at=at,tx=tx,execute_start_ns=int(at*NS),
                        execute_end_ns=int(at*NS),error_class=error)

    def claim(self,members,at=20,conv=1,org=1,work=1,tx='c',error=None):
        row=self.add('claim_bound',at=at,tx=tx,organization_id=org,conversation_id=conv,
                     turn_work_id=work,member_ids=members,attempts=1)
        self.commit(tx,at,error)
        return row


def offered(*ids):
    return [dict(outcome='ACCEPTED_DURABLE',message_id=i) for i in ids]


def census(*rows):
    return [dict(id=mid,direction='in',semantic_type='',organization_id=org,conversation_id=conv)
            for mid,org,conv in rows]


def report(journal,offers,rows,cut=1050,resolutions=()):
    return reconstruct([journal.rows],offers,rows,Interval(int(cut*NS),int(cut*NS)),
                       run_id='test',resolutions=resolutions)


class TemporalEvidenceTests(unittest.TestCase):
    def test_interval_crossing_bound_is_indeterminate(self):
        r=classify(Interval(0,0),Interval(int(119.8*NS),int(120.2*NS)),Interval(121*NS,121*NS))
        self.assertEqual(r['disposition'],'INDETERMINATE')

    def test_exact_bound_is_within_but_any_proven_excess_fails(self):
        self.assertEqual(classify(Interval(0,0),Interval(120*NS,120*NS),Interval(121*NS,121*NS))['disposition'],'OBSERVED_WITHIN_TARGET')
        self.assertEqual(classify(Interval(0,0),Interval(120*NS+1,121*NS),Interval(122*NS,122*NS))['disposition'],'OBSERVED_EXCESS')

    def test_young_pending_never_passes(self):
        self.assertEqual(classify(Interval(0,0),None,Interval(NS,NS))['disposition'],'PENDING_CENSORED')

    def test_never_claimed_old_episode_exceeds(self):
        self.assertEqual(classify(Interval(0,NS),None,Interval(122*NS,122*NS))['disposition'],'OBSERVED_EXCESS')

    def test_unknown_origin_cannot_pass(self):
        self.assertEqual(classify(Interval(None,None),Interval(NS,NS),Interval(2*NS,2*NS))['disposition'],'INDETERMINATE')

    def test_invalid_clock_never_credits_bound(self):
        self.assertEqual(classify(Interval(0,0),Interval(NS,NS),Interval(2*NS,2*NS),valid=False)['disposition'],'INVALID_EVIDENCE')


class CohortTests(unittest.TestCase):
    def test_population_starts_before_claim_and_keeps_unserved_org(self):
        j=JournalFixture(); j.ingress(1); j.ingress(2,conv=2,org=2); j.claim([1])
        r=report(j,offered(1,2),census((1,1,1),(2,2,2)))
        self.assertEqual(len(r['episodes']),2)
        self.assertEqual(r['summary']['PENDING_CENSORED'],1)
        self.assertEqual(r['organization_counts'],{'1':1,'2':1})
        self.assertNotIn('OBSERVED_COMPATIBLE',r['dispositions'])

    def test_correction_does_not_reset_ready_and_w2_has_own_origin(self):
        j=JournalFixture(); j.ingress(1); j.ingress(2,at=15,deadline=10); j.claim([1,2],at=20)
        j.ingress(3,at=21,deadline=30); j.claim([3],at=40,work=2,tx='c2')
        r=report(j,offered(1,2,3),census((1,1,1),(2,1,1),(3,1,1)))
        self.assertEqual([e['member_ids'] for e in r['episodes']],[[1,2],[3]])
        self.assertEqual([e['ready_ns_bounds'][0]/NS for e in r['episodes']],[1010,1030])
        self.assertFalse(r['issues'])

    def test_deadline_extension_before_ready_changes_origin(self):
        j=JournalFixture(); j.ingress(1); j.ingress(2,at=5,deadline=15); j.claim([1,2])
        r=report(j,offered(1,2),census((1,1,1),(2,1,1)))
        self.assertEqual(r['episodes'][0]['ready_ns_bounds'],[1015*NS,1015*NS])

    def test_null_legacy_starts_at_ingress_commit(self):
        j=JournalFixture(); j.ingress(1,deadline=None); j.claim([1])
        r=report(j,offered(1),census((1,1,1)))
        self.assertEqual(r['episodes'][0]['ready_ns_bounds'],[1001*NS,1001*NS])

    def test_duplicate_is_not_a_new_obligation(self):
        j=JournalFixture(); j.ingress(1)
        r=report(j,offered(1)+[dict(outcome='DUPLICATE_CONFIRMED',message_id=1)],census((1,1,1)))
        self.assertEqual(len(r['episodes']),1)
        self.assertEqual(r['population']['technical_duplicates'],1)

    def test_outer_rollback_cannot_end_episode(self):
        j=JournalFixture(); j.ingress(1); j.claim([1])
        j.rows.pop(); j.add('rollback_end',tx='c',error_class=None)
        r=report(j,offered(1),census((1,1,1)))
        self.assertEqual(r['summary']['PENDING_CENSORED'],1)

    def test_savepoint_rollback_does_not_hide_outer_commit(self):
        j=JournalFixture(); j.ingress(1); candidate=j.claim([1]); candidate['savepoint_ids']=['sp']
        j.rows.pop()
        j.add('savepoint_rollback',tx='c',savepoint_id='sp')
        j.add('savepoint_rollback_end',tx='c',savepoint_id='sp',error_class=None)
        j.commit('c',20)
        r=report(j,offered(1),census((1,1,1)))
        self.assertEqual(r['summary']['PENDING_CENSORED'],1)

    def test_failed_commit_followed_by_rollback_is_not_proven_rollback(self):
        j=JournalFixture(); j.ingress(1); j.claim([1],error='DatabaseError')
        j.add('rollback_end',tx='c',error_class=None)
        r=report(j,offered(1),census((1,1,1)))
        self.assertEqual(r['summary']['PENDING_CENSORED'],1)
        self.assertEqual(r['uncertain_transactions'][0]['reason'],'COMMIT_ACK_UNRESOLVED')

    def test_independent_visibility_resolves_lost_ack_and_supplies_upper_bound(self):
        j=JournalFixture(); j.ingress(1); j.claim([1],error='DatabaseError'); j.add('rollback_end',tx='c',error_class=None)
        resolution=dict(session_id='s',transaction_id='c',result='COMMITTED',witness_verified=True,visible_by_db_ns=1030*NS)
        r=report(j,offered(1),census((1,1,1)),resolutions=[resolution])
        self.assertEqual(r['episodes'][0]['claim_commit_ns_bounds'],[1020*NS,1030*NS])
        self.assertFalse(r['uncertain_transactions'])

    def test_reclaim_does_not_close_w2_or_add_episode(self):
        j=JournalFixture(); j.ingress(1); j.claim([1]); j.ingress(2,at=21,deadline=30)
        j.claim(None,at=40,work=1,tx='recover')
        r=report(j,offered(1,2),census((1,1,1),(2,1,1)))
        self.assertEqual(len(r['episodes']),2)
        self.assertEqual(r['summary']['PENDING_CENSORED'],1)
        self.assertEqual(len(r['recovery']),1)

    def test_missing_accepted_ingress_retains_obligation(self):
        r=report(JournalFixture(),offered(1),census((1,1,1)))
        self.assertEqual(len(r['episodes']),1)
        self.assertIn('ACCEPTED_INPUT_ORIGIN_NOT_RECONSTRUCTED:1',r['issues'])

    def test_clock_step_invalidates_without_resetting_age(self):
        j=JournalFixture(); j.ingress(1); j.add('db_clock',at=30,start_ns=30*NS,end_ns=30*NS,db_timestamp=iso(1040))
        r=report(j,offered(1),census((1,1,1)))
        self.assertIn('INVALID_CLOCK_RELATION',r['issues'])
        self.assertNotIn('OBSERVED_COMPATIBLE',r['dispositions'])

    def test_full_cohort_alone_does_not_certify_load(self):
        j=JournalFixture(); j.ingress(1); j.claim([1])
        r=report(j,offered(1),census((1,1,1)))
        self.assertEqual(r['dispositions'],['COHORT_ONLY_NOT_LEVEL_ACCEPTANCE'])

    def test_foreign_run_and_duplicate_session_cannot_supply_evidence(self):
        j=JournalFixture(); j.ingress(1); j.claim([1])
        for row in j.rows:
            row['run_id']='foreign'
        r=report(j,offered(1),census((1,1,1)))
        self.assertIn('CAPTURE_RUN_MISMATCH',r['issues'])
        for row in j.rows:
            row['run_id']='test'
        r=reconstruct([j.rows,j.rows],offered(1),census((1,1,1)),Interval(1050*NS,1050*NS),run_id='test')
        self.assertIn('DUPLICATE_CAPTURE_SESSION',r['issues'])

    def test_cross_tenant_membership_fails_reconciliation(self):
        j=JournalFixture(); j.ingress(1); j.claim([1],org=2)
        r=report(j,offered(1),census((1,1,1)))
        self.assertIn('MEMBERSHIP_NOT_RECONCILED:1',r['issues'])


class BacklogAndPlanTests(unittest.TestCase):
    def test_three_increasing_windows_fail(self):
        self.assertEqual(backlog_disposition([[0,0],[1,1],[2,2],[3,3]]),'OBSERVED_BACKLOG_GROWTH')

    def test_partial_window_does_not_complete_three_full_windows(self):
        self.assertEqual(backlog_disposition([[0,0],[1,1],[2,2],[3,3]],[True,True,False]),'INDETERMINATE')

    def test_net_growth_or_uncertain_counts_do_not_pass(self):
        self.assertEqual(backlog_disposition([[0,0],[1,1],[0,0],[1,1]]),'INDETERMINATE')
        self.assertEqual(backlog_disposition([[0,1],[0,1]]),'INDETERMINATE')

    def test_balanced_plan_validates_but_fake_acceptance_and_unknown_case_fail(self):
        plan=dict(case_id='R1-02',baseline=BASELINE,protocol_version='D29-v1',
                  conversations_per_org=3,offered_rates_per_minute=[1.,1.],offer_seconds=360)
        self.assertEqual(validate_level_plan(plan),plan)
        with self.assertRaises(ValueError):
            validate_level_plan(dict(plan,invariants_accredited=True))
        with self.assertRaises(ValueError):
            validate_level_plan(dict(plan,case_id='R2-04'))


if __name__=='__main__':
    unittest.main()
