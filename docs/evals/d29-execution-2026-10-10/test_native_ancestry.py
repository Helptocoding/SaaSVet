import copy
import unittest
from native_ancestry import validate


class NativeAncestryTests(unittest.TestCase):
    def setUp(self):
        self.launch=dict(launcher_pid=1,launcher_creation_filetime=100)
        self.identity=dict(os_pid=3,parent_pid=2,process_creation_filetime=120,monotonic_ns=20)
        rows=[dict(pid=3,parent=2,name='python.exe'),dict(pid=2,parent=1,name='python.exe')]
        self.samples=[dict(monotonic_ns=t,processes=copy.deepcopy(rows)) for t in (30,40)]
    def check(self,samples=None):return validate(self.launch,self.identity,self.samples if samples is None else samples,50)
    def test_native_transitive_venv_parent_path(self):
        r=self.check();self.assertTrue(r['passed']);self.assertEqual([p['pid'] for p in r['native_chain']],[3,2])
    def test_native_direct_parent_path(self):
        self.identity['parent_pid']=1
        for s in self.samples:s['processes']=[dict(pid=3,parent=1,name='python.exe')]
        self.assertTrue(self.check()['passed'])
    def test_single_or_historical_snapshot_rejected(self):
        self.assertFalse(self.check(self.samples[:1])['passed'])
        for s in self.samples:s['monotonic_ns']=10
        self.assertFalse(self.check()['passed'])
    def test_missing_intermediate_is_not_inferred(self):
        for s in self.samples:s['processes']=s['processes'][:1]
        self.assertFalse(self.check()['passed'])
    def test_cycle_rejected(self):
        for s in self.samples:s['processes'][1]['parent']=3
        self.assertFalse(self.check()['passed'])
    def test_changed_or_mismatching_parent_rejected(self):
        self.samples[1]['processes'][0]['parent']=1
        self.assertFalse(self.check()['passed'])
    def test_creation_order_required(self):
        self.identity['process_creation_filetime']=90
        self.assertFalse(self.check()['passed'])


if __name__=='__main__':unittest.main()
