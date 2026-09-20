"""Versioned conversations through real preparation/publication/consent services."""
import json
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.agent import durable, operations, sender, operation_consent as consent
from apps.agent.models import Conversation
from apps.channels.models import Message
from apps.channels.providers import SendResult
from apps.channels.status import record_status
from .test_operation_consent import ConsentFixtures

CORPUS = json.loads((Path(__file__).resolve().parents[4] /
    'docs/evals/b7b-consent-corpus-v1.json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B7BCorpusTests(ConsentFixtures, TestCase):
    def run_case(self, case):
        scenario = case['scenario']
        no_emit = scenario in {'pending', 'sending', 'uncertain', 'failed', 'discarded', 'late_webhook'}
        self.proposal(not no_emit)
        if scenario in ('sending', 'uncertain', 'late_webhook'):
            claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
            sender.admit_dispatch(claim)
            if scenario != 'sending':
                sender.finalize_dispatch(claim, SendResult('uncertain', provider_id='wamid.b7b-proposal'))
        if scenario in ('failed', 'discarded'):
            Message.objects.filter(pk=self.msg.pk).update(status=scenario)
        if scenario == 'intermediate':
            self.response('¿Cuánto cuesta?')
            durable.finalize_turn(self.claim(), outputs=[{'body': 'La consulta cuesta 500.'}])
        text = case['text'].replace('{TOKEN}', 'CONFIRMAR ' + consent.proposal_token(self.op))
        self.response(text, reply_to=self.msg.external_message_id if scenario in ('reply', 'old_reply') else None)
        if scenario == 'late_webhook':
            record_status(self.channel, 'wamid.b7b-proposal', 'read')
        if scenario == 'identity':
            self.conv.contact.auto_rematch_blocked = True
            self.conv.contact.save(update_fields=['auto_rematch_blocked'])
        if scenario == 'takeover':
            with transaction.atomic():
                durable.invalidate_ownership(self.conv, reason='test_takeover')
                self.conv.state = Conversation.STATE_HUMAN_ACTIVE
                self.conv.save(update_fields=['state'])
        if scenario in ('binding', 'old_reply'):
            self.witness = self.claim()
            self.ctx = durable.context_for_work(self.witness)
            self.change({'pet': self.max.pk})
            result = consent.evaluate_turn(self.witness)
        elif scenario == 'expired':
            with patch('apps.agent.operation_consent.db_now', return_value=self.op.expires_at+timedelta(seconds=1)):
                result = self.evaluate()
        else:
            result = self.evaluate()
        self.op.refresh_from_db()
        CORPUS_RESULTS.append({'id': case['id'], 'decision': result.decision,
            'state': self.op.consent_state, 'expected_decision': case['decision'],
            'expected_state': case['state'], 'category': case['category'],
            'false_authorization': self.op.consent_state == 'AUTHORIZED' and case['state'] != 'AUTHORIZED'})
        self.assertEqual(result.decision, case['decision'])
        self.assertEqual(self.op.consent_state, case['state'])
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        from apps.appointments.models import Appointment
        self.assertEqual(Appointment.objects.count(), 0)


def make_test(case):
    def test(self):
        self.run_case(case)
    return test


for case in CORPUS['cases']:
    setattr(B7BCorpusTests, 'test_corpus_' + case['id'], make_test(case))
