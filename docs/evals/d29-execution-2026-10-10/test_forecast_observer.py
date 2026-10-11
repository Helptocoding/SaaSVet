"""Reject nonnative or ineligible prequery predicate before any physical trial."""
import copy
import unittest
from forecast_observer import eligible,qualifies_yield,find_arm


class ForecastPredicateTests(unittest.TestCase):
    def setUp(self):
        self.arm=dict(waiter=1,future=2)
        self.pre=dict(db_ns=1_000_000_000,messages=[
            dict(id=1,organization_id=1,status='pending',turn_work_id=None,available_at='1970-01-01T00:00:00+00:00'),
            dict(id=2,organization_id=2,status='pending',turn_work_id=None,available_at='1970-01-01T00:00:01.500000+00:00')],
            works=[dict(organization_id=1,status='COMPLETED',claimed_at='1970-01-01T00:00:00+00:00')])
    def test_ready_future_and_actual_prior_service(self):
        self.assertTrue(eligible(self.pre,self.arm))
    def test_future_at_or_outside_horizon_rejected(self):
        for due in ('1970-01-01T00:00:01+00:00','1970-01-01T00:00:02.000001+00:00'):
            p=copy.deepcopy(self.pre);p['messages'][1]['available_at']=due
            self.assertFalse(eligible(p,self.arm))
    def test_waiter_claimed_or_not_ready_rejected(self):
        for change in (dict(turn_work_id=3),dict(available_at='1970-01-01T00:00:01.1+00:00')):
            p=copy.deepcopy(self.pre);p['messages'][0].update(change)
            self.assertFalse(eligible(p,self.arm))
    def test_busy_or_peer_recent_service_rejected(self):
        p=copy.deepcopy(self.pre);p['works'][0]['status']='PROCESSING';self.assertFalse(eligible(p,self.arm))
        p=copy.deepcopy(self.pre);p['works'].append(dict(organization_id=2,status='COMPLETED',claimed_at='1970-01-01T00:00:00+00:00'))
        self.assertFalse(eligible(p,self.arm))
    def test_only_successful_native_empty_poll_end_can_signal(self):
        observation=dict(conversation_ids=[],eligible=True)
        self.assertTrue(qualifies_yield('poll_end',dict(outcome='returned'),observation))
        self.assertFalse(qualifies_yield('selection_end',dict(outcome='returned'),observation))
        self.assertFalse(qualifies_yield('poll_end',dict(outcome='error'),observation))
        self.assertFalse(qualifies_yield('poll_end',dict(outcome='returned'),dict(conversation_ids=[1],eligible=True)))
        self.assertFalse(qualifies_yield('poll_end',dict(outcome='returned'),dict(conversation_ids=[],eligible=False)))
    def test_dynamic_discovery_uses_actual_ready_future_and_recency(self):
        self.assertEqual(find_arm(self.pre),self.arm)
        p=copy.deepcopy(self.pre)
        p['works'].append(dict(organization_id=2,status='COMPLETED',claimed_at='1969-12-31T23:59:59+00:00'))
        self.assertEqual(find_arm(p),self.arm)
        p['messages'][0]['direction']='out'
        self.assertIsNone(find_arm(p))


if __name__=='__main__':unittest.main()
