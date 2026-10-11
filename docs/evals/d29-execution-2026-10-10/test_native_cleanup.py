import unittest
from native_cleanup import validate,participant_exit


class NativeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.exits=[dict(pid=i,exit_code=0) for i in (1,2,3)]
        self.after=[dict(stage='after',processes=[dict(pid=9)])]
        self.execution=dict(clients_after_child=[],database_removed=True)
    def check(self):return validate(self.exits,[4,5,6],self.after,self.execution)
    def test_all_native_cleanup_evidence_required(self):self.assertTrue(self.check()['all_reaped'])
    def test_present_child_or_missing_snapshot_rejected(self):
        self.after[0]['processes'].append(dict(pid=5));self.assertFalse(self.check()['all_reaped'])
        self.after=[];self.assertFalse(self.check()['all_reaped'])
    def test_failed_exit_or_remaining_database_client_rejected(self):
        self.exits[0]['exit_code']=1;self.assertFalse(self.check()['all_reaped'])
        self.exits[0]['exit_code']=0;self.execution['clients_after_child']=[dict(pid=7)]
        self.assertFalse(self.check()['all_reaped'])
    def test_participant_capture_requires_native_process_and_backend_exit(self):
        self.assertTrue(participant_exit(self.exits,[4,5,6],[dict(pid=9)],[])['all_reaped'])
        self.assertFalse(participant_exit(self.exits,[4,5,6],[dict(pid=5)],[])['all_reaped'])
        self.assertFalse(participant_exit(self.exits,[4,5,6],[dict(pid=9)],[7])['all_reaped'])
