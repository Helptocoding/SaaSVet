"""B7B contract tests, written before the consent implementation."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.db import transaction, DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.channels.models import Message
from apps.channels.events import normalize_whatsapp_event, EVENT_METADATA_KEY
from apps.channels.providers import SendResult
from apps.agent import durable, operations, sender, operation_consent as consent
from apps.agent.models import ConversationOperation, Conversation, TurnWork
from apps.agent.services import ingest_inbound_message
from .test_b7a_operations import OperationFixtures


class ConsentFixtures(OperationFixtures):
    def setUp(self):
        super().setUp()
        # B3's inherited "m1" is bootstrap history, not a consent response.
        # OperationFixtures claimed its later preparation input only. Drain
        # this unclaimed fixture seed so the real response burst has no ghost
        # member when its quiet window is released.
        Message.objects.filter(pk=self.m1.pk, turn_work__isnull=True).update(status='processed')

    def proposal(self, emit=True):
        self.op = self.prepare()
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.msg = self.op.proposal_message
        if emit:
            self.emit()
        return self.op

    def emit(self):
        self.send_claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk,
                                              channel_account_id=self.channel.pk)
        self.assertIsNotNone(self.send_claim)
        self.assertIsNotNone(sender.admit_dispatch(self.send_claim))
        sender.finalize_dispatch(self.send_claim, SendResult('accepted', provider_id='wamid.b7b-proposal'))
        self.msg.refresh_from_db()

    def response(self, text=None, reply_to=None, **extra):
        text = text if text is not None else 'CONFIRMAR ' + consent.proposal_token(self.op)
        raw = {'type': 'text', 'text': {'body': text}}
        if reply_to:
            raw['context'] = {'id': reply_to}
        event = normalize_whatsapp_event(raw)
        m = ingest_inbound_message(self.channel, wamid='wamid.' + uuid.uuid4().hex,
            wa_id='5215512345678', body=text, raw={EVENT_METADATA_KEY: event.projection(), **extra})
        # Drain the real quiet window for the entire unclaimed burst. Ingest
        # extends older members too; clearing only the newest would test one
        # response while falsely claiming multi-message coverage.
        Message.objects.filter(conversation=m.conversation, direction='in',
            status='pending', turn_work__isnull=True).update(available_at=None)
        return m

    def evaluate(self):
        self.witness = self.claim()
        result = consent.evaluate_turn(self.witness)
        self.op.refresh_from_db()
        return result


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class OperationConsentTests(ConsentFixtures, TestCase):
    def test_emit_01_missing_proposal_is_not_emission(self):
        self.op = self.prepare()
        self.assertFalse(consent.is_proposal_emitted(self.op))

    def test_emit_02_pending_persisted_not_admitted(self):
        self.proposal(False)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_emit_03_sending_without_admission(self):
        self.proposal(False)
        sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_emit_04_uncertain_not_retried_or_authorized(self):
        self.proposal(False)
        self.emit()
        Message.objects.filter(pk=self.msg.pk).update(status='uncertain', uncertain_at=timezone.now(),
                                                     provider_accepted_at=None)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertIsNone(sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk))

    def test_emit_05_failed_discarded(self):
        self.proposal(False)
        for status in ('failed', 'discarded'):
            Message.objects.filter(pk=self.msg.pk).update(status=status)
            self.assertFalse(consent.is_proposal_emitted(self.op))

    def test_emit_06_verified_emission_then_exact_token_authorizes_once(self):
        self.proposal()
        response = self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(self.op.authorization_message_id, response.pk)
        evidence = consent.authorization_evidence(self.op)
        self.assertEqual(evidence.response_turn_id, self.witness.turn_work_id)
        self.assertEqual(evidence.parameters_digest, self.op.parameters_digest)
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertTrue(consent.evaluate_turn(self.witness).duplicate)

    def test_causal_03_response_during_http_cannot_be_retroauthorized(self):
        self.proposal(False)
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        self.response()
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.b7b-proposal'))
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_emit_07_late_reconciliation_does_not_rewrite_inbound_evidence(self):
        self.proposal(False)
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('uncertain', provider_id='wamid.b7b-proposal'))
        self.response()
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.b7b-proposal'))
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_causal_04_verified_reply_to_exact_proposal(self):
        self.proposal()
        self.response('Sí confirmo', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'ACCEPT')

    def test_causal_04_unknown_reply_to_does_not_fallback_to_token(self):
        self.proposal()
        self.response(reply_to='wamid.foreign')
        self.assertEqual(self.evaluate().decision, 'STALE')

    def test_causal_10_intermediate_question_prevents_bare_yes(self):
        self.proposal()
        self.response('¿Cuánto cuesta?')
        work = self.claim()
        durable.finalize_turn(work, outputs=[{'body': 'La consulta cuesta 500.'}])
        self.response('Sí confirmo')
        self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')

    def test_consent_02_reject_never_cancels_business(self):
        self.proposal()
        self.response('No mejor no', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'REJECT')
        self.assertEqual(self.op.consent_state, 'REJECTED')
        self.assertIsNone(self.op.authorized_at)
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')

    def test_consent_03_correction_precedes_acceptance(self):
        self.proposal()
        self.response('Sí pero las 11', reply_to=self.msg.external_message_id)
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_consent_04_condition_is_not_unconditional_permission(self):
        self.proposal()
        self.response('Sí si hay espacio', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_consent_05_emoji_ambiguous(self):
        self.proposal()
        self.response('👍', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')

    def test_causal_09_incompatible_burst_has_no_terminal_acceptance(self):
        self.proposal()
        self.response()
        self.response('No')
        self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')
        self.assertEqual(len(durable.context_for_work(self.witness).events), 2)

    def test_rev_01_binding_change_invalidates(self):
        self.proposal()
        self.response()
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.change({'pet': self.max.pk})
        self.assertNotEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_rev_02_identity_change_invalidates(self):
        self.proposal()
        self.response()
        self.conv.contact.auto_rematch_blocked = True
        self.conv.contact.save(update_fields=['auto_rematch_blocked'])
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_rev_03_takeover_blocks(self):
        self.proposal()
        self.response()
        with transaction.atomic():
            durable.invalidate_ownership(self.conv, reason='test_takeover')
            self.conv.state = Conversation.STATE_HUMAN_ACTIVE
            self.conv.save(update_fields=['state'])
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_rev_05_expiry_does_not_extend_ttl(self):
        self.proposal()
        self.response()
        with patch('apps.agent.operation_consent.db_now', return_value=self.op.expires_at + timedelta(seconds=1)):
            self.assertEqual(self.evaluate().decision, 'STALE')
        self.assertEqual(self.op.consent_state, 'EXPIRED')

    def test_fi04_validation_before_commit_rolls_back_authorization(self):
        self.proposal()
        self.response()
        self.witness = self.claim()
        with patch('apps.agent.operation_consent._persist_decision', side_effect=DatabaseError('FI-10')):
            with self.assertRaises(DatabaseError):
                consent.evaluate_turn(self.witness)
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'PENDING')
        self.assertIsNone(self.op.authorization_message_id)
        self.assertEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')

    def test_fi05_commit_before_work_completion_recovery_is_idempotent(self):
        self.proposal()
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        TurnWork.objects.filter(pk=self.witness.turn_work_id).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
        self.witness = self.claim()
        self.assertTrue(consent.evaluate_turn(self.witness).duplicate)
        durable.finalize_turn(self.witness)
        self.assertEqual(ConversationOperation.objects.filter(consent_state='AUTHORIZED').count(), 1)

    def test_sender_blocks_proposal_after_correction_before_admission(self):
        self.proposal(False)
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        self.response('Mejor Max')
        self.assertIsNone(sender.admit_dispatch(claim))
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, 'discarded')

    def test_model_has_no_public_authorization_writer(self):
        from django.core.exceptions import ValidationError
        self.proposal()
        self.op.consent_state = 'AUTHORIZED'
        with self.assertRaises(ValidationError):
            self.op.save(validate=False)

    def test_emit_08_scope_and_semantic_content_are_exact(self):
        import copy
        self.proposal()
        for field, value in [('organization_id', 99999), ('conversation_id', 99999),
                ('contact_id', 99999), ('channel_account_id', 99999), ('body', 'Confirma'),
                ('operation_key', str(uuid.uuid4())), ('semantic_type', ''),
                ('origin_epoch', self.op.ownership_epoch+1), ('author_type', Message.AUTHOR_AGENT),
                ('external_message_id', 'invalid'), ('send_admitted_at', None)]:
            message = copy.copy(self.msg)
            setattr(message, field, value)
            with self.subTest(field=field):
                self.assertFalse(consent.is_proposal_emitted(self.op, message))

    def test_emit_09_superseded_proposal_not_authorizable(self):
        self.proposal()
        Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, contact=self.conv.contact, direction='out',
            author_type=Message.AUTHOR_HUMAN, body=self.msg.body,
            supersedes_message=self.msg, origin_epoch=self.conv.ownership_epoch)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')

    def test_causal_01_inbound_before_proposal_has_no_receipt(self):
        self.op = self.prepare()
        # The preparation turn itself cannot authorize its not-yet-published proposal.
        self.assertNotEqual(consent.evaluate_turn(self.witness).decision, 'ACCEPT')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_causal_07_other_contact_cannot_authorize_known_token(self):
        self.proposal()
        text = 'CONFIRMAR ' + consent.proposal_token(self.op)
        for wa_id in ('5215599999999', '5215511111111'):
            event = normalize_whatsapp_event({'type': 'text', 'text': {'body': text}})
            response = ingest_inbound_message(self.channel, wamid='wamid.'+uuid.uuid4().hex,
                wa_id=wa_id, body=text, raw={EVENT_METADATA_KEY: event.projection()})
            Message.objects.filter(pk=response.pk).update(available_at=None)
            witness = durable.claim_turn(response.conversation_id)
            self.assertNotEqual(consent.evaluate_turn(witness).decision, 'ACCEPT')
            durable.finalize_turn(witness)
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_causal_08_duplicate_webhook_does_not_create_new_membership(self):
        self.proposal()
        response = self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.assertIsNone(ingest_inbound_message(self.channel, wamid=response.external_message_id,
            wa_id='5215512345678', body='No'))
        self.assertTrue(consent.evaluate_turn(self.witness).duplicate)

    def test_receipt_cannot_be_supplied_or_mutated_by_raw_input(self):
        from apps.agent.operation_proposals import RECEIPT_KEY
        self.proposal(False)
        response = self.response(**{RECEIPT_KEY: {'version': 1, 'observed': [{'message_id': self.msg.pk,
            'field': 'provider_accepted_at'}], 'received_at': timezone.now().isoformat()}})
        self.assertEqual(response.raw_metadata[RECEIPT_KEY]['observed'], [])
        with self.assertRaises(DatabaseError), transaction.atomic():
            Message.objects.filter(pk=response.pk).update(raw_metadata={})

    def test_rev_04_permission_rechecked_even_without_revision_change(self):
        from apps.agent.operation_permission import ActorPermission
        self.proposal()
        self.response()
        with patch('apps.agent.operations.actor_permission', return_value=ActorPermission(
                'FORBIDDEN', 'revoked', {})):
            self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_rev_07_digest_corruption_cannot_authorize(self):
        from django.db import connection
        self.proposal()
        self.response()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE agent_conversationoperation SET parameters_digest=%s WHERE id=%s',
                           ['0'*64, self.op.pk])
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_rev_08_authorized_history_does_not_transfer_to_replacement(self):
        self.proposal()
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        durable.finalize_turn(self.witness)
        self.response('Mejor para Max')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.change({'pet': self.max.pk})
        self.observe_slot()
        replacement = self.prepare()
        self.assertEqual(replacement.replaces_id, self.op.pk)
        self.assertEqual(replacement.consent_state, 'PENDING')
        self.assertIsNone(replacement.authorization_message_id)
        self.assertIsNone(replacement.proposal_message_id)
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertIsNotNone(consent.authorization_evidence(self.op))

    def test_mode_01_to_05_contextual_declaration_never_authorizes(self):
        from apps.agent import goals
        self.bind_appointment(name='confirm_appointment')
        self.op = self.prepare('confirm_appointment')
        from .b8d_support import make_legacy_attendance
        make_legacy_attendance(self.op)
        self.assertEqual(self.op.authorization_mode, 'CONTEXTUAL_DECLARATION')
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.assertIsNone(self.op.proposal_message_id)
        self.response('Sí confirmo que asistiré')
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_int_01_authorized_does_not_open_any_business_write(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from apps.agent import tools
        from apps.agent.capabilities import OPERATIONS
        from apps.agent.intake import write_is_contained
        self.proposal()
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        executor = SimpleNamespace(conversation=self.conv,
            agent_user=SimpleNamespace(organization_id=self.org.pk), record_local=Mock())
        for name in OPERATIONS:
            self.assertTrue(write_is_contained(name))
            with patch.dict(tools.TOOL_SPECS[name], handler=Mock(side_effect=AssertionError('WRITE'))):
                outcome = tools.run_tool(name, {}, conversation=self.conv, executor=executor)
            self.assertEqual(outcome.client_error, 'autonomous_writes_paused')

    def test_int_02_worker_safety_precedes_consent(self):
        from apps.agent import worker, safety_handoff
        self.proposal()
        self.response('Sí pero ahora Luna no puede respirar', reply_to=self.msg.external_message_id)
        self.witness = self.claim()
        with override_settings(AGENT_SAFETY_AUTOMATION_ENABLED=True), patch.object(
                consent, 'evaluate_turn', side_effect=AssertionError('Consent preceded safety')):
            self.assertEqual(worker._run_turn(self.witness), 'safety_handoff')
        self.op.refresh_from_db()
        self.assertNotEqual(self.op.consent_state, 'AUTHORIZED')

    def test_int_05_worker_authorization_and_output_commit_together(self):
        from apps.agent import worker, planner
        self.proposal()
        self.response()
        self.witness = self.claim()
        with patch.object(planner, 'handle_inbound', side_effect=AssertionError('LLM is not authority')):
            self.assertEqual(worker._run_turn(self.witness), 'consent_accept')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(TurnWork.objects.get(pk=self.witness.turn_work_id).status, 'COMPLETED')
        self.assertEqual(Message.objects.filter(turn_work_id=self.witness.turn_work_id, direction='out').count(), 1)

    def test_int_08_legacy_json_is_not_synthetic_evidence(self):
        from .legacy_pending import seed_pending
        from apps.agent import confirmations
        self.proposal(False)
        seed_pending(self.conv, tool='create_appointment', args=self.op.parameters, paraphrase=self.msg.body)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertFalse(confirmations.is_confirmable(self.conv, confirmations.get_pending(self.conv)))

    def test_fi_local_publication_error_rolls_back_message_and_link(self):
        self.op = self.prepare()
        with patch('apps.agent.operation_proposals.observe', side_effect=DatabaseError('after link')):
            with self.assertRaises(DatabaseError):
                durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.assertIsNone(self.op.proposal_message_id)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.assertIsNotNone(self.op.proposal_message_id)

    def test_webhook_verified_reconciliation_then_new_response_is_eligible(self):
        import json
        from apps.channels.tests.test_webhook import SECRET, _sign
        self.proposal(False)
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('uncertain', provider_id='wamid.b7b-proposal'))
        payload = {'entry': [{'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': self.channel.external_account_id},
            'statuses': [{'id': 'wamid.b7b-proposal', 'status': 'delivered'}]}}]}]}
        body = json.dumps(payload).encode()
        with override_settings(WHATSAPP_APP_SECRET=SECRET):
            self.assertEqual(self.client.post('/hooks/whatsapp/', body, content_type='application/json',
                HTTP_X_HUB_SIGNATURE_256='sha256=invalid').status_code, 403)
            self.assertFalse(consent.is_proposal_emitted(self.op))
            self.assertEqual(self.client.post('/hooks/whatsapp/', body, content_type='application/json',
                HTTP_X_HUB_SIGNATURE_256=_sign(body)).status_code, 200)
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(consent.authorization_evidence(self.op).proposal_emission_evidence.field, 'delivered_at')

    def test_causal_05_reply_to_replaced_proposal_does_not_authorize_new_one(self):
        self.proposal()
        old = self.op
        old_message = self.msg
        self.response('Mejor para Max')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.change({'pet': self.max.pk})
        self.observe_slot()
        self.op = self.prepare()
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.msg = self.op.proposal_message
        claim = sender.claim_message(self.msg.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
        sender.admit_dispatch(claim)
        sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.proposal-B'))
        self.response('Sí confirmo', reply_to=old_message.external_message_id)
        self.assertEqual(self.evaluate().decision, 'STALE')
        self.assertEqual(self.op.consent_state, 'PENDING')
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'INVALIDATED')

    def test_scope_other_account_and_organization_do_not_authorize(self):
        from apps.channels.models import ChannelAccount
        from apps.organizations.models import Organization
        self.proposal()
        other_org = Organization.objects.create(name='Other tenant B7B')
        for org in (self.org, other_org):
            channel = ChannelAccount.objects.create(organization=org, external_account_id=uuid.uuid4().hex)
            event = normalize_whatsapp_event({'type': 'text', 'text': {'body': 'Sí confirmo'},
                                             'context': {'id': self.msg.external_message_id}})
            response = ingest_inbound_message(channel, wamid='wamid.' + uuid.uuid4().hex,
                wa_id='5215512345678', body=event.text, raw={EVENT_METADATA_KEY: event.projection()})
            Message.objects.filter(pk=response.pk).update(available_at=None)
            self.assertNotEqual(consent.evaluate_turn(durable.claim_turn(response.conversation_id)).decision, 'ACCEPT')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_proposal_token_collision_is_detected_without_publication(self):
        self.proposal()
        first = self.op
        self.response('Mejor para Max')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.change({'pet': self.max.pk})
        self.observe_slot()
        second = self.prepare()
        with patch('apps.agent.operation_proposals.proposal_token', return_value='COLLISION'):
            with self.assertRaisesMessage(ValueError, 'collision'):
                durable.finalize_turn(self.witness, proposal_operation=second)
        second.refresh_from_db()
        self.assertIsNone(second.proposal_message_id)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_inspector_distinguishes_consent_from_execution(self):
        from apps.agent.admin import ConversationOperationAdmin
        from django.contrib.admin.sites import AdminSite
        admin = ConversationOperationAdmin(ConversationOperation, AdminSite())
        self.op = self.prepare()
        self.assertEqual(admin.proposal_stage(self.op), 'PREPARED')
        durable.finalize_turn(self.witness, proposal_operation=self.op)
        self.op.refresh_from_db()
        self.msg = self.op.proposal_message
        self.assertEqual(admin.proposal_stage(self.op), 'PERSISTED')
        self.emit()
        self.assertEqual(admin.proposal_stage(self.op), 'EMISSION_VERIFIED')
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')
        self.assertFalse(admin.has_change_permission(None, self.op))

    def test_causal_06_multiple_plausible_proposals_fail_closed(self):
        # B6 normally prevents two foreground matters. Inject a second row and
        # bypass ONLY its matter revalidation to exercise the selection defense
        # against inconsistent historical/admin data; sender/receipt/locks are real.
        from apps.agent.models import ConversationGoal
        from apps.agent.operation_model_contract import _lifecycle
        from apps.agent.operation_proposals import render_proposal
        self.proposal()
        goal = ConversationGoal.objects.create(organization=self.org, conversation=self.conv,
            name=self.goal.name, status=ConversationGoal.STATUS_ABANDONED)
        data = {f.attname: getattr(self.op, f.attname) for f in self.op._meta.concrete_fields
                if f.attname not in {'id', 'operation_key', 'created_at', 'updated_at', 'proposal_message_id'}}
        data.update(goal_id=goal.pk, stage_key='inconsistent_fixture')
        token = operations._preparing.set(True)
        try:
            second = ConversationOperation.objects.create(**data)
        finally:
            operations._preparing.reset(token)
        message = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, contact=self.conv.contact, direction='out',
            author_type=Message.AUTHOR_SYSTEM, semantic_type=Message.SEMANTIC_CONFIRMATION,
            operation_key=str(second.operation_key), origin_epoch=second.ownership_epoch,
            turn_work=second.source_turn, output_ordinal=1, body=render_proposal(second))
        second.proposal_message = message
        token = _lifecycle.set('proposal')
        try:
            second.save(update_fields=['proposal_message'])
        finally:
            _lifecycle.reset(token)
        with patch('apps.agent.operations.revalidate', side_effect=lambda operation: operation):
            claim = sender.claim_message(message.pk, organization_id=self.org.pk, channel_account_id=self.channel.pk)
            sender.admit_dispatch(claim)
            sender.finalize_dispatch(claim, SendResult('accepted', provider_id='wamid.second-proposal'))
            self.response()
            self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')
        self.assertFalse(ConversationOperation.objects.filter(consent_state='AUTHORIZED').exists())

    def test_token_render_is_stable_across_application_secret_rotation(self):
        from apps.agent.operation_proposals import render_proposal
        self.proposal()
        original = render_proposal(self.op)
        with override_settings(SECRET_KEY='rotated-test-secret'):
            self.assertEqual(render_proposal(self.op), original)
            self.response()
            self.assertEqual(self.evaluate().decision, 'ACCEPT')

    def test_b4_observability_has_only_bounded_labels(self):
        self.proposal(False)
        with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
            self.emit()
        observed = [record for record in logs.records if record.msg == 'AGENT_B7B_PROPOSAL_EMISSION_VERIFIED']
        self.assertTrue(observed)
        for record in observed:
            for forbidden in ('operation_key', 'message_id', 'contact_id', 'phone', 'body'):
                self.assertNotIn(forbidden, record.__dict__)

    def test_exact_code_after_price_question_is_an_unambiguous_reference(self):
        self.proposal()
        self.response('¿Cuánto cuesta?')
        durable.finalize_turn(self.claim(), outputs=[{'body': 'La consulta cuesta 500.'}])
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')

    def test_unresolved_correction_flush_cannot_repropose_old_parameters(self):
        from apps.agent.turn_changes import TurnChanges
        self.proposal()
        self.response('Sí pero con la doctora Ana')
        self.witness = self.claim()
        self.conv.refresh_from_db()
        changes = TurnChanges(self.witness, self.conv)
        durable.finalize_turn(self.witness, changes=changes, outputs=[{'body': 'texto no autorizable'}])
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'INVALIDATED')
        self.assertEqual(ConversationOperation.objects.count(), 1)
        output = Message.objects.get(turn_work_id=self.witness.turn_work_id, direction='out')
        self.assertIn('invalidada', output.body)
        self.assertEqual(output.operation_key, '')

    def test_resolved_b6_correction_flush_publishes_new_exact_operation(self):
        from apps.agent.turn_changes import TurnChanges
        self.proposal()
        old = self.op
        self.response('Sí pero para Max')
        self.witness = self.claim()
        self.ctx = durable.context_for_work(self.witness)
        self.conv.refresh_from_db()
        changes = TurnChanges(self.witness, self.conv)
        with changes.activate():
            self.change({'pet': self.max.pk})
            self.observe_slot()
        durable.finalize_turn(self.witness, changes=changes)
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'INVALIDATED')
        new = ConversationOperation.objects.get(consent_state='PENDING')
        self.assertEqual(new.pet_id, self.max.pk)
        self.assertIsNotNone(new.proposal_message_id)
        self.assertIn('Max', new.proposal_message.body)
        self.assertIsNone(new.authorization_message_id)

    def test_human_owned_consent_finalization_publishes_no_bot_reply(self):
        self.proposal()
        with transaction.atomic():
            durable.invalidate_ownership(self.conv, reason='test_takeover')
            self.conv.state = Conversation.STATE_HUMAN_ACTIVE
            self.conv.save(update_fields=['state'])
        self.response()
        witness = self.claim()
        durable.finalize_turn(witness, evaluate_consent=True)
        self.assertFalse(Message.objects.filter(turn_work_id=witness.turn_work_id, direction='out').exists())
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_duplicate_provider_id_is_not_exact_emission_evidence(self):
        self.proposal()
        Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, contact=self.conv.contact, direction='out',
            author_type=Message.AUTHOR_HUMAN, body='another provider correlation',
            status='sent', external_message_id=self.msg.external_message_id)
        self.response()
        self.assertNotEqual(self.evaluate().decision, 'ACCEPT')
        self.assertEqual(self.op.consent_state, 'PENDING')

    def test_appointment_declaration_is_not_registration_or_cancellation_consent(self):
        self.proposal()
        for kind in ('REGISTER_PET', 'CANCEL_APPOINTMENT'):
            self.op.operation_kind = kind
            with self.subTest(kind=kind):
                self.assertNotEqual(consent.classify('Confirmo esa cita', self.op).decision, 'ACCEPT')

    def test_conditional_burst_retires_pending_before_a_later_yes(self):
        self.proposal()
        self.response()
        self.response('Sí si hay espacio')
        self.assertEqual(self.evaluate().decision, 'AMBIGUOUS')
        self.assertEqual(len(durable.context_for_work(self.witness).events), 2)
        self.assertEqual(self.op.consent_state, 'INVALIDATED')

    def test_b7a_appointment_without_visible_vet_snapshot_requires_new_definition(self):
        import json
        from django.db import connection
        self.bind_appointment(name='cancel_appointment')
        operation = self.prepare('cancel_appointment')
        # A real B7A definition predates the original-vet renderer snapshot.
        # Reproduce that historical shape without inventing proposal/evidence.
        old_preconditions = dict(operation.preconditions)
        old_preconditions['labels'] = dict(old_preconditions['labels'])
        old_preconditions['labels'].pop('original_veterinarian')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE agent_conversationoperation SET preconditions=%s::jsonb WHERE id=%s',
                [json.dumps(old_preconditions), operation.pk])
        operation.refresh_from_db()
        durable.finalize_turn(self.witness, proposal_operation=operation)
        operation.refresh_from_db()
        self.assertEqual(operation.consent_state, 'INVALIDATED')
        self.assertEqual(operation.invalidation_reason, 'proposal_contract_changed')
        self.assertIsNone(operation.proposal_message_id)
        self.assertFalse(Message.objects.filter(direction='out').exists())
