"""Versioned execution corpus, real B7A/B7B authority, fake domain only."""
import json
from contextlib import ExitStack
from pathlib import Path
from types import MappingProxyType
from datetime import timedelta
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.agent import operation_execution as execution
from apps.agent.models import Conversation, HumanHandoff
from apps.agent.operation_permission import ActorPermission
from apps.channels.models import Message
from .test_operation_execution import ExecutionFixtures
from .b8a_support import enabled_test_adapter, LocalTestAdapter, effect_count

CORPUS = json.loads((Path(__file__).resolve().parents[4] /
    'docs/evals/b8a-execution-corpus-v1.json').read_text(encoding='utf-8'))
CORPUS_RESULTS = []


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class B8ACorpusTests(ExecutionFixtures, TestCase):
    def run_case(self, case):
        self.authorized()
        scenario = case['scenario']
        adapter = LocalTestAdapter()
        with ExitStack() as stack:
            if scenario != 'containment':
                stack.enter_context(enabled_test_adapter(adapter))
            if scenario == 'expired':
                stack.enter_context(patch.object(execution.durable, 'db_now',
                    return_value=self.op.expires_at + timedelta(seconds=1)))
            elif scenario == 'digest':
                self.tamper(parameters_digest='0'*64)
            elif scenario == 'identity':
                self.conv.contact.verified_at = timezone.now()
                self.conv.contact.save(update_fields=['verified_at'])
            elif scenario == 'binding':
                self.correct()
            elif scenario == 'ownership':
                Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=self.witness.ownership_epoch+1)
            elif scenario == 'permission':
                stack.enter_context(patch.object(execution.operation_permission, 'actor_permission',
                    return_value=ActorPermission('FORBIDDEN', 'revoked', {})))
            elif scenario == 'takeover':
                self.takeover()
            elif scenario == 'safety':
                HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
            elif scenario == 'precondition':
                adapter.validate_preconditions = Mock(return_value=execution.PreconditionResult(False, 'slot_unavailable'))
            elif scenario == 'executed_retry':
                self.assertEqual(self.execute().status, 'SUCCEEDED')
            elif scenario == 'uncertain_retry':
                adapter.execute = Mock(side_effect=TimeoutError())
                self.assertEqual(self.execute().status, 'UNCERTAIN')
            elif scenario in ('correction', 'revocation'):
                self.response('Mejor las 11' if scenario == 'correction' else 'No, olvida la propuesta')
            elif scenario == 'incomplete_evidence':
                self.tamper(authorization_message_id=self.op.source_message_id)
            elif scenario == 'no_emission':
                Message.objects.filter(pk=self.msg.pk).update(status='uncertain', uncertain_at=timezone.now())
            elif scenario == 'stale_causality':
                self.tamper(authorized_at=self.op.created_at, consent_decided_at=self.op.created_at)
            elif scenario == 'kind_disabled':
                registry = dict(execution.REGISTRY)
                registry['CREATE_APPOINTMENT'] = execution.Registration('create_appointment')
                stack.enter_context(patch.object(execution, 'REGISTRY', MappingProxyType(registry)))
            elif scenario == 'reconcile':
                adapter.execute(self.op, self.context)
                adapter.execute = Mock(side_effect=AssertionError('duplicate effect'))
            result = self.execute()
            effects = effect_count()
        CORPUS_RESULTS.append({'id': case['id'], 'scenario': scenario, 'status': result.status,
            'reason': result.reason, 'expected_status': case['status'], 'effects': effects,
            'expected_effects': case['effects'],
            'unauthorized_business_effects': max(0, effects - case['effects'])})
        self.assertEqual(result.status, case['status'])
        self.assertEqual(effects, case['effects'])
        # No runtime business integration is claimed by these synthetic rows.
        from apps.appointments.models import Appointment
        self.assertEqual(Appointment.objects.count(), 0)


def make_test(case):
    def test(self):
        self.run_case(case)
    return test


for case in CORPUS['cases']:
    setattr(B8ACorpusTests, 'test_corpus_' + case['id'], make_test(case))
