"""Fail-closed tests of physical evidence, never synthetic accreditation."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from apps.agent.tests.scheduling_characterization.physical import ADAPTERS, same_history, verify_receipt
from apps.agent.tests.scheduling_characterization.recipes import RECIPES
from apps.agent.tests.scheduling_characterization.runner import BASELINE


class PhysicalEvidenceTests(unittest.TestCase):
    def fixture(self, **changes):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)
        cleanup=dict(all_reaped=True)
        (p/'participants-cleanup.json').write_text(json.dumps(cleanup),encoding='utf-8')
        r=dict(baseline=BASELINE,source_kind='PHYSICAL_POSTGRESQL',case_id='R2-03',variant='precommit',run_id='test',
            organization_count=2,events=[],checks=[],error=None,artifacts={'participants-cleanup.json':hashlib.sha256((p/'participants-cleanup.json').read_bytes()).hexdigest()})
        r.update(changes);(p/'receipt.json').write_text(json.dumps(r),encoding='utf-8');return p

    def test_exact_eight_registry_and_all_25_variants(self):
        self.assertEqual(set(ADAPTERS),{'R1-07','R2-03','R2-04','R2-05','R2-06','R2-07','R2-08','R2-10'})
        self.assertEqual(sum(len(RECIPES[c].variants) for c in ADAPTERS),25)

    def test_empty_model_pass_never_accredits(self):
        p=self.fixture(status='PASS');r=verify_receipt(p)
        self.assertEqual(r['status'],'NOT_ACCREDITED')
        self.assertIn('INVARIANT_FAILURE_OR_ABSENT',r['errors'])
        self.assertTrue(any('BOUNDARY_NOT_OBSERVED' in e for e in r['errors']))

    def test_replay_provenance_never_accredits(self):
        self.assertIn('WRONG_PROVENANCE',verify_receipt(self.fixture(source_kind='SYNTHETIC_REPLAY'))['errors'])

    def test_tampered_artifact_refused(self):
        p=self.fixture();(p/'participants-cleanup.json').write_text('{"all_reaped":false}',encoding='utf-8')
        r=verify_receipt(p);self.assertIn('ARTIFACT_MISMATCH:participants-cleanup.json',r['errors']);self.assertIn('PARTICIPANT_LEAK',r['errors'])

    def test_runtime_error_retained(self):
        self.assertIn('EXECUTION_ERROR',verify_receipt(self.fixture(error={'message':'fault'}))['errors'])

    def test_same_history_rejects_budget_reset(self):
        keys=('id','organization_id','conversation_id','ownership_epoch','context_at','anchor_message_id','anchor_created_at',
            'cursor_message_id','cursor_created_at','llm_call_limit','llm_output_token_limit')
        a=dict.fromkeys(keys,1);a.update(llm_calls_admitted=2,llm_output_tokens_reserved=1200)
        b=dict(a,llm_calls_admitted=0,llm_output_tokens_reserved=0)
        self.assertFalse(same_history(a,b))

    def test_same_history_rejects_membership_anchor_change(self):
        keys=('id','organization_id','conversation_id','ownership_epoch','context_at','anchor_message_id','anchor_created_at',
            'cursor_message_id','cursor_created_at','llm_call_limit','llm_output_token_limit')
        a=dict.fromkeys(keys,1);a.update(llm_calls_admitted=2,llm_output_tokens_reserved=1200)
        self.assertFalse(same_history(a,dict(a,anchor_message_id=99)))

    def test_source_path_escape_refused(self):
        p=self.fixture(artifacts={'../escape':'fake'})
        self.assertIn('ARTIFACT_MISMATCH:../escape',verify_receipt(p)['errors'])
