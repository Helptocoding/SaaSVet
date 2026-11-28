"""B5 safety/handoff, actual PostgreSQL and durable B3/B4 integration."""
from datetime import timedelta
from unittest.mock import patch

from django.db import connection, transaction, DatabaseError, IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agent import durable, safety, safety_handoff, worker, sender, policy, tier0, guards
from apps.agent.models import Conversation, HumanHandoff, TurnWork, ConversationGoal
from apps.agent.services import ingest_inbound_message
from apps.agent.turn_context import build_turn_context
from apps.channels.models import Message
from apps.channels.providers import SendResult
from . import test_b3_durable as fixtures
from .test_inbox_api import _make_user
from apps.agent.tests.agent_settings_fixtures import create_enabled_agent_settings


@override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True)
class B5SafetyTests(TestCase):
    setUp = fixtures.DurableTurnTests.setUp
    inbound = fixtures.DurableTurnTests.inbound
    claim = fixtures.DurableTurnTests.claim
    expire = fixtures.DurableTurnTests.expire

    def signal(self, text='mi gato está intentando orinar y no sale nada'):
        return self.inbound(text)

    def outbound(self):
        return Message.objects.get(direction='out', semantic_type='safety_guidance')

    def staff(self):
        actor = _make_user('b5-operator', self.org, 'ADMIN')
        client = APIClient()
        client.force_authenticate(actor)
        return actor, client

    def test_safe_01_identity_tool_planner_and_onboarding_independent(self):
        self.conv.flow = {'client_path': '', 'pending_action': {'tool': 'propose_appointment', 'args': {}}}
        self.conv.save(update_fields=['flow'])
        ConversationGoal.objects.create(organization=self.org, conversation=self.conv, name='schedule')
        with patch('apps.agent.planner.handle_inbound', side_effect=TimeoutError), patch(
                'apps.agent.executor.ToolExecutor.call', side_effect=TimeoutError, create=True), patch(
                'apps.agent.alerts.notify_urgent_handoff') as alert:
            self.signal()
        alert.assert_not_called()
        self.assertIsNone(self.conv.contact.owner_id)
        self.assertEqual(HumanHandoff.objects.get().priority, 'urgent')
        self.assertEqual(self.outbound().status, 'pending')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)
        self.assertEqual(self.conv.ownership_epoch, 1)
        self.assertNotIn('pending_action', self.conv.flow)

    def test_handoff_01_durable_scope_source_and_inbox(self):
        message = self.signal()
        h = HumanHandoff.objects.get()
        out = self.outbound()
        self.assertEqual((h.organization_id, h.conversation_id), (self.org.pk, self.conv.pk))
        self.assertEqual(h.source_message_id, message.pk)
        self.assertEqual(h.source_turn_id, out.turn_work_id)
        self.assertEqual(h.reason_code, HumanHandoff.REASON_SAFETY)
        self.assertEqual(h.safety_signals, ['URINARY'])
        self.assertEqual(h.notification_status, 'NOT_CONFIGURED')
        self.assertIsNone(h.acknowledged_at)
        self.assertIsNone(h.acknowledged_by_id)
        from apps.agent.views import _handoff_payload
        payload = _handoff_payload(self.conv)
        self.assertEqual(payload['state'], 'QUEUED')
        self.assertEqual(payload['guidance_status'], 'pending')

    def test_safe_mt_01_real_c1_and_exclusive_cursor(self):
        self.m1.body = 'lleva rato intentando hacer pipí'
        self.m1.save(update_fields=['body'])
        first = self.claim()
        durable.finalize_turn(first)
        m2 = self.signal('pero no sale nada')
        h = HumanHandoff.objects.get()
        self.assertEqual(h.source_message_id, m2.pk)
        self.assertEqual(h.safety_signals, ['URINARY'])
        self.assertNotIn('lleva rato', h.reason_detail)

    def test_safe_context_does_not_cross_time_or_subject(self):
        Message.objects.filter(pk=self.m1.pk).update(body='lleva rato intentando hacer pipi',
            created_at=timezone.now()-timedelta(hours=1), status='processed')
        m2 = self.inbound('no sale nada')
        result = safety.assess_context(self.conv, build_turn_context(self.conv, [m2]))
        self.assertEqual(result.classification, safety.NO_SIGNAL)
        self.assertFalse(HumanHandoff.objects.exists())

    def test_safe_neg_01_independent_symptoms(self):
        for text in ('no está convulsionando', 'no le cuesta respirar', 'no está sangrando',
                     'no es que no pueda orinar', 'nunca ha convulsionado', 'sí come no ha dejado de comer'):
            self.assertEqual(safety.assess_texts([text]).classification, safety.NO_SIGNAL)
        self.assertEqual(safety.assess_texts(['no está sangrando pero está convulsionando']).classification, safety.URGENT)

    def test_safe_time_01(self):
        for text in ('el año pasado tuvo problemas para respirar', 'qué hago si un día no puede orinar'):
            self.assertEqual(safety.assess_texts([text]).classification, safety.NO_SIGNAL)
        self.assertEqual(safety.assess_texts(['ahorita no puede respirar bien']).classification, safety.URGENT)

    def test_safe_03_honest_finite_guidance(self):
        self.signal()
        body = self.outbound().body
        self.assertIn('WhatsApp no sustituye', body)
        self.assertIn('no esperes', body)
        self.assertIn('marcado esta conversación', body)
        for forbidden in ('diagnóstico:', 'mg', 'medicamento', 'está estable', 'en breve', 'ya avisé', 'enseguida'):
            self.assertNotIn(forbidden, body)
        for forbidden in ('Ya avisé al equipo', 'El veterinario ya fue notificado', 'Ya vieron tu mensaje',
                          'Te atenderán enseguida', 'Te responderán en breve',
                          'Está todo bajo control', 'No es una emergencia', 'Puedes esperar'):
            self.assertIsNotNone(guards.check_containment(forbidden))

    def test_handoff_02_ack_only_explicit_scoped_claim(self):
        self.signal()
        actor, client = self.staff()
        response = client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/')
        self.assertEqual(response.status_code, 200, response.data)
        h = HumanHandoff.objects.get()
        self.assertEqual(h.acknowledged_by_id, actor.pk)
        stamp = h.acknowledged_at
        self.assertIsNotNone(stamp)
        client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/')
        h.refresh_from_db()
        self.assertEqual(h.acknowledged_at, stamp)

    def test_handoff_03_duplicate_webhook_repeat_signal_no_spam(self):
        m = self.signal()
        duplicate = ingest_inbound_message(self.channel, wamid=m.external_message_id,
            wa_id='5215512345678', body=m.body)
        self.assertIsNone(duplicate)
        self.signal('está convulsionando')
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
        self.assertIn('NEUROLOGICAL', HumanHandoff.objects.get().safety_signals)

    def test_safe_human_01_no_ownership_or_output_competition(self):
        actor, client = self.staff()
        client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/')
        self.conv.refresh_from_db()
        epoch = self.conv.ownership_epoch
        self.signal()
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.claimed_by_id, actor.pk)
        self.assertEqual(self.conv.ownership_epoch, epoch)
        self.assertEqual(self.conv.state, Conversation.STATE_HUMAN_ACTIVE)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(HumanHandoff.objects.get().priority, 'urgent')
        self.assertIsNone(HumanHandoff.objects.get().acknowledged_at)
        self.assertEqual(client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/').status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, epoch)
        self.assertEqual(HumanHandoff.objects.get().acknowledged_by_id, actor.pk)

    def test_safe_media_01_no_binary_inference(self):
        m = ingest_inbound_message(self.channel, wamid='media1', wa_id='5215512345678',
            payload_type='audio', raw={'audio': {'id': 'test-audio'}})
        self.assertFalse(HumanHandoff.objects.exists())
        self.assertEqual(safety.assess_context(self.conv, build_turn_context(self.conv, [m])).classification, safety.NO_SIGNAL)
        ingest_inbound_message(self.channel, wamid='media2', wa_id='5215512345678',
            body='mira cómo está respirando', payload_type='image', raw={'image': {'id': 'test-image'}})
        self.assertIn('No puedo interpretar', self.outbound().body)

    def test_safe_tenant_01_foreign_context_and_ack_rejected(self):
        from dataclasses import replace
        from apps.organizations.models import Organization
        other = Organization.objects.create(name='Other B5')
        context = build_turn_context(self.conv, [self.m1])
        with self.assertRaises(ValueError):
            safety.assess_context(self.conv, replace(context, organization_id=other.pk))
        self.signal()
        actor = _make_user('b5-foreign', other, 'ADMIN')
        with self.assertRaises(ValueError):
            safety_handoff.acknowledge(self.conv, actor)
        client = APIClient(); client.force_authenticate(actor)
        self.assertEqual(client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/').status_code, 404)

    def test_safe_race_01_new_safety_fixed_membership_defers_normal(self):
        w1 = self.claim()
        signal = self.signal()
        self.assertEqual(durable.context_for_work(w1).inbound_ids, (self.m1.pk,))
        self.assertIsNone(Message.objects.get(pk=signal.pk).turn_work_id)
        self.assertEqual(durable.finalize_turn(w1, outputs=[{'body': 'Comercial obsoleto'}]), 'deferred_to_new_input')
        worker._run_turn(self.claim())
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)
        self.assertEqual(self.outbound().body[:8], 'Por lo q')

    def test_safe_race_02_pending_commercial_discarded_valid_guidance_admitted(self):
        normal = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', author_type=Message.AUTHOR_AGENT, body='Comercial', origin_epoch=0)
        self.signal()
        normal.refresh_from_db()
        self.assertEqual(normal.status, 'discarded')
        out = self.outbound()
        claim = sender.claim_message(out.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        self.assertIsNotNone(sender.admit_dispatch(claim))
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.safe'))
        out.refresh_from_db()
        self.assertEqual(out.status, 'sent')

    def test_safe_race_03_admitted_commercial_reality_survives(self):
        normal = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', author_type=Message.AUTHOR_AGENT, body='Comercial', origin_epoch=0)
        claim = sender.claim_message(normal.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        self.signal()
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.before-safety'))
        normal.refresh_from_db()
        self.assertEqual(normal.status, 'sent')
        self.assertIsNotNone(normal.send_admitted_at)

    def test_safe_fi_01_crash_after_detection_recovers_same_work(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.signal()
        witness = self.claim()
        assessment = safety.assess_context(self.conv, durable.context_for_work(witness))
        self.assertEqual(assessment.classification, safety.URGENT)
        self.assertFalse(HumanHandoff.objects.exists())
        self.expire(witness)
        recovered = self.claim()
        worker._run_turn(recovered)
        self.assertEqual(witness.turn_work_id, recovered.turn_work_id)
        self.assertEqual(HumanHandoff.objects.count(), 1)

    def test_safe_fi_02_db_failure_after_handoff_rolls_back_all(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.signal()
        witness = self.claim()
        def fail(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')
        with patch('apps.agent.tier0.render_safety_guidance', side_effect=fail), self.assertRaises(DatabaseError):
            worker._run_turn(witness)
        self.assertFalse(HumanHandoff.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 0)
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PROCESSING)
        worker._run_turn(witness)
        self.assertEqual(HumanHandoff.objects.count(), 1)

    def test_safe_fi_04_handoff_insert_failure_no_false_claim(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.signal()
        witness = self.claim()
        with patch.object(HumanHandoff, 'save', side_effect=DatabaseError), self.assertRaises(DatabaseError):
            worker._run_turn(witness)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertFalse(HumanHandoff.objects.exists())

    def test_safe_fi_04_webhook_preserves_inbound_on_consolidation_failure(self):
        with patch.object(HumanHandoff, 'save', side_effect=DatabaseError):
            message = self.signal()
        message.refresh_from_db()
        self.assertEqual(message.status, 'pending')
        self.assertIsNone(message.turn_work_id)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        worker._run_turn(self.claim())
        self.assertEqual(HumanHandoff.objects.count(), 1)

    def test_safe_fi_05_takeover_before_finalize_preserves_case_without_output(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.signal()
        witness = self.claim()
        actor, client = self.staff()
        self.assertEqual(client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/').status_code, 200)
        with self.assertRaises(durable.OwnershipLost):
            worker._run_turn(witness)
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_safe_gate_before_requested_human_and_no_onboarding(self):
        self.signal('quiero hablar con una persona, mi gato no puede orinar')
        self.assertEqual(HumanHandoff.objects.get().reason_code, HumanHandoff.REASON_SAFETY)

    def test_sender_refuses_commercial_while_safety_waits_for_w2(self):
        normal = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', author_type=Message.AUTHOR_AGENT, body='Comercial', origin_epoch=0)
        witness = self.claim()
        signal = self.signal()
        self.inbound('otro mensaje normal')
        signal.refresh_from_db()
        self.assertTrue(signal.available_at is None or signal.available_at <= timezone.now())
        self.assertIsNone(sender.claim_message(normal.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk))
        normal.refresh_from_db()
        self.assertEqual(normal.failure_reason, 'safety_pending')
        durable.finalize_turn(witness)

    def test_automation_flag_off_does_not_activate_new_safety_circuit(self):
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=False):
            self.signal()
        self.assertFalse(HumanHandoff.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_observability_snapshot_has_counts_ages_and_no_pii_labels(self):
        self.signal()
        snapshot = safety_handoff.observe_handoffs()
        self.assertEqual(snapshot['queue']['urgent']['count'], 1)
        self.assertEqual(snapshot['guidance'], {'pending': 1})
        self.assertNotIn(self.conv.contact.external_id, str(snapshot))
        self.assertNotIn('conversation_id', str(snapshot))

    def test_safe_fi_06_normal_input_does_not_resume_funnel(self):
        from apps.agent.models import AgentSettings
        actor, _ = self.staff()
        create_enabled_agent_settings(self.org, agent_user=actor)
        self.signal()
        self.inbound('quiero una cita')
        with patch('apps.agent.planner._run_planner', side_effect=AssertionError('funnel resumed')):
            outcome = worker._run_turn(self.claim())
        self.assertEqual(outcome, 'silent')
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, Conversation.STATE_HANDOFF_PENDING)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_safe_fi_07_uncertain_guidance_does_not_erase_handoff_or_retry(self):
        self.signal()
        out = self.outbound()
        claim = sender.claim_message(out.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('uncertain', code='timeout'))
        self.assertEqual(HumanHandoff.objects.count(), 1)
        self.assertEqual(Message.objects.get(pk=out.pk).status, 'uncertain')
        self.assertIsNone(sender.claim_message(out.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk))

    def test_safe_fi_08_existing_handoff_is_elevated(self):
        old = HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code='explicit_request')
        self.signal()
        self.assertEqual(HumanHandoff.objects.get().pk, old.pk)
        self.assertEqual(HumanHandoff.objects.get().priority, 'urgent')

    def test_own_04_grant_revoked_by_next_takeover_and_not_generic_system(self):
        self.signal()
        out = self.outbound()
        fake = Message.objects.create(organization=self.org, conversation=self.conv, channel_account=self.channel,
            direction='out', body='Oferta comercial', author_type='system', origin_epoch=0, semantic_type='safety_guidance')
        self.conv.refresh_from_db()
        self.assertFalse(safety_handoff.guidance_authorized(fake, self.conv))
        actor, client = self.staff()
        client.post(f'/api/inbox/conversations/{self.conv.public_id}/claim/')
        self.assertIsNone(sender.claim_message(out.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk))

    def test_no_idle_close_of_unresolved_human_queue(self):
        self.signal()
        Conversation.objects.filter(pk=self.conv.pk).update(last_activity_at=timezone.now()-timedelta(days=3))
        self.assertEqual(policy.close_inactive_conversations(), 0)

    def test_partial_event_uniqueness_preserves_multiple_legacy_open(self):
        for _ in range(2):
            HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code='explicit_request')
        self.signal()
        self.assertEqual(HumanHandoff.objects.count(), 2)
        h = HumanHandoff.objects.exclude(event_key=None).get()
        with self.assertRaises((IntegrityError,)), transaction.atomic():
            HumanHandoff(organization=self.org, conversation=self.conv, reason_code='safety_urgent',
                event_key=h.event_key).save(validate=False)
