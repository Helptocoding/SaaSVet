"""Regressions for raw-capture adapter failures; no physical model PASS."""
import unittest
import r106_verifier
from native_verifier_bridge import canonical_works, installed


class VerifierBridgeControls(unittest.TestCase):
    def test_original_wrong_call_shape_is_reproducible(self):
        with self.assertRaises(TypeError):
            r106_verifier._savepoint_rolled_back(dict(event='work_terminal',savepoint_ids=[]),
                                               [dict(event='commit_end')])

    def test_acknowledged_savepoint_rollback_still_rejects_witness(self):
        bound = dict(event='work_terminal',savepoint_ids=['sp'])
        events = [dict(event='savepoint_rollback',savepoint_id='sp'),
                  dict(event='savepoint_rollback_end',savepoint_id='sp',error_class=None)]
        with installed():
            self.assertTrue(r106_verifier._savepoint_rolled_back(bound,events))
            self.assertFalse(r106_verifier._savepoint_rolled_back(dict(savepoint_ids=[]),events))

    def test_failed_savepoint_rollback_is_not_invented(self):
        events = [dict(event='savepoint_rollback',savepoint_id='sp'),
                  dict(event='savepoint_rollback_end',savepoint_id='sp',error_class='DatabaseError')]
        with installed():
            self.assertFalse(r106_verifier._savepoint_rolled_back(dict(savepoint_ids=['sp']),events))

    def test_timezone_and_separator_preserve_exact_instant(self):
        raw = [dict(anchor_created_at='2026-10-10 10:24:31.376731-06:00')]
        self.assertEqual(canonical_works(raw)[0]['anchor_created_at'],'2026-10-10T16:24:31.376731+00:00')
        self.assertEqual(raw[0]['anchor_created_at'],'2026-10-10 10:24:31.376731-06:00')
        changed = [dict(anchor_created_at='2026-10-10 10:24:31.376732-06:00')]
        self.assertNotEqual(canonical_works(raw),canonical_works(changed))

    def test_missing_timezone_fails_closed(self):
        with self.assertRaises(ValueError):
            canonical_works([dict(anchor_created_at='2026-10-10 10:24:31')])


if __name__ == '__main__':
    unittest.main()
