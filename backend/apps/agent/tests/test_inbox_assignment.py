"""WA-ASN-01: tenant/RBAC boundary, fencing, committed audit and row locks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
from unittest.mock import patch
from uuid import uuid4

from django.core.cache import cache
from django.db import close_old_connections, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.agent import durable
from apps.agent.inbox_assignment import assign_conversation
from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.users.models import User


class AssignmentFixtures:
    @classmethod
    def build(cls):
        cls.org = Organization.objects.create(name='Asignación sintética')
        cls.other_org = Organization.objects.create(name='Otra asignación sintética')
        cls.actor = cls.make_user('reception', cls.org, ('agentinbox.claim', 'agentinbox.view', 'agentinbox.send'))
        cls.target = cls.make_user('vet', cls.org, ('agentinbox.send',))
        cls.target.first_name = 'Veterinaria sintética'
        cls.target.save(update_fields=['first_name'])
        cls.viewer = cls.make_user('viewer', cls.org, ('agentinbox.view',))
        cls.foreign = cls.make_user('foreign', cls.other_org, ('agentinbox.send',))
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='assignment')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='assignment')
        cls.convo = Conversation.objects.create(organization=cls.org, channel_account=cls.account, contact=cls.contact)
        cls.url = f'/api/inbox/conversations/{cls.convo.public_id}/assign/'
        cls.directory = '/api/inbox/assignable-users/'

    @classmethod
    def make_user(cls, username, org, codes):
        user = User.objects.create(username=username, organization=org, role='ASSISTANT')
        user.user_roles.all().delete()
        if codes is not None:
            role = Role.objects.create(organization=org, name='assignment-'+username)
            role.permissions.set([Permission.objects.get_or_create(code=code)[0] for code in codes])
            UserRole.objects.create(user=user, role=role)
        return user


class InboxAssignmentTests(AssignmentFixtures, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.actor)

    def assign(self, user=None, url=None):
        return self.client.post(url or self.url,
            {'user_public_id': str((user or self.target).public_id)}, format='json')

    def test_assign_to_colleague_and_multiple_cases(self):
        second = Conversation.objects.create(organization=self.org, contact=ContactIdentity.objects.create(
            organization=self.org, external_id='assignment-second'), channel_account=self.account)
        self.assertEqual(self.assign().status_code, 200)
        self.assertEqual(self.assign(url=f'/api/inbox/conversations/{second.public_id}/assign/').status_code, 200)
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.claimed_by, self.target)
        self.assertEqual(self.convo.state, 'human_active')
        self.assertIsNotNone(self.convo.claimed_at)

    def test_reassign_other_staff_and_self_are_allowed(self):
        self.convo.claimed_by = self.target
        self.convo.state = 'human_active'
        self.convo.save()
        self.assertEqual(self.assign(self.actor).status_code, 200)
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.claimed_by, self.actor)

    def test_same_assignment_is_idempotent(self):
        self.assertEqual(self.assign().status_code, 200)
        self.convo.refresh_from_db()
        before = (self.convo.ownership_epoch, self.convo.claimed_at, self.convo.updated_at)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.assertEqual(self.assign().status_code, 200)
        self.assertEqual(callbacks, [])
        self.convo.refresh_from_db()
        self.assertEqual(before, (self.convo.ownership_epoch, self.convo.claimed_at, self.convo.updated_at))

    def test_inactive_target_rejected(self):
        self.target.is_active = False
        self.target.save()
        self.assertEqual(self.assign().status_code, 400)

    def test_target_without_send_or_db_role_rejected(self):
        self.assertEqual(self.assign(self.viewer).status_code, 400)
        self.target.user_roles.all().delete()
        self.assertEqual(self.assign().status_code, 400)  # ASSISTANT legacy fallback must not grant it.

    def test_revoked_permission_after_directory_load_rejected(self):
        self.assertIn(str(self.target.public_id), {row['public_id'] for row in self.client.get(self.directory).data})
        self.target.user_roles.get().role.permissions.clear()
        self.assertEqual(self.assign().status_code, 400)

    def test_foreign_and_missing_target_indistinguishable_404(self):
        self.assertEqual(self.assign(self.foreign).status_code, 404)
        response = self.client.post(self.url, {'user_public_id': str(uuid4())}, format='json')
        self.assertEqual(response.status_code, 404)
        self.convo.refresh_from_db()
        self.assertIsNone(self.convo.claimed_by)

    def test_service_account_rejected_even_with_send(self):
        self.target.is_service_account = True
        self.target.save()
        self.assertEqual(self.assign().status_code, 400)

    def test_foreign_conversation_and_invalid_uuid_are_404(self):
        foreign_account = ChannelAccount.objects.create(organization=self.other_org, external_account_id='foreign-assignment')
        foreign_convo = Conversation.objects.create(organization=self.other_org, channel_account=foreign_account,
            contact=ContactIdentity.objects.create(organization=self.other_org, external_id='foreign-assignment'))
        for public_id in (foreign_convo.public_id, '1', uuid4()):
            self.assertEqual(self.assign(url=f'/api/inbox/conversations/{public_id}/assign/').status_code, 404)

    def test_invalid_target_body_is_400(self):
        for payload in ({}, {'user_public_id': 1}, {'user_public_id': None}, [], {'user_public_id': 'bad'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.url, payload, format='json').status_code, 400)

    def test_closed_conversation_stays_closed(self):
        self.convo.state = 'closed'
        self.convo.save()
        self.assertEqual(self.assign().status_code, 400)
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.state, 'closed')
        self.assertIsNone(self.convo.claimed_by)

    def test_actor_requires_claim_and_authentication_for_both_endpoints(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.assign().status_code, 403)
        self.assertEqual(self.client.get(self.directory).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.assign().status_code, 401)
        self.assertEqual(self.client.get(self.directory).status_code, 401)

    def test_directory_minimal_scoped_strict_and_bounded_queries(self):
        self.target.is_active = False
        self.target.save()
        self.make_user('legacy-only', self.org, None)
        service = self.make_user('service', self.org, ('agentinbox.send',))
        service.is_service_account = True
        service.save()
        for n in range(5):
            self.make_user(f'colleague-{n}', self.org, ('agentinbox.*', '*.*'))
        # Actor permission cached before measuring directory data queries.
        self.client.get(self.directory)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.directory)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row['public_id'] for row in response.data},
            {str(self.actor.public_id)} | {str(u.public_id) for u in User.objects.filter(username__startswith='colleague-')})
        self.assertTrue(all(set(row) == {'public_id', 'name'} for row in response.data))
        user_selects = [q for q in queries if 'FROM "users_user"' in q['sql']]
        self.assertEqual(len(user_selects), 1)

    def test_assignment_does_not_acknowledge_handoff_or_mark_read(self):
        handoff = HumanHandoff.objects.create(organization=self.org, conversation=self.convo, reason_code='emergency')
        self.assertEqual(self.assign().status_code, 200)
        handoff.refresh_from_db()
        self.assertIsNone(handoff.acknowledged_at)
        self.assertIsNone(handoff.acknowledged_by_id)

    def test_assignment_invalidates_pending_agent_authority(self):
        message = Message.objects.create(organization=self.org, channel_account=self.account,
            conversation=self.convo, direction='out', author_type='agent', status='pending', body='Synthetic')
        self.convo.processing_until = timezone.now()+timedelta(minutes=1)
        self.convo.save()
        epoch = self.convo.ownership_epoch
        self.assertEqual(self.assign().status_code, 200)
        self.convo.refresh_from_db()
        message.refresh_from_db()
        self.assertEqual(self.convo.ownership_epoch, epoch+1)
        self.assertIsNone(self.convo.processing_until)
        self.assertEqual(message.status, 'discarded')

    def test_committed_structured_audit_contains_ids_only(self):
        self.convo.claimed_by = self.actor
        self.convo.save()
        with patch('apps.agent.inbox_assignment.logger.info') as log:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.assign().status_code, 200)
            assignment_logs = [call for call in log.call_args_list if call.args == ('INBOX_CONVERSATION_ASSIGNED',)]
            self.assertEqual(len(assignment_logs), 1)
            extra = assignment_logs[0].kwargs['extra']
            self.assertEqual(extra['actor_public_id'], str(self.actor.public_id))
            self.assertEqual(extra['from_user_public_id'], str(self.actor.public_id))
            self.assertEqual(extra['to_user_public_id'], str(self.target.public_id))
            self.assertEqual(extra['conversation_public_id'], str(self.convo.public_id))
            self.assertEqual(set(extra), {'organization_public_id', 'conversation_public_id', 'actor_public_id',
                'from_user_public_id', 'to_user_public_id', 'assigned_at'})

    def test_rollback_has_no_assignment_or_audit(self):
        with patch('apps.agent.inbox_assignment.logger.info') as log:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    assign_conversation(self.convo, self.actor, self.target.public_id)
                    transaction.set_rollback(True)
            log.assert_not_called()
        self.convo.refresh_from_db()
        self.assertIsNone(self.convo.claimed_by_id)

    def test_assignment_moves_incremental_list_and_transcript(self):
        thread_url = f'/api/inbox/threads/{self.contact.public_id}/{self.account.public_id}/messages/'
        own = self.client.get('/api/inbox/threads/', {'claimed': 'me'}).data
        transcript = self.client.get(thread_url).data
        self.assertEqual(self.assign(self.actor).status_code, 200)
        delta = self.client.get('/api/inbox/threads/', {'claimed': 'me', 'since': own['sync_cursor']}).data
        self.assertEqual(len(delta['upserts']), 1)
        transcript_delta = self.client.get(thread_url, {'since': transcript['sync_cursor']}).data
        self.assertEqual(transcript_delta['metadata']['conversation']['claimed_by_name'], self.actor.username)
        self.assertEqual(self.assign().status_code, 200)
        removed = self.client.get('/api/inbox/threads/', {'claimed': 'me', 'since': delta['sync_cursor']}).data
        self.assertEqual(len(removed['removals']), 1)


class InboxAssignmentRaceTests(AssignmentFixtures, APITransactionTestCase):
    def setUp(self):
        cache.clear()
        self.build()

    def race(self, first):
        entered, release = threading.Event(), threading.Event()
        backend_pid = {}
        assignment_first = first == 'assign'
        module = 'apps.agent.inbox_assignment' if assignment_first else 'apps.agent.views'

        def fence(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Timed out releasing first row lock')
            return durable.invalidate_ownership(*args, **kwargs)

        def request(kind):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pid[kind] = cursor.fetchone()[0]
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=self.actor.pk))
                if kind == 'assign':
                    return client.post(self.url, {'user_public_id': str(self.target.public_id)}, format='json').status_code
                return client.post(f'/api/inbox/conversations/{self.convo.public_id}/claim/').status_code
            finally:
                connection.close()

        second = 'claim' if assignment_first else 'assign'
        with patch(module+'.invalidate_ownership', side_effect=fence):
            with ThreadPoolExecutor(max_workers=2) as pool:
                winner = pool.submit(request, first)
                try:
                    self.assertTrue(entered.wait(10), 'First request did not acquire Conversation lock')
                    waiter = pool.submit(request, second)
                    deadline = time.monotonic()+8
                    blocked = False
                    while time.monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [backend_pid.get(second)])
                            row = cursor.fetchone()
                        if row and row[0] == 'Lock':
                            blocked = True
                            break
                        time.sleep(0.03)
                    self.assertTrue(blocked, 'Second request must wait on the real database row lock')
                    self.assertFalse(waiter.done())
                finally:
                    release.set()
                self.assertEqual(winner.result(timeout=10), 200)
                self.assertEqual(waiter.result(timeout=10), 409 if assignment_first else 200)
        self.convo.refresh_from_db()
        self.assertEqual(self.convo.claimed_by, self.target)
        self.assertEqual(self.convo.state, 'human_active')

    def test_assign_first_claim_waits_then_conflicts(self):
        self.race('assign')

    def test_claim_first_assign_waits_then_transfers(self):
        self.race('claim')
