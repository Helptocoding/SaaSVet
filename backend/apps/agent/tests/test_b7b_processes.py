"""B7B FI-01..10 and race ordering with separate PostgreSQL processes."""
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from apps.agent import durable, sender, operation_consent as consent
from apps.agent.models import ConversationOperation, TurnWork
from apps.channels.models import Message
from apps.channels.providers import SendResult
from apps.channels.status import record_status
from .test_operation_consent import ConsentFixtures


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B7BProcessTests(ConsentFixtures, TransactionTestCase):
    def start(self, mode):
        self.assertEqual(connection.vendor, 'postgresql')
        args = {'witness': asdict(self.witness), 'operation_id': self.op.pk,
                'goal_id': self.goal.pk, 'max_id': self.max.pk}
        env = dict(os.environ, B3_TEST_DATABASE=json.dumps(connection.settings_dict, default=str),
                   PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-X', 'utf8', '-m',
            'apps.agent.tests.b7b_process', mode, json.dumps(args, default=str)],
            cwd=Path(__file__).resolve().parents[3], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, proc)
        self.barrier(proc, 'READY')
        return proc

    @staticmethod
    def cleanup(proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=15)

    def barrier(self, proc, expected):
        def read():
            while line := proc.stdout.readline():
                if line.startswith('B7B_'):
                    return line.strip()
            return ''
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                actual = pool.submit(read).result(timeout=45)
            except Exception:
                proc.kill()
                raise
        self.assertEqual(actual, 'B7B_' + expected)

    def release(self, proc):
        proc.stdin.write('go\n')
        proc.stdin.flush()

    def result(self, proc):
        stdout, stderr = proc.communicate(timeout=45)
        self.assertEqual(proc.returncode, 0, stderr[-3000:])
        return json.loads(next(x.removeprefix('B7B_RESULT ') for x in stdout.splitlines()
                              if x.startswith('B7B_RESULT ')))

    def ready_response(self):
        self.proposal()
        self.response()
        self.witness = self.claim()

    def reclaim(self):
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(
            lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()

    def assert_pending(self):
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'PENDING')
        self.assertIsNone(self.op.authorization_message_id)
        self.assertIsNone(self.op.consent_decided_at)
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')

    def test_fi01_crash_after_proposal_before_emission(self):
        self.op = self.prepare()
        proc = self.start('publish')
        self.release(proc)
        self.barrier(proc, 'PUBLISHED')
        self.cleanup(proc)
        self.op.refresh_from_db()
        self.assertEqual(self.op.proposal_message.status, 'pending')
        self.msg = self.op.proposal_message
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assert_pending()
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_fi02_crash_after_meta_before_sent_is_uncertain(self):
        self.proposal(False)
        proc = self.start('meta_accepted')
        self.release(proc)
        self.barrier(proc, 'META_ACCEPTED')
        self.cleanup(proc)
        Message.objects.filter(pk=self.msg.pk).update(send_lease_until=timezone.now()-timedelta(seconds=1))
        self.assertEqual(sender.recover_expired(), 1)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, 'uncertain')
        self.assertIsNone(self.msg.external_message_id)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assert_pending()

    def test_fi03_crash_after_emission_before_evaluation(self):
        self.ready_response()
        proc = self.start('before_evaluate')
        self.release(proc)
        self.barrier(proc, 'BEFORE_EVALUATE')
        self.cleanup(proc)
        self.reclaim()
        self.assertEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')

    def test_fi04_crash_after_validation_before_authorization_commit(self):
        self.ready_response()
        proc = self.start('before_commit')
        self.release(proc)
        self.barrier(proc, 'UNCOMMITTED')
        self.cleanup(proc)
        self.assert_pending()
        self.reclaim()
        self.assertEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')

    def test_fi05_crash_after_commit_before_turn_completion(self):
        self.ready_response()
        proc = self.start('after_commit')
        self.release(proc)
        self.barrier(proc, 'COMMITTED')
        self.cleanup(proc)
        self.reclaim()
        self.assertTrue(consent.evaluate_turn(self.witness).duplicate)
        self.assertEqual(ConversationOperation.objects.filter(consent_state='AUTHORIZED').count(), 1)
        durable.finalize_turn(self.witness)

    def change_wins(self, mode):
        self.ready_response()
        changing = self.start('hold_' + mode)
        self.release(changing)
        self.barrier(changing, 'CHANGED')
        authorizing = self.start('authorize')
        self.release(authorizing)
        self.release(changing)
        self.assertTrue(self.result(changing)['changed'])
        result = self.result(authorizing)
        self.assertNotEqual(result.get('decision'), 'ACCEPT')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'INVALIDATED')
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')

    def test_fi06_correction_wins_against_concurrent_authorization(self):
        self.change_wins('correction')

    def test_fi07_takeover_wins_against_concurrent_authorization(self):
        self.change_wins('takeover')

    def consent_wins(self, mode):
        self.ready_response()
        authorizing = self.start('hold_consent')
        self.release(authorizing)
        self.barrier(authorizing, 'UNCOMMITTED')
        changing = self.start(mode)
        self.release(changing)
        self.release(authorizing)
        self.assertEqual(self.result(authorizing)['decision'], 'ACCEPT')
        self.assertTrue(self.result(changing)['changed'])
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertIsNotNone(consent.authorization_evidence(self.op))
        self.assertFalse(ConversationOperation.objects.filter(consent_state='PENDING').exists())

    def test_authorization_precedes_correction_history_not_transferred(self):
        self.consent_wins('correction')

    def test_authorization_precedes_takeover_history_not_reopened(self):
        self.consent_wins('takeover')

    def test_fi08_concurrent_duplicate_one_decision(self):
        self.ready_response()
        processes = [self.start('authorize'), self.start('authorize')]
        for proc in processes:
            self.release(proc)
        results = [self.result(proc) for proc in processes]
        self.assertEqual([x['decision'] for x in results], ['ACCEPT', 'ACCEPT'])
        self.assertEqual(sum(x['duplicate'] for x in results), 1)
        self.assertEqual(ConversationOperation.objects.filter(consent_state='AUTHORIZED').count(), 1)

    def test_fi09_reconciliation_after_ambiguous_order_is_not_retroactive(self):
        self.proposal(False)
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('uncertain', provider_id='wamid.b7b-process'))
        self.response()
        self.witness = self.claim()
        proc = self.start('authorize')
        record_status(self.channel, 'wamid.b7b-process', 'sent')
        self.release(proc)
        self.assertEqual(self.result(proc)['decision'], 'STALE')
        self.assert_pending()

    def test_fi10_database_error_rolls_back_evidence_and_state(self):
        self.ready_response()
        proc = self.start('db_error')
        self.release(proc)
        self.assertEqual(self.result(proc)['error'], 'DataError')
        self.assert_pending()
        self.assertEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')

    def test_distinct_concurrent_no_defers_yes_and_late_worker_cannot_overwrite(self):
        self.ready_response()
        yes_work = self.witness
        authorizing = self.start('authorize')
        self.response('No', reply_to=self.msg.external_message_id)
        self.release(authorizing)
        self.assertEqual(self.result(authorizing)['decision'], 'STALE')
        self.assertEqual(durable.finalize_turn(yes_work), 'deferred_to_new_input')
        self.witness = self.claim()
        self.assertEqual(consent.evaluate_turn(self.witness).decision, 'REJECT')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'REJECTED')
        self.witness = yes_work
        late = self.start('authorize')
        self.release(late)
        self.assertEqual(self.result(late)['error'], 'OwnershipLost')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'REJECTED')
