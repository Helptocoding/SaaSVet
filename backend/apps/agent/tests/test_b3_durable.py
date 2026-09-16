"""B3 acceptance: real PostgreSQL constraints, leases and local publication."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.db import DataError, IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.agent.models import Conversation, TurnWork
from apps.agent.services import ingest_inbound_message
from apps.agent import durable


class DurableTurnTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql', 'B3 requires PostgreSQL')
        self.org = Organization.objects.create(name='B3', timezone='UTC')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='b3-channel')
        self.m1 = self.inbound('m1')
        self.conv = self.m1.conversation

    def inbound(self, key):
        message = ingest_inbound_message(self.channel, wamid=key,
                                         wa_id='5215512345678', body=key)
        Message.objects.filter(pk=message.pk).update(available_at=None)
        return message

    def claim(self):
        return durable.claim_turn(self.conv.pk)

    def expire(self, witness):
        TurnWork.objects.filter(pk=witness.turn_work_id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1))

    def test_dur_01_reclaims_same_work_context_and_fences_old_token(self):
        m2 = self.inbound('m2')
        Message.objects.filter(conversation=self.conv).update(available_at=None)
        a = self.claim()
        before = durable.context_for_work(a)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.status, Message.STATUS_PENDING)
        self.expire(a)
        b = self.claim()
        self.assertEqual(a.turn_work_id, b.turn_work_id)
        self.assertNotEqual(a.lease_token, b.lease_token)
        self.assertEqual(before, durable.context_for_work(b))
        self.assertEqual(before.inbound_ids, (self.m1.pk, m2.pk))
        self.assertEqual(TurnWork.objects.get().attempts, 2)
        with self.assertRaises(durable.OwnershipLost):
            durable.assert_witness(a)
        durable.finalize_turn(b, outputs=[{'body': 'Respuesta'}])
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(Message.objects.filter(turn_work_id=b.turn_work_id,
                                               direction='out').count(), 1)

    def test_dup_01_live_lease_and_partial_unique_constraint(self):
        a = self.claim()
        self.assertIsNone(self.claim())
        m2 = self.inbound('m2')
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            TurnWork(organization=self.org, conversation=self.conv,
                anchor_message=m2, anchor_created_at=m2.created_at,
                cursor_message_id=m2.pk, cursor_created_at=m2.created_at,
                context_at=timezone.now(), clinic_timezone='UTC').save(validate=False)
        self.assertEqual(caught.exception.__cause__.diag.constraint_name, 'turnwork_one_nonterminal')
        self.assertEqual(TurnWork.objects.get().lease_token, a.lease_token)

    def test_input_01_members_fixed_and_defer_terminates_work(self):
        m2 = self.inbound('m2')
        Message.objects.filter(conversation=self.conv).update(available_at=None)
        a = self.claim()
        before = durable.context_for_work(a)
        m3 = self.inbound('m3')
        durable.finalize_turn(a, outputs=[{'body': 'Obsoleta'}])
        work = TurnWork.objects.get(pk=a.turn_work_id)
        self.assertEqual(work.status, TurnWork.COMPLETED)
        self.assertEqual(work.outcome_code, 'deferred_to_new_input')
        self.assertEqual(before.inbound_ids, (self.m1.pk, m2.pk))
        self.assertFalse(Message.objects.filter(direction='out').exists())
        m3.refresh_from_db()
        self.assertIsNone(m3.turn_work_id)
        b = self.claim()
        self.assertNotEqual(a.turn_work_id, b.turn_work_id)
        self.assertEqual(durable.context_for_work(b).inbound_ids, (m3.pk,))


class B3LocalIntegrationTests(TestCase):
    setUp = DurableTurnTests.setUp
    inbound = DurableTurnTests.inbound
    claim = DurableTurnTests.claim
    expire = DurableTurnTests.expire

    def enable_agent(self):
        from apps.agent.models import AgentSettings
        from apps.users.services import ensure_agent_user
        agent, _ = ensure_agent_user(self.org)
        return AgentSettings.objects.create(organization=self.org, enabled=True, agent_user=agent)

    def staff_client(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from apps.core.models import UserRole
        from .test_inbox_api import _seed_role_from_catalog
        user = get_user_model().objects.create_user(
            username='b3-admin', password=None, organization=self.org, role='ADMIN')
        UserRole.objects.get_or_create(user=user, role=_seed_role_from_catalog(self.org, 'ADMIN'))
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_takeover_api_and_return_advance_epoch_and_fence_old_worker(self):
        witness, changes = self.prepare()
        client = self.staff_client()
        base = f'/api/inbox/conversations/{self.conv.public_id}'
        self.assertEqual(client.post(base + '/claim/').status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
        self.assertEqual(client.post(base + '/claim/').status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(witness, outputs=changes.outputs, changes=changes)
        self.assertEqual(client.post(base + '/release/').status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 2)
        self.assertEqual(TurnWork.objects.get().status, TurnWork.FAILED)
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_reset_api_invalidates_work_and_next_inbound_opens_new_episode(self):
        witness = self.claim()
        response = self.staff_client().post(
            f'/api/inbox/conversations/{self.conv.public_id}/reset-identity/')
        self.assertEqual(response.status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
        self.assertEqual(self.conv.state, Conversation.STATE_CLOSED)
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(witness, outputs=[{'body': 'Stale'}])
        newer = self.inbound('after-reset')
        self.assertNotEqual(newer.conversation_id, self.conv.pk)
        self.assertIsNone(newer.turn_work_id)

    def test_human_reply_epoch_is_dispatchable_and_discards_pending_bot(self):
        from apps.agent.worker import _dispatch_rejection
        witness = self.claim()
        durable.finalize_turn(witness, outputs=[{'body': 'Bot'}])
        bot = Message.objects.get(direction='out')
        response = self.staff_client().post(
            f'/api/inbox/conversations/{self.conv.public_id}/send/',
            {'body': 'Respuesta humana'}, HTTP_X_IDEMPOTENCY_KEY='b3-human')
        self.assertEqual(response.status_code, 201)
        bot.refresh_from_db()
        self.assertEqual(bot.status, 'discarded')
        human = Message.objects.get(author_type=Message.AUTHOR_HUMAN)
        self.assertEqual(human.origin_epoch, 1)
        self.assertIsNone(human.turn_work_id)
        self.assertFalse(_dispatch_rejection(human))

    def test_periodic_close_does_not_invalidate_an_active_work(self):
        from apps.agent.policy import close_inactive_conversations
        old = timezone.now() - timedelta(days=2)
        Conversation.objects.filter(pk=self.conv.pk).update(last_activity_at=old)
        witness = self.claim()
        self.assertEqual(close_inactive_conversations(), 0)
        durable.assert_witness(witness)
        durable.finalize_turn(witness)
        self.assertEqual(close_inactive_conversations(), 1)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.ownership_epoch, 1)
        self.assertEqual(self.conv.state, Conversation.STATE_CLOSED)

    def test_periodic_nudge_cannot_bypass_work_authority(self):
        from apps.agent.policy import nudge_abandoned_flows
        settings = self.enable_agent()
        settings.nudge_enabled = True
        settings.save(update_fields=['nudge_enabled'])
        old = timezone.now() - timedelta(hours=2)
        Conversation.objects.filter(pk=self.conv.pk).update(
            last_inbound_at=old, flow={'pending_action': {'tool': 'create_appointment'}})
        witness = self.claim()
        self.assertEqual(nudge_abandoned_flows(), 0)
        durable.assert_witness(witness)
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_takeover_during_real_planning_fences_all_local_writes(self):
        from apps.agent import worker, planner
        from apps.agent.llm import LLMResult, StubLLMClient
        from apps.agent.models import TurnDecision, ConversationGoal
        self.enable_agent()
        stub = StubLLMClient(scripted=[])
        def takeover(**kwargs):
            with transaction.atomic():
                durable.invalidate_ownership(self.conv, reason='takeover')
                Conversation.objects.filter(pk=self.conv.pk).update(state=Conversation.STATE_HUMAN_ACTIVE)
            return LLMResult(kind='text', text='Respuesta que perdió autoridad.')
        with patch.object(planner, 'get_llm_client', return_value=stub), patch.object(stub, 'complete', side_effect=takeover):
            worker.process_pending_conversations()
        self.assertEqual(TurnWork.objects.get().status, TurnWork.FAILED)
        self.assertFalse(TurnDecision.objects.exists())
        self.assertFalse(ConversationGoal.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.total_llm_calls, 0)

    def test_new_inbound_and_duplicate_webhook_during_real_planning(self):
        from apps.agent import worker, planner
        from apps.agent.llm import LLMResult, StubLLMClient
        self.enable_agent()
        self.assertIsNone(ingest_inbound_message(self.channel, wamid='m1',
            wa_id='5215512345678', body='duplicate'))
        stub = StubLLMClient(scripted=[])
        def incoming(**kwargs):
            self.inbound('m2')
            self.assertIsNone(ingest_inbound_message(self.channel, wamid='m2',
                wa_id='5215512345678', body='duplicate during work'))
            return LLMResult(kind='text', text='Hola, puedo ayudarte.')
        with patch.object(planner, 'get_llm_client', return_value=stub), patch.object(stub, 'complete', side_effect=incoming):
            worker.process_pending_conversations()
        work = TurnWork.objects.get()
        self.assertEqual(work.outcome_code, 'deferred_to_new_input')
        self.assertEqual(Message.objects.filter(turn_work=work, direction='in').count(), 1)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(Message.objects.filter(direction='in').count(), 2)
        self.assertEqual(durable.context_for_work(self.claim()).texts, ('m2',))

    def test_request_human_tool_case_and_receipt_are_one_commit(self):
        from apps.agent import worker, planner
        from apps.agent.llm import LLMResult, StubLLMClient
        from apps.agent.models import HumanHandoff, ToolExecution
        self.enable_agent()
        stub = StubLLMClient(scripted=[
            LLMResult(kind='tool_call', tool_name='request_human', tool_args={}),
            LLMResult(kind='text', text='Registré la solicitud.')])
        with patch.object(planner, 'get_llm_client', return_value=stub):
            worker.process_pending_conversations()
        self.assertEqual(TurnWork.objects.get().status, TurnWork.COMPLETED)
        self.assertEqual(HumanHandoff.objects.filter(conversation=self.conv).count(), 1)
        self.assertEqual(ToolExecution.objects.get().result_summary_redacted['_outcome_v1']['kind'], 'EFFECT')
        out = Message.objects.get(direction='out')
        self.assertIsNotNone(out.turn_work_id)
        self.assertNotIn('ya avisé', out.body.lower())

    def test_retry_after_database_failure_does_not_duplicate_local_state(self):
        witness, changes = self.prepare()
        from apps.agent.models import ConversationGoal
        with patch.object(Message, 'save', side_effect=IntegrityError('final failure')):
            with self.assertRaises(IntegrityError):
                durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
        self.expire(witness)
        next_witness = self.claim()
        durable.finalize_turn(next_witness, outputs=[{'body': 'Recovered'}])
        self.assertEqual(TurnWork.objects.count(), 1)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)
        self.assertFalse(ConversationGoal.objects.exists())

    def test_expired_token_cannot_finalize_or_release_after_reclaim(self):
        witness = self.claim()
        self.expire(witness)
        new = self.claim()
        for action in (lambda: durable.fail_turn(witness),
                       lambda: durable.finalize_turn(witness, outputs=[{'body': 'old'}])):
            with self.assertRaises(durable.OwnershipLost):
                action()
        work = TurnWork.objects.get()
        self.assertEqual(work.lease_token, new.lease_token)
        self.assertEqual(work.status, TurnWork.PROCESSING)

    def test_processing_until_is_not_a_second_authority(self):
        Conversation.objects.filter(pk=self.conv.pk).update(
            processing_until=timezone.now() + timedelta(days=1))
        witness = self.claim()
        self.assertIsNotNone(witness)
        Conversation.objects.filter(pk=self.conv.pk).update(processing_until=None)
        self.assertIsNone(self.claim())

    def test_scoped_buffer_cannot_cross_witness(self):
        witness, changes = self.prepare()
        with self.assertRaises(ValueError):
            durable.finalize_turn(replace(witness, organization_id=self.org.pk+1000), changes=changes)
        self.assertFalse(Message.objects.filter(direction='out').exists())

    def test_database_clock_controls_lease_even_with_future_poll_time(self):
        witness = self.claim()
        self.assertIsNone(durable.claim_turn(self.conv.pk, eligible_at=timezone.now()+timedelta(days=1)))
        self.assertEqual(TurnWork.objects.get().lease_token, witness.lease_token)

    def test_deadline_stops_local_changes_without_heartbeat(self):
        from apps.agent.turn_changes import TurnChanges
        witness = self.claim()
        TurnWork.objects.filter(pk=witness.turn_work_id).update(
            claimed_at=timezone.now()-durable.TURN_DEADLINE-timedelta(seconds=1))
        with self.assertRaises(TimeoutError), TurnChanges(witness, self.conv).activate():
            self.fail('expired deadline admitted planning')

    def prepare(self):
        from apps.agent.turn_changes import TurnChanges
        from apps.agent import goals
        from apps.agent.models import ConversationGoal, TurnDecision
        from apps.agent.outbound import enqueue_outbound
        from apps.agent.turn_changes import create_local, save_local
        witness = self.claim()
        changes = TurnChanges(witness, self.conv)
        with changes.activate():
            goal = goals.open_goal(self.conv, goals.SCHEDULE, authorization_message=self.m1)
            goal.slots = {'reason': {'value': 'consulta', 'confidence': 1.0}}
            save_local(goal, update_fields=['slots'])
            self.conv.flow = {'b3_local': True}
            save_local(self.conv, update_fields=['flow'])
            create_local(TurnDecision, organization=self.org, conversation=self.conv,
                         verdict='reply', because=TurnDecision.Because.PLANNER_HANDLED,
                         triggered_by_message=self.m1)
            enqueue_outbound(self.conv, 'Respuesta final')
        self.assertFalse(ConversationGoal.objects.filter(conversation=self.conv).exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertFalse(TurnDecision.objects.filter(conversation=self.conv).exists())
        return witness, changes

    def test_dur_02_before_final_transaction_has_no_durable_changes(self):
        from apps.agent.models import ConversationGoal, TurnDecision
        witness, changes = self.prepare()
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PROCESSING)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow, {})
        self.expire(witness)
        recovered = self.claim()
        self.assertEqual(witness.turn_work_id, recovered.turn_work_id)
        self.assertFalse(ConversationGoal.objects.exists())
        self.assertFalse(TurnDecision.objects.exists())

    def test_dur_02_failure_after_local_flush_rolls_back_everything(self):
        from apps.agent.models import ConversationGoal, TurnDecision
        witness, changes = self.prepare()
        with patch.object(Message, 'save', side_effect=IntegrityError('final DB failure')):
            with self.assertRaises(IntegrityError):
                durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow, {})
        self.assertFalse(ConversationGoal.objects.exists())
        self.assertFalse(TurnDecision.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PROCESSING)

    def test_dur_02_success_commits_correlated_local_state_and_output(self):
        from apps.agent.models import ConversationGoal, TurnDecision
        witness, changes = self.prepare()
        durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
        self.assertEqual(ConversationGoal.objects.get().slots['reason']['value'], 'consulta')
        self.assertEqual(TurnDecision.objects.get().facts_produced['turn_work_id'], witness.turn_work_id)
        out = Message.objects.get(direction='out')
        self.assertEqual((out.turn_work_id, out.output_ordinal, out.status),
                         (witness.turn_work_id, 0, 'pending'))
        self.assertEqual(TurnWork.objects.get().status, TurnWork.COMPLETED)

    def test_real_postgres_error_after_outbound_insert_rolls_back_final_commit(self):
        from apps.agent.models import ConversationGoal, TurnDecision
        witness, changes = self.prepare()
        real_save = Message.save
        def fail_after_insert(message, *args, **kwargs):
            real_save(message, *args, **kwargs)
            self.assertTrue(Message.objects.filter(pk=message.pk).exists())
            self.assertTrue(ConversationGoal.objects.exists())
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 / 0')
        with patch.object(Message, 'save', new=fail_after_insert), self.assertRaises(DataError):
            durable.finalize_turn(witness, outputs=changes.outputs, changes=changes)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.flow, {})
        self.assertFalse(ConversationGoal.objects.exists())
        self.assertFalse(TurnDecision.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PROCESSING)

    def test_existing_poll_recovers_expired_work_without_unassigned_input(self):
        from apps.agent.worker import process_pending_conversations
        witness = self.claim()
        self.expire(witness)
        self.assertFalse(Message.objects.filter(direction='in', turn_work__isnull=True).exists())
        self.assertEqual(process_pending_conversations(), 1)
        work = TurnWork.objects.get()
        self.assertEqual((work.pk, work.status, work.attempts),
                         (witness.turn_work_id, TurnWork.COMPLETED, 2))
        self.assertEqual(Message.objects.get(direction='out').output_ordinal, 0)

    def test_own_01_staged_state_rejected_after_takeover(self):
        from apps.agent.models import ConversationGoal
        from apps.agent.turn_changes import save_local
        witness, changes = self.prepare()
        with transaction.atomic():
            durable.invalidate_ownership(self.conv, reason='takeover')
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
        with self.assertRaises(durable.OwnershipLost), changes.activate():
            self.conv.flow = {'stale': True}
            save_local(self.conv, update_fields=['flow'])
        self.assertFalse(ConversationGoal.objects.exists())
        self.assertFalse(Message.objects.filter(direction='out').exists())




    def test_processed_01_real_worker_planning_sees_pending_members(self):
        from apps.agent import worker, planner
        from apps.agent.models import AgentSettings
        from apps.agent.llm import StubLLMClient, LLMResult
        from apps.users.services import ensure_agent_user
        agent, _ = ensure_agent_user(self.org)
        AgentSettings.objects.create(organization=self.org, enabled=True, agent_user=agent)
        stub = StubLLMClient(scripted=[LLMResult(kind='text', text='Hola, puedo ayudarte.')])
        complete = stub.complete
        def during(**kwargs):
            self.assertEqual(Message.objects.get(pk=self.m1.pk).status, 'pending')
            self.assertFalse(Message.objects.filter(direction='out').exists())
            return complete(**kwargs)
        with patch.object(planner, 'get_llm_client', return_value=stub), patch.object(stub, 'complete', side_effect=during):
            self.assertEqual(worker.process_pending_conversations(), 1)
        self.assertEqual(Message.objects.get(pk=self.m1.pk).status, 'processed')
        self.assertEqual(TurnWork.objects.get().status, TurnWork.COMPLETED)

    def test_starve_01_repeated_new_input_finishes_each_fixed_work(self):
        from apps.agent.models import ConversationGoal
        witness, changes = self.prepare()
        for index in range(5):
            newer = self.inbound(f'new-{index}')
            durable.finalize_turn(witness, changes=changes, outputs=changes.outputs)
            self.assertEqual(TurnWork.objects.get(pk=witness.turn_work_id).outcome_code,
                             'deferred_to_new_input')
            self.assertEqual(TurnWork.objects.get(pk=witness.turn_work_id).attempts, 1)
            witness = self.claim()
            self.assertEqual(durable.context_for_work(witness).inbound_ids, (newer.pk,))
            from apps.agent.turn_changes import TurnChanges
            self.conv.refresh_from_db()
            changes = TurnChanges(witness, self.conv)
        self.assertEqual(ConversationGoal.objects.get().slots['reason']['value'], 'consulta')
        durable.finalize_turn(witness, outputs=[{'body': 'Final'}])
        self.assertEqual(TurnWork.objects.filter(status=TurnWork.COMPLETED).count(), 6)
        self.assertEqual(Message.objects.filter(direction='out').count(), 1)

    def test_retry_limit_backoff_and_failed_never_processed(self):
        for attempt in range(1, durable.MAX_ATTEMPTS + 1):
            witness = self.claim()
            durable.fail_turn(witness, 'llm_timeout')
            work = TurnWork.objects.get()
            self.assertEqual(work.attempts, attempt)
            self.assertIsNone(self.claim())
            if attempt < durable.MAX_ATTEMPTS:
                TurnWork.objects.filter(pk=work.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(work.status, TurnWork.FAILED)
        self.assertEqual(work.outcome_code, 'llm_timeout')
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.status, 'pending')

    def test_cross_org_message_and_work_rejected_by_database(self):
        witness = self.claim()
        other = Organization.objects.create(name='Tenant B', timezone='UTC')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=self.m1.pk).update(organization=other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TurnWork.objects.filter(pk=witness.turn_work_id).update(organization=other)

    def test_membership_and_cursor_immutable_in_database(self):
        witness = self.claim()
        newer = self.inbound('late')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=newer.pk).update(turn_work_id=witness.turn_work_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=self.m1.pk).update(turn_work=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TurnWork.objects.filter(pk=witness.turn_work_id).update(cursor_message_id=newer.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=self.m1.pk).update(payload_type='image')

    def test_older_unclaimed_input_cannot_join_already_claimed_membership(self):
        Message.objects.filter(pk=self.m1.pk).update(available_at=timezone.now()+timedelta(hours=1))
        newer = self.inbound('eligible')
        witness = self.claim()
        self.assertEqual(durable.context_for_work(witness).inbound_ids, (newer.pk,))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=self.m1.pk).update(turn_work_id=witness.turn_work_id)

    def test_retry_pending_does_not_reopen_membership(self):
        middle = self.inbound('temporarily-ineligible')
        last = self.inbound('last')
        Message.objects.filter(pk__in=(self.m1.pk, last.pk)).update(available_at=None)
        Message.objects.filter(pk=middle.pk).update(available_at=timezone.now()+timedelta(hours=1))
        witness = self.claim()
        self.assertEqual(durable.context_for_work(witness).inbound_ids, (self.m1.pk, last.pk))
        durable.fail_turn(witness)
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PENDING)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Message.objects.filter(pk=middle.pk).update(turn_work_id=witness.turn_work_id)

    def test_epoch_is_monotonic_in_database(self):
        Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=1)

    def test_ordinal_unique_constraint_on_postgres(self):
        witness = self.claim()
        durable.finalize_turn(witness, outputs=[{'body': 'A'}, {'body': 'B'}])
        rows = list(Message.objects.filter(direction='out').order_by('output_ordinal'))
        self.assertEqual([r.output_ordinal for r in rows], [0, 1])
        row = rows[0]
        row.pk = None
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            row.save(validate=False, force_insert=True)
        self.assertEqual(caught.exception.__cause__.diag.constraint_name, 'message_unique_turn_output')

    def test_own_01_takeover_rejects_publication_and_completion(self):
        a = self.claim()
        with transaction.atomic():
            conv = Conversation.objects.select_for_update().get(pk=self.conv.pk)
            durable.invalidate_ownership(conv, reason='takeover')
            conv.state = Conversation.STATE_HUMAN_ACTIVE
            conv.save(update_fields=['state'])
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(a, outputs=[{'body': 'Vieja'}])
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.assertEqual(TurnWork.objects.get().status, TurnWork.FAILED)

    def test_dur_02_db_failure_rolls_back_completion_and_output(self):
        a = self.claim()
        with patch.object(Message, 'save', side_effect=IntegrityError('injected')):
            with self.assertRaises(IntegrityError):
                durable.finalize_turn(a, outputs=[{'body': 'Respuesta'}])
        self.assertEqual(TurnWork.objects.get().status, TurnWork.PROCESSING)
        self.assertFalse(Message.objects.filter(direction='out').exists())
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.status, Message.STATUS_PENDING)

    def test_ordinal_01_completion_cannot_publish_twice(self):
        a = self.claim()
        durable.finalize_turn(a, outputs=[{'body': 'Una'}])
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(a, outputs=[{'body': 'Dos'}])
        out = Message.objects.get(direction='out')
        self.assertEqual(out.output_ordinal, 0)
        self.assertEqual(out.origin_epoch, a.ownership_epoch)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.status, Message.STATUS_PROCESSED)

    def test_tenant_01_forged_witness_is_rejected(self):
        a = self.claim()
        other = Organization.objects.create(name='Other', timezone='UTC')
        with self.assertRaises(durable.OwnershipLost):
            durable.finalize_turn(replace(a, organization_id=other.pk),
                                  outputs=[{'body': 'No'}])
        self.assertFalse(Message.objects.filter(direction='out').exists())


class B3SenderCompatibilityTests(TransactionTestCase):
    """B3 sender regressions with actual commit boundaries required by B4."""
    setUp = DurableTurnTests.setUp
    claim = DurableTurnTests.claim
    inbound = DurableTurnTests.inbound

    def test_legacy_01_sender_discards_ambiguous_without_fabricating_epoch(self):
        from apps.agent.worker import send_pending_outbound
        out = Message.objects.create(organization=self.org, conversation=self.conv,
            channel_account=self.channel, direction='out', body='legacy', status='pending',
            author_type=Message.AUTHOR_SYSTEM)
        provider = __import__('unittest.mock', fromlist=['Mock']).Mock()
        send_pending_outbound(provider_factory=provider)
        out.refresh_from_db()
        self.assertEqual((out.status, out.failure_reason), ('discarded', 'legacy_unverified'))
        self.assertIsNone(out.turn_work_id)
        self.assertIsNone(out.origin_epoch)
        provider.assert_not_called()


    def test_sender_dispatches_valid_b3_output(self):
        from apps.agent.worker import send_pending_outbound
        from unittest.mock import Mock
        witness = self.claim()
        durable.finalize_turn(witness, outputs=[{'body': 'B3'}])
        provider = Mock()
        from apps.channels.providers import SendResult
        provider.return_value.send_text.return_value = SendResult('accepted', 'wamid.b3')
        send_pending_outbound(provider_factory=provider)
        out = Message.objects.get(direction='out')
        self.assertEqual(out.status, 'sent')
        self.assertEqual(out.external_message_id, 'wamid.b3')
        provider.return_value.send_text.assert_called_once()


    def test_sender_rechecks_epoch_at_dispatch(self):
        from apps.agent.worker import send_pending_outbound
        from unittest.mock import Mock
        witness = self.claim()
        durable.finalize_turn(witness, outputs=[{'body': 'Stale'}])
        Conversation.objects.filter(pk=self.conv.pk).update(ownership_epoch=1)
        provider = Mock()
        send_pending_outbound(provider_factory=provider)
        self.assertEqual(Message.objects.get(direction='out').failure_reason, 'ownership_invalidated')
        provider.assert_not_called()
