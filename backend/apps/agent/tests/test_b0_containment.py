"""BASE-01/02/03: fronteras actuales, sin worker/sender ni bypass de contención."""
from .legacy_pending import seed_pending
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.agent import alerts, confirmations, guards, intake, planner, tier0, tools
from apps.agent.executor import ToolExecutor
from apps.agent.llm import LLMError, LLMResult
from apps.agent.models import AgentSettings, ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.services import ensure_agent_user
from .harness import (
    ControlledTransport, CriticalB0Runner, FailureBarrier, InjectedFailure,
    PersistedTurnHarness,
)
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings

CORPUS_PATH = Path(__file__).with_name('fixtures') / 'b0_critical.json'
# IDs estables externos al fixture: quitarlo, vaciarlo o omitir un caso falla.
WRITE_CASES = {
    'create_appointment', 'confirm_appointment', 'cancel_appointment',
    'reschedule_appointment', 'register_new_client_and_pet',
    'register_pet_and_schedule', 'register_pet_only',
}
OUTPUT_CASES = {
    'clinical-dose', 'clinical-severity', 'unbacked-write',
    'unbacked-notice', 'accidental-number',
}
REPLY_CASES = {
    'no ', 'no estoy de acuerdo ', 'sí para Max', 'sí pero otra mascota',
    'sí confirmo que asistiré', '¿mi cita está confirmada?',
}


def load_corpus():
    corpus = json.loads(CORPUS_PATH.read_text(encoding='utf-8'))
    if (corpus['version'] != 1 or set(corpus['writes']) != WRITE_CASES
            or set(corpus['replies']) != REPLY_CASES
            or {c['id'] for c in corpus['unsafe_outputs']} != OUTPUT_CASES):
        raise AssertionError('Corpus B0 incompleto o versión no revisada')
    return corpus


@override_settings(DISCORD_WEBHOOK_URL='')
class B0ContainmentTests(TestCase):
    def setUp(self):
        self.corpus = load_corpus()
        self.org = Organization.objects.create(name='B0 test', timezone='UTC')
        self.owner = Owner.objects.create(
            organization=self.org, name='Ana', phone='5512345678')
        self.pet = Pet.objects.create(
            organization=self.org, owner=self.owner, name='Luna', species='perro')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='b0-test')
        self.user, _ = ensure_agent_user(self.org)
        create_enabled_agent_settings(self.org, agent_user=self.user)
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id='5215512345678',
            owner=self.owner, verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now())
        self.conv = self.new_conversation()

    def new_conversation(self):
        return Conversation.objects.create(
            organization=self.org, channel_account=self.channel, contact=self.contact)

    def harness(self):
        return PersistedTurnHarness(self, self.conv, self.user)

    def test_registry_covers_every_current_write(self):
        writes = {name for name, spec in tools.TOOL_SPECS.items()
                  if spec['tier'] == '2'} | {'confirm_appointment'}
        self.assertEqual(writes, WRITE_CASES)
        self.assertEqual(set(intake.CONTAINED_WRITES), WRITE_CASES)
        exposed = {t['function']['name'] for t in tools.as_openai_tools(self.conv)}
        self.assertFalse(exposed & WRITE_CASES)

    def test_forced_dispatch_cannot_invoke_any_write_handler(self):
        for name in self.corpus['writes']:
            with self.subTest(tool=name):
                harness = self.harness()
                handler = Mock(side_effect=AssertionError('WRITE handler invoked'))
                with patch.dict(tools.TOOL_SPECS[name], handler=handler):
                    outcome = tools.run_tool(
                        name, {}, conversation=self.conv,
                        executor=ToolExecutor(self.conv, self.user,
                                              transport=harness.transport))
                self.assertEqual(outcome.client_error, 'autonomous_writes_paused')
                handler.assert_not_called()
                self.assertEqual(harness.transport.calls, [])
                harness.assert_zero_business_effects()

    def test_forced_planner_write_is_handed_off(self):
        for name in self.corpus['writes']:
            with self.subTest(tool=name):
                self.conv = self.new_conversation()
                harness = self.harness()
                result = harness.run(['Necesito ayuda con la agenda'], scripted_llm=[
                    LLMResult(kind='tool_call', tool_name=name, tool_args={})])
                self.assertEqual(result['decision'], 'autonomous_writes_paused')
                self.assertEqual(harness.outbounds[-1].body, tier0.T0_WRITE_PAUSED)
                self.assertTrue(HumanHandoff.objects.filter(
                    conversation=self.conv, resolved_at__isnull=True).exists())
                harness.assert_zero_business_effects()

    def test_legacy_pending_cannot_authorize_any_reply(self):
        for reply in self.corpus['replies']:
            with self.subTest(reply=reply):
                self.conv = self.new_conversation()
                seed_pending(
                    self.conv, tool='create_appointment',
                    args={'pet_id': str(self.pet.public_id)}, paraphrase='Cita para Luna')
                harness = self.harness()
                harness.run([reply], scripted_llm=[])
                self.assertEqual(harness.outbounds[-1].body, tier0.T0_WRITE_PAUSED)
                harness.assert_zero_business_effects()

    def test_direct_pending_commit_is_contained(self):
        for name in tools.COMMIT_HANDLERS:
            with self.subTest(tool=name):
                self.conv = self.new_conversation()
                seed_pending(self.conv, tool=name, args={},
                                            paraphrase='Propuesta heredada')
                harness = self.harness()
                handler = Mock(side_effect=AssertionError('commit invoked'))
                with patch.dict(tools.COMMIT_HANDLERS, {name: handler}):
                    result = planner._commit_pending(
                        self.conv, ToolExecutor(self.conv, self.user,
                                               transport=harness.transport))
                self.assertEqual(result['decision'], 'autonomous_writes_paused')
                handler.assert_not_called()
                harness.assert_zero_business_effects()

    def test_unsafe_output_corpus_is_replaced_without_retry(self):
        for case in self.corpus['unsafe_outputs']:
            with self.subTest(case=case['id']):
                self.conv = self.new_conversation()
                harness = self.harness()
                result = harness.run(['Ayúdame con una consulta'], scripted_llm=[
                    LLMResult(kind='text', text=case['text'])])
                self.assertEqual(result['reason'], case['reason'])
                expected = (tier0.T0_CLINICAL_LIMIT if case['reason'] == 'medical_advice'
                            else tier0.T0_GUARD_BLOCKED)
                self.assertEqual(harness.outbounds[-1].body, expected)
                self.assertEqual(result['llm_calls'], 1)
                harness.assert_zero_business_effects()

    def test_read_result_does_not_prove_write_or_price(self):
        # Una lectura exitosa no acredita otro efecto ni autoriza prosa sensible.
        for text in ('Ya quedó agendada la cita.', 'El precio es $500.'):
            with self.subTest(text=text):
                self.conv = self.new_conversation()
                harness = self.harness()
                result = harness.run(['Consulta administrativa'], scripted_llm=[
                    LLMResult(kind='tool_call', tool_name='get_clinic_info',
                              tool_args={}),
                    LLMResult(kind='text', text=text),
                ])
                self.assertEqual(result['decision'], 'containment_blocked')
                self.assertEqual(result['tools'], 1)
                self.assertEqual(harness.outbounds[-1].body, tier0.T0_GUARD_BLOCKED)
                harness.assert_zero_business_effects()
        self.assertIsNone(guards.check_containment('Puedes consultar los horarios.'))

    def test_public_read_and_explicit_human_remain_available(self):
        harness = self.harness()
        outcome = tools.run_tool(
            'get_clinic_info', {}, conversation=self.conv,
            executor=ToolExecutor(self.conv, self.user, transport=harness.transport))
        self.assertTrue(outcome.ok)
        harness.run(['Quiero hablar con una persona'], scripted_llm=[])
        self.assertIn('registrada', harness.outbounds[-1].body)
        harness.assert_zero_business_effects()

    def test_personal_read_needs_current_identity(self):
        for verified_at in (None, timezone.now() - timedelta(days=183)):
            with self.subTest(verified_at=verified_at):
                self.contact.verified_at = verified_at
                self.contact.save(update_fields=['verified_at'])
                harness = self.harness()
                outcome = tools.run_tool(
                    'list_my_pets', {}, conversation=self.conv,
                    executor=ToolExecutor(self.conv, self.user,
                                          transport=harness.transport))
                self.assertEqual(outcome.client_error, 'verification_required')
                self.assertEqual(harness.transport.calls, [])

    def test_pending_events_and_queued_outbound_do_not_mean_delivery(self):
        harness = self.harness()
        harness.run(['Consulta administrativa'], scripted_llm=[
            LLMResult(kind='text', text='¿Qué información necesitas?')])
        self.assertEqual([m.status for m in harness.outbounds], [Message.STATUS_PENDING])
        self.assertEqual(
            list(Message.objects.filter(pk__in=[m.pk for m in harness.inbounds])
                 .values_list('status', flat=True)), [Message.STATUS_PENDING])
        self.assertEqual(harness.transport.calls, [])

    def test_failure_after_persistence_leaves_pending_event(self):
        harness = PersistedTurnHarness(
            self, self.conv, self.user,
            barrier=FailureBarrier(fail_at='inbound_persisted'))
        with self.assertRaises(InjectedFailure):
            harness.run(['Hola'], scripted_llm=[])
        self.assertEqual(Message.objects.get(pk=harness.inbounds[0].pk).status,
                         Message.STATUS_PENDING)
        harness.assert_zero_business_effects()

    def test_llm_timeout_yields_honest_fallback(self):
        harness = self.harness()
        harness.run(['Consulta administrativa'], scripted_llm=[
            LLMError('timeout', retryable=True)] * 3)
        self.assertEqual(harness.outbounds[-1].body, tier0.T0_TECH_PROBLEM)
        harness.assert_zero_business_effects()

    def test_emergency_copy_uses_only_configured_phone(self):
        self.org.phone = ''
        self.assertEqual(tier0.render_emergency(None, self.org),
                         tier0.T0_EMERGENCY_NO_PHONE)
        self.org.phone = '5550000000'  # Fixture, nunca contacto del piloto.
        text = tier0.render_emergency(None, self.org)
        self.assertIn('llamar a la clínica al 5550000000', text)
        self.assertIn('no esperes una respuesta por este chat', text)
        self.assertNotIn('Ya avisé', text)


class B0CorpusGateTests(SimpleTestCase):
    def test_fixture_is_required_and_complete(self):
        self.assertEqual(set(load_corpus()['writes']), WRITE_CASES)
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                load_corpus()
        with patch.object(Path, 'read_text', return_value='{"version":1,"writes":[]}'):
            with self.assertRaises((AssertionError, KeyError)):
                load_corpus()
        # Conservar solo los tests del gate no puede ocultar la ausencia del corpus
        # de comportamiento; el runner requerido debe rechazar esa suite parcial.
        with self.assertRaisesRegex(RuntimeError, 'Escenarios críticos B0 ausentes'):
            CriticalB0Runner(verbosity=0).build_suite([
                'apps.agent.tests.test_b0_containment.B0CorpusGateTests'])

    def test_failed_empty_skipped_or_expected_failure_cannot_pass_gate(self):
        runner = CriticalB0Runner(verbosity=0)
        for scenario in ('failed', 'empty', 'skipped', 'expected', 'partial'):
            result = unittest.TestResult()
            result.testsRun = 1
            if scenario == 'failed':
                result.failures.append(('critical', 'failed'))
            elif scenario == 'empty':
                result.testsRun = 0
            elif scenario == 'skipped':
                result.skipped.append(('critical', 'skip'))
            elif scenario == 'expected':
                result.expectedFailures.append(('critical', 'xfail'))
            else:
                runner._planned_count = 2
            self.assertGreater(runner.suite_result(None, result), 0)

    def test_controlled_provider_failure_boundaries(self):
        for boundary in ('before_provider', 'after_provider'):
            transport = ControlledTransport(
                responses=[(200, {'accepted': True})],
                barrier=FailureBarrier(fail_at=boundary))
            with self.assertRaises(InjectedFailure):
                transport('POST', '/test-provider', headers={})
            self.assertEqual(transport.calls, [('POST', '/test-provider')])
            self.assertIn(boundary, transport.barrier.events)

    @override_settings(DISCORD_WEBHOOK_URL='https://provider.invalid/test')
    def test_alert_acceptance_failure_and_no_free_text_export(self):
        conv = Mock(pk=1, public_id='test', organization=Mock(pk=2))
        conv.organization.name = 'Test org'
        for response, expected in ((Mock(status_code=204), True),
                                   (Mock(status_code=500), False),
                                   (requests.Timeout(), False)):
            with self.subTest(response=response):
                with patch('apps.agent.alerts.requests.post') as post:
                    if isinstance(response, Exception):
                        post.side_effect = response
                    else:
                        post.return_value = response
                    with self.assertLogs('agent.events') as logs:
                        accepted = alerts.notify_urgent_handoff(
                            conv, reason_code='emergency',
                            detail='texto privado de cliente')
                    self.assertEqual(accepted, expected)
                    self.assertNotIn('texto privado', str(post.call_args))
                    self.assertEqual(logs.records[-1].alert_provider_accepted, expected)
                    self.assertNotIn('alert_delivered', logs.records[-1].__dict__)
