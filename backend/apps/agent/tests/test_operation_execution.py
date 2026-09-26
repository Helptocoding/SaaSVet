"""B8A contract tests: real consent, isolated adapters; no business WRITE."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch, Mock
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.agent import durable, operation_execution as execution
from apps.agent.models import ConversationOperation, Conversation, ToolExecution, HumanHandoff, TurnWork
from apps.channels.models import Message
from .b8a_support import setup_domain, effect_count, enabled_test_adapter, LocalTestAdapter
from .test_operation_consent import ConsentFixtures


class ExecutionFixtures(ConsentFixtures):
    def setUp(self):
        super().setUp()
        setup_domain()

    def authorized(self):
        self.proposal()
        self.response()
        self.assertEqual(self.evaluate().decision, 'ACCEPT')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        return self.op

    def execute(self):
        return execution.execute_authorized_operation(self.op.operation_key, self.context)

    def tamper(self, **values):
        # Deliberate damaged historical/admin state, never a production writer.
        import json
        from psycopg import sql
        with connection.cursor() as c:
            assignments = sql.SQL(', ').join(sql.SQL('{} = %s').format(sql.Identifier(field)) for field in values)
            c.execute(sql.SQL('UPDATE agent_conversationoperation SET {} WHERE id = %s').format(assignments),
                [json.dumps(value) if isinstance(value, dict) else value for value in values.values()] + [self.op.pk])
        self.op.refresh_from_db()

    def denied(self, reason=None):
        with enabled_test_adapter():
            result = self.execute()
        self.assertEqual(result.status, 'DENIED')
        if reason:
            self.assertEqual(result.reason, reason)
        self.assertEqual(effect_count(), 0)
        return result

    def takeover(self):
        with transaction.atomic():
            conv = Conversation.objects.select_for_update().get(pk=self.conv.pk)
            durable.invalidate_ownership(conv, reason='test_takeover')
            conv.state = Conversation.STATE_HUMAN_ACTIVE
            conv.save(update_fields=['state'])

    def correct(self):
        self.ctx = durable.context_for_work(self.witness)
        self.change({'pet': self.max.pk})


@override_settings(AGENT_B7B_CONSENT_ENABLED=True)
class OperationExecutionTests(ExecutionFixtures, TestCase):
    def test_auth_01_pending_never_executes(self):
        self.op = self.prepare()
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        self.assertEqual(self.execute().reason, 'consent_not_authorized')
        self.op.refresh_from_db()
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')

    def test_gate_01_authorized_b0_closed(self):
        self.authorized()
        self.assertEqual(self.execute().reason, 'containment_closed')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertEqual(self.op.execution_state, 'NOT_STARTED')

    def test_gate_02_schema_and_authorization_do_not_enable_kind(self):
        self.authorized()
        with patch('apps.agent.intake.write_is_contained', return_value=False):
            # B8B registers CREATE, but schema/consent cannot open its flag.
            self.assertEqual(self.execute().reason, 'flag_disabled')

    def test_gate_04_unknown_capability(self):
        self.authorized()
        self.context = replace(self.context, capability='invented_write')
        self.assertEqual(self.execute().reason, 'capability_mismatch')

    def test_registry_all_five_kinds_closed(self):
        from django.conf import settings
        self.assertEqual(set(execution.REGISTRY), set(ConversationOperation.KINDS))
        self.assertTrue(all(entry.enabled and entry.adapter is not None
                            for kind, entry in execution.REGISTRY.items()
                            if kind == 'REGISTER_PET'))
        # B8B is technically present, effective production execution stays closed.
        self.assertTrue(execution.REGISTRY['CREATE_APPOINTMENT'].enabled)
        self.assertIsNotNone(execution.REGISTRY['CREATE_APPOINTMENT'].adapter)
        self.assertEqual(getattr(settings, 'AGENT_OPERATION_EXECUTION_ENABLED', {}), {})

    def test_auth_02_rejected(self):
        self.proposal()
        self.response('No', reply_to=self.msg.external_message_id)
        self.assertEqual(self.evaluate().decision, 'REJECT')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        self.denied('consent_not_authorized')

    def test_auth_03_expired_before_consent(self):
        self.op = self.prepare()
        ConversationOperation.objects.filter(pk=self.op.pk).retire_pending('EXPIRED', 'ttl_elapsed')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        self.denied('consent_not_authorized')

    def test_auth_04_invalidated(self):
        self.op = self.prepare()
        ConversationOperation.objects.filter(pk=self.op.pk).retire_pending('INVALIDATED', 'correction')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        self.denied('consent_not_authorized')

    def test_auth_05_incomplete_evidence(self):
        self.authorized()
        self.tamper(authorization_message_id=self.op.source_message_id)
        self.denied('authorization_evidence_invalid')

    def test_auth_06_digest_mismatch(self):
        self.authorized()
        self.tamper(parameters_digest='0'*64)
        self.denied('digest_mismatch')

    def test_auth_07_proposal_not_emitted(self):
        self.authorized()
        Message.objects.filter(pk=self.msg.pk).update(status='uncertain', uncertain_at=timezone.now())
        self.denied('authorization_evidence_invalid')

    def test_auth_08_not_causal(self):
        self.authorized()
        self.tamper(authorized_at=self.op.created_at, consent_decided_at=self.op.created_at)
        self.denied('authorization_evidence_invalid')

    def test_auth_09_contextual_mode_disabled(self):
        self.bind_appointment(name='confirm_appointment')
        self.op = self.prepare('confirm_appointment')
        from .b8d_support import make_legacy_attendance
        make_legacy_attendance(self.op)
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'confirm_appointment')
        self.denied('consent_not_authorized')
        # Even injected terminal state cannot enable contextual mode. No B7B
        # writer can produce this; reproduce a damaged/legacy database record.
        now = timezone.now()
        self.tamper(consent_state='AUTHORIZED', authorized_at=now, consent_decided_at=now,
            proposal_message_id=self.op.source_message_id, authorization_message_id=self.op.source_message_id,
            authorization_channel='whatsapp', authorization_policy_version=1)
        with patch.object(execution.operation_consent, 'execution_authorization_evidence') as evidence:
            self.denied('authorization_mode_disabled')
            evidence.assert_not_called()

    def test_inactive_pet_is_ineligible(self):
        from apps.patients.models import Pet
        self.authorized()
        Pet.all_objects.filter(pk=self.luna.pk).update(is_active=False)
        self.denied('entity_inactive')

    def test_blocked_precondition_survives_intervening_permission_denial(self):
        from apps.agent.operation_permission import ActorPermission
        self.authorized()
        with enabled_test_adapter() as adapter:
            adapter.validate_preconditions = Mock(return_value=execution.PreconditionResult(False, 'slot_unavailable'))
            self.assertEqual(self.execute().reason, 'slot_unavailable')
            with patch.object(execution.operation_permission, 'actor_permission', return_value=ActorPermission(
                    'FORBIDDEN', 'revoked', {})):
                self.assertEqual(self.execute().reason, 'permission_forbidden')
            self.assertEqual(self.execute().reason, 'slot_unavailable')
        self.assertEqual(effect_count(), 0)

    def test_auth_10_legacy_confirmation(self):
        from .legacy_pending import seed_pending
        self.op = self.prepare()
        seed_pending(self.conv, tool='create_appointment', args=self.op.parameters, paraphrase='yes')
        self.context = execution.ExecutionContext(self.witness, self.conv.contact_id, 'create_appointment')
        self.denied('consent_not_authorized')

    def test_authorized_expired_preserves_historical_evidence(self):
        self.authorized()
        # Freeze only the execution clock; do not change immutable TTL/proposal.
        with patch.object(execution.durable, 'db_now', return_value=self.op.expires_at + timedelta(seconds=1)):
            self.denied('operation_expired')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')
        self.assertIsNotNone(execution.operation_consent.authorization_evidence(self.op))

    def test_rev_01_binding_revision(self):
        self.authorized()
        self.correct()
        self.denied('binding_stale')

    def test_rev_02_identity_revision(self):
        self.authorized()
        contact = self.conv.contact
        contact.verified_at = timezone.now()
        contact.save(update_fields=['verified_at'])
        self.denied('identity_stale')

    def test_rev_03_ownership_revision(self):
        self.authorized()
        Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=self.witness.ownership_epoch+1)
        self.denied('ownership_lost')

    def test_rev_04_permission_revoked(self):
        from apps.agent.operation_permission import ActorPermission
        self.authorized()
        with patch.object(execution.operation_permission, 'actor_permission', return_value=ActorPermission(
                'FORBIDDEN', 'revoked', {})) as permission:
            self.denied('permission_forbidden')
        self.assertEqual(permission.call_args.kwargs, {'purpose': 'execute'})

    def test_rev_05_cross_tenant_entity(self):
        from apps.organizations.models import Organization
        from apps.patients.models import Pet
        self.authorized()
        other = Organization.objects.create(name='Other B8A')
        Pet.all_objects.filter(pk=self.luna.pk).update(organization=other)
        self.denied('entity_scope')

    def test_rev_06_takeover(self):
        self.authorized()
        self.takeover()
        self.denied('ownership_lost')

    def test_rev_07_safety_handoff(self):
        self.authorized()
        HumanHandoff.objects.create(organization=self.org, conversation=self.conv, reason_code=HumanHandoff.REASON_EXPLICIT)
        self.denied('safety_handoff')

    def test_rev_08_replaced(self):
        self.authorized()
        old = self.op
        durable.finalize_turn(self.witness)
        self.response('Mejor para Max')
        self.witness = self.claim()
        self.correct()
        self.observe_slot()
        newer = self.prepare()
        self.assertEqual(newer.replaces_id, old.pk)
        self.context = replace(self.context, witness=self.witness)
        self.denied('binding_stale')
        old.refresh_from_db()
        self.assertEqual(old.consent_state, 'AUTHORIZED')

    def test_gate_03_missing_adapter(self):
        self.authorized()
        with enabled_test_adapter(), patch.dict(execution.REGISTRY, CREATE_APPOINTMENT=
                execution.Registration('create_appointment', True, None)):
            self.assertEqual(self.execute().reason, 'adapter_missing')

    def test_gate_05_missing_flag(self):
        self.authorized()
        with enabled_test_adapter(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={}):
            self.assertEqual(self.execute().reason, 'flag_disabled')

    def test_flag_truthy_value_is_not_enabled(self):
        self.authorized()
        with enabled_test_adapter(), override_settings(AGENT_OPERATION_EXECUTION_ENABLED={'CREATE_APPOINTMENT': 'true'}):
            self.assertEqual(self.execute().reason, 'flag_disabled')

    def test_unknown_external_adapter_transaction_contract_is_closed(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.transaction_mode = 'REMOTE'
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().reason, 'adapter_contract_disabled')

    def test_result_01_success_requires_durable_evidence(self):
        self.authorized()
        with enabled_test_adapter():
            result = self.execute()
        self.assertEqual(result.status, 'SUCCEEDED')
        self.assertEqual(effect_count(), 1)
        self.op.refresh_from_db()
        self.assertEqual(self.op.result['evidence']['operation_key'], str(self.op.operation_key))
        self.assertEqual(result.evidence.parameters_digest, self.op.parameters_digest)
        self.assertEqual(self.op.executed_at, result.evidence.committed_at)

    def test_result_02_definitive_failure_without_effect(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(return_value=execution.AdapterResult('FAILED',
            reason='definitive_rejection', no_effect_confirmed=True,
            operation_key=self.op.operation_key, parameters_digest=self.op.parameters_digest))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'FAILED')
            self.assertEqual(self.execute().status, 'FAILED')
        adapter.execute.assert_called_once()
        self.assertEqual(effect_count(), 0)

    def test_result_03_timeout_is_uncertain(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(side_effect=TimeoutError('possible commit'))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        self.op.refresh_from_db()
        self.assertTrue(self.op.result['reconciliation_required'])

    def test_result_04_uncertain_never_reexecutes_even_if_absent(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(side_effect=TimeoutError())
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        adapter.execute.assert_called_once()

    def test_result_05_success_duplicate(self):
        self.authorized()
        with enabled_test_adapter() as adapter, patch.object(adapter, 'execute', wraps=adapter.execute) as effect:
            first, second = self.execute(), self.execute()
        self.assertEqual(first.evidence, second.evidence)
        self.assertTrue(second.duplicate)
        effect.assert_called_once()
        self.assertEqual(effect_count(), 1)

    def test_result_06_failure_never_means_success(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(return_value=execution.AdapterResult('FAILED', reason='definitive_rejection'))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')

    def test_result_07_response_without_durable_row_never_succeeds(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(return_value=execution.AdapterResult('SUCCEEDED', execution.EffectEvidence(
            self.op.operation_key, self.op.parameters_digest, str(uuid4()), timezone.now())))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        self.assertEqual(effect_count(), 0)

    def test_result_08_reconcile_effect_without_reexecute(self):
        self.authorized()
        adapter = LocalTestAdapter()
        # Persisted inside the TestCase transaction. Real separate commit is FI-03.
        adapter.execute(self.op, self.context)
        adapter.execute = Mock(side_effect=AssertionError('duplicate effect'))
        with enabled_test_adapter(adapter):
            result = self.execute()
        self.assertEqual(result.status, 'SUCCEEDED')
        self.assertTrue(result.duplicate)
        adapter.execute.assert_not_called()
        self.assertEqual(effect_count(), 1)

    def test_uncertain_resolved_only_by_definitive_domain_absence(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.execute = Mock(side_effect=TimeoutError())
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
            adapter.reconcile = Mock(return_value=execution.AdapterResult('FAILED',
                reason='reconciled_no_effect', no_effect_confirmed=True,
                operation_key=self.op.operation_key, parameters_digest=self.op.parameters_digest))
            self.assertEqual(self.execute().status, 'FAILED')
        adapter.execute.assert_called_once()

    def test_no_effect_proof_cannot_be_transferred_from_another_operation(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.reconcile = Mock(return_value=execution.AdapterResult('ABSENT', no_effect_confirmed=True,
            operation_key=uuid4(), parameters_digest=self.op.parameters_digest))
        adapter.execute = Mock(side_effect=AssertionError('unproven absence'))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        adapter.execute.assert_not_called()
        self.assertEqual(effect_count(), 0)

    def test_contradictory_attempt_is_not_not_started_proof(self):
        self.authorized()
        ToolExecution.objects.create(organization=self.org, conversation=self.conv, operation=self.op,
            tool_name='create_appointment', policy_decision='confirmed', http_status=200)
        with enabled_test_adapter():
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        self.assertEqual(effect_count(), 0)

    def test_blocked_label_cannot_hide_contradictory_effect_evidence(self):
        self.authorized()
        self.tamper(result={'schema': 1, 'status': 'BLOCKED', 'operation_key': str(self.op.operation_key),
            'no_effect_confirmed': False, 'reconciliation_required': False,
            'evidence': {'domain_object_id': str(uuid4())}})
        with enabled_test_adapter():
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        self.assertEqual(effect_count(), 0)

    def test_denial_does_not_erase_contradictory_result(self):
        self.authorized()
        previous = {'status': 'SUCCEEDED', 'evidence': {'domain_object_id': str(uuid4())}}
        self.tamper(result=previous, parameters_digest='0'*64)
        self.denied('digest_mismatch')
        self.op.refresh_from_db()
        self.assertEqual(self.op.result, previous)
        self.assertEqual(execution.execution_stage(self.op), 'INCONSISTENT / RECONCILIATION_PENDING')

    def test_confirmed_result_can_be_replayed_after_ttl_without_new_effect(self):
        self.authorized()
        with enabled_test_adapter():
            first = self.execute()
            with patch.object(execution.durable, 'db_now', return_value=self.op.expires_at + timedelta(seconds=1)):
                second = self.execute()
        self.assertEqual(first.evidence, second.evidence)
        self.assertTrue(second.duplicate)
        self.assertEqual(effect_count(), 1)

    def test_uncertain_reconciles_after_binding_change_without_new_effect(self):
        self.authorized()
        adapter = LocalTestAdapter()
        with enabled_test_adapter(adapter), patch.object(adapter, 'execute', side_effect=TimeoutError()):
            self.assertEqual(self.execute().status, 'UNCERTAIN')
        adapter.execute(self.op, self.context)
        self.correct()
        with enabled_test_adapter(adapter):
            result = self.execute()
        self.assertEqual(result.status, 'SUCCEEDED')
        self.assertTrue(result.duplicate)
        self.assertEqual(effect_count(), 1)

    def test_definitive_precondition_failure_cannot_be_retried(self):
        self.authorized()
        adapter = LocalTestAdapter()
        adapter.validate_preconditions = Mock(return_value=execution.PreconditionResult(False, 'slot_unavailable'))
        with enabled_test_adapter(adapter):
            self.assertEqual(self.execute().reason, 'slot_unavailable')
            adapter.validate_preconditions.return_value = execution.PreconditionResult(True)
            self.assertEqual(self.execute().reason, 'slot_unavailable')
        adapter.validate_preconditions.assert_called_once()
        self.assertEqual(effect_count(), 0)

    def test_transient_precondition_failure_can_be_reevaluated(self):
        self.authorized()
        adapter = LocalTestAdapter()
        with enabled_test_adapter(adapter), patch.object(adapter, 'validate_preconditions',
                side_effect=TimeoutError()):
            self.assertEqual(self.execute().reason, 'precondition_infrastructure')
        with enabled_test_adapter():
            self.assertEqual(self.execute().status, 'SUCCEEDED')

    def test_later_revocation_blocks_even_after_turn_processed(self):
        self.authorized()
        durable.finalize_turn(self.witness)
        self.response('No, olvida la propuesta')
        self.witness = self.claim()
        self.context = replace(self.context, witness=self.witness)
        self.denied('authorization_superseded_by_input')
        self.op.refresh_from_db()
        self.assertEqual(self.op.consent_state, 'AUTHORIZED')

    def test_new_input_blocks_old_worker(self):
        self.authorized()
        self.response('Mejor las 11')
        self.denied('new_input')

    def test_no_alternative_parameters_or_string_key(self):
        self.authorized()
        with self.assertRaises(TypeError):
            execution.execute_authorized_operation(self.op.operation_key, self.context, parameters={'pet_id': self.max.pk})
        self.assertEqual(execution.execute_authorized_operation(str(self.op.operation_key), self.context).status, 'DENIED')

    def test_result_fields_cannot_be_written_by_ordinary_orm(self):
        self.authorized()
        for field, value in (('execution_state', 'SUCCEEDED'), ('result', {'status': 'SUCCEEDED'})):
            self.op.refresh_from_db()
            setattr(self.op, field, value)
            with self.assertRaises(ValidationError):
                self.op.save(validate=False)

    def test_b8a_never_exports_model_write_tool_even_if_b0_hypothetically_open(self):
        from apps.agent import tools
        from types import SimpleNamespace
        self.authorized()
        executor = SimpleNamespace(conversation=self.conv,
            agent_user=SimpleNamespace(organization_id=self.org.pk), record_local=Mock())
        with patch('apps.agent.intake.write_is_contained', return_value=False):
            for capability in execution.OPERATIONS:
                with patch.dict(tools.TOOL_SPECS[capability], handler=Mock(side_effect=AssertionError('WRITE'))):
                    self.assertEqual(tools.run_tool(capability, {'operation_key': str(self.op.operation_key)},
                        conversation=self.conv, executor=executor).client_error, 'operation_guard_required')

    def test_agent_jwt_domain_routes_denied_without_affecting_staff(self):
        from apps.users.models import User
        from rest_framework.test import APIClient
        from apps.agent.executor import mint_agent_token
        user = User.objects.create(organization=self.org, username='b8a-agent', role='AGENT')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + mint_agent_token(user))
        for path, method in (('/api/appointments/', 'post'), ('/api/appointments/create-with-patient/', 'post'),
                ('/api/pets/', 'post'), ('/api/owners/', 'post'),
                ('/api/appointments/' + str(uuid4()) + '/status/', 'patch'),
                ('/api/appointments/' + str(uuid4()) + '/', 'patch')):
            with self.subTest(path=path):
                self.assertEqual(getattr(client, method)(path, {}, format='json', secure=True).status_code, 403)
        self.assertFalse(execution.agent_api_write_denied(self.vet, 'POST'))

    def test_observability_and_readonly_inspector(self):
        from apps.agent.admin import ConversationOperationAdmin
        from django.contrib.admin.sites import AdminSite
        self.authorized()
        admin = ConversationOperationAdmin(ConversationOperation, AdminSite())
        self.assertEqual(admin.execution_stage(self.op), 'AUTHORIZED_NOT_EXECUTED')
        with self.assertLogs('agent.events', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
            self.execute()
        self.op.refresh_from_db()
        self.assertEqual(admin.execution_stage(self.op), 'BLOCKED_BY_GATE')
        for record in logs.records:
            if str(record.msg).startswith('AGENT_B8A_'):
                self.assertIn(record.event, execution.EVENTS)
                for key in ('operation_key', 'message_id', 'contact_id', 'phone', 'body'):
                    self.assertNotIn(key, record.__dict__)
        self.assertFalse(admin.has_change_permission(None, self.op))
