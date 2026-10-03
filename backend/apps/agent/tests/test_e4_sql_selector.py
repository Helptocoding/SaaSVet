"""Behavior and PostgreSQL plan guards for the E4 organization forecast relation."""
import random
import uuid
from datetime import timedelta

from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.agent import durable, worker
from apps.agent.models import Conversation, LLMCall, TurnWork
from apps.channels.models import Message
from . import test_b9a_e2e as b9a
from .b9a_harness import ApplicationHarness
from .e4_sql_oracle import old_selector
from . import test_e4_claim_yield as e4


class E4SQLSelectorTests(TransactionTestCase):
    setUp = e4.E4ClaimYieldTests.setUp
    inbound = e4.E4ClaimYieldTests.inbound
    pair = e4.E4ClaimYieldTests.pair

    def equivalent(self, now, excluded=()):
        before = list(TurnWork.objects.values('id', 'attempts', 'llm_calls_admitted'))
        expected = list(old_selector(now, excluded))
        with self.assertNumQueries(1):
            actual = list(worker._pending_conversation_candidates(now, excluded))
        self.assertEqual(actual, expected)
        orgs = dict(Conversation.objects.filter(pk__in=actual+expected)
                    .values_list('pk', 'organization_id'))
        self.assertEqual([orgs[x] for x in actual], [orgs[x] for x in expected])
        self.assertEqual(len(actual), len(set(orgs[x] for x in actual)))
        self.assertLessEqual(len(actual), 3)
        self.assertEqual(list(TurnWork.objects.values('id', 'attempts', 'llm_calls_admitted')), before)
        self.assertEqual(LLMCall.objects.count(), 0)
        return actual

    def test_sql_01_boundaries_safety_order_and_fallback_match_old(self):
        _, _, ready, future, clock = self.pair(prior_healthy=True)
        for delta, yields in ((.5, True), (1, True), (1.001, False)):
            Message.objects.filter(pk=future.pk).update(available_at=clock+timedelta(seconds=delta))
            self.assertEqual(self.equivalent(clock), [] if yields else [ready.conversation_id])
        Message.objects.filter(pk=future.pk).update(available_at=clock+timedelta(seconds=.5))
        self.assertEqual(self.equivalent(clock+timedelta(seconds=.5)),
                         [future.conversation_id, ready.conversation_id])
        self.assertEqual(self.equivalent(clock+timedelta(seconds=.5), [future.conversation_id]),
                         [ready.conversation_id])
        Message.objects.filter(pk=ready.pk).update(semantic_type=Message.SEMANTIC_SAFETY_SIGNAL)
        self.assertEqual(self.equivalent(clock), [ready.conversation_id])

    def test_sql_02_generated_states_match_order_yield_and_exclusions(self):
        _, _, ready, future, clock = self.pair(prior_healthy=True)
        _, channel, *_ = b9a.seed_domain('E4-SQL-NEVER')
        fresh = self.inbound(102, ApplicationHarness(channel))
        same_org = self.inbound(3)
        messages = [ready, future, fresh, same_org]
        works = list(TurnWork.objects.all())
        rng = random.Random(20261001)
        for index in range(160):
            with transaction.atomic(), self.subTest(state=index):
                for message in messages:
                    delta = rng.choice((None, -1, 0, .5, 1, 1.001, 10))
                    Message.objects.filter(pk=message.pk).update(
                        available_at=None if delta is None else clock+timedelta(seconds=delta),
                        status=rng.choice(('pending', 'pending', 'processed')),
                        semantic_type=rng.choice(('', '', Message.SEMANTIC_SAFETY_SIGNAL)))
                for work in works:
                    status = rng.choice((TurnWork.COMPLETED, TurnWork.PENDING, TurnWork.PROCESSING))
                    TurnWork.objects.filter(pk=work.pk).update(status=status,
                        attempts=1, lease_token=uuid.UUID(int=work.pk),
                        lease_expires_at=clock+timedelta(minutes=rng.choice((-5,5))),
                        next_attempt_at=rng.choice((None,clock-timedelta(minutes=5),clock+timedelta(minutes=5))))
                excluded = [m.conversation_id for m in messages if rng.random() < .2]
                self.equivalent(clock+timedelta(seconds=rng.choice((0,.5,1))), excluded)
                transaction.set_rollback(True)

    def test_sql_03_large_message_scans_do_not_repeat_per_conversation(self):
        self.assertEqual(connection.vendor, 'postgresql')
        _, harness, ready, future, clock = self.pair(prior_healthy=True)
        _, channel, *_ = b9a.seed_domain('E4-SQL-PLAN')
        third = self.inbound(102, ApplicationHarness(channel))
        durable.finalize_turn(durable.claim_turn(third.conversation_id))
        templates = [ready, future, third]
        Message.objects.filter(pk__in=[ready.pk,future.pk]).update(status='processed')
        conversations = Conversation.objects.bulk_create([
            Conversation(organization_id=templates[i%3].organization_id,
                channel_account_id=templates[i%3].channel_account_id,
                contact_id=templates[i%3].contact_id, last_activity_at=clock-timedelta(seconds=i))
            for i in range(100)])
        Message.objects.bulk_create([
            Message(organization_id=conversations[i%100].organization_id,
                channel_account_id=conversations[i%100].channel_account_id,
                contact_id=conversations[i%100].contact_id, conversation=conversations[i%100],
                direction='in', author_type='client', status='pending',
                available_at=clock-timedelta(seconds=1) if i<1600 else clock+timedelta(seconds=.5))
            for i in range(2000)], batch_size=500)
        def loops(selector):
            query, params = selector(now=clock).query.sql_with_params()
            with connection.cursor() as cursor:
                cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query, params)
                plan = cursor.fetchone()[0][0]['Plan']
            values = []
            def visit(node):
                if node.get('Relation Name') == 'channels_message':
                    values.append(node['Actual Loops'])
                for child in node.get('Plans', []):
                    visit(child)
            visit(plan)
            return values
        with connection.cursor() as cursor:
            for table in ('channels_message','agent_conversation','agent_turnwork','organizations_organization'):
                cursor.execute('ANALYZE '+table)
        self.assertGreater(max(loops(old_selector)), 50)
        new_loops = loops(worker._pending_conversation_candidates)
        self.assertTrue(new_loops)
        self.assertEqual(max(new_loops), 1, new_loops)
