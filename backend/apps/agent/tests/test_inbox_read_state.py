"""WA-UNR-01: independent staff read cursors, episode counts and real PG races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, local
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.agent.models import ContactIdentity, Conversation, InboxReadState
from apps.channels.models import ChannelAccount, Message
from apps.core.models import TenantQuerySet
from apps.organizations.models import Organization
from apps.users.models import User


def build_fixture(target):
    target.org = Organization.objects.create(name='Lectura por empleado', timezone='UTC')
    target.a = User.objects.create_user(username='read-a', organization=target.org, role='ASSISTANT')
    target.b = User.objects.create_user(username='read-b', organization=target.org, role='VET')
    target.account = ChannelAccount.objects.create(organization=target.org, external_account_id='read-main')
    target.contact = ContactIdentity.objects.create(organization=target.org, external_id='read-contact')
    now = timezone.now()
    target.old = Conversation.objects.create(
        organization=target.org, contact=target.contact, channel_account=target.account,
        state='closed', closed_at=now - timedelta(days=1), last_activity_at=now - timedelta(days=1),
    )

    def message(session, status='processed', direction='in'):
        return Message.objects.create(
            organization=session.organization, contact=session.contact,
            channel_account=session.channel_account, conversation=session,
            body='Contenido sintético', direction=direction,
            author_type='client' if direction == 'in' else 'agent', status=status,
        )

    target.old_message = message(target.old)
    target.current = Conversation.objects.create(
        organization=target.org, contact=target.contact, channel_account=target.account,
        last_activity_at=now, claimed_by=target.a,
    )
    target.incoming = [message(target.current, status) for status in ('processed', 'pending', 'failed')]
    target.hidden = message(target.current, 'discarded')
    target.outgoing = message(target.current, 'failed', 'out')
    target.other_account = ChannelAccount.objects.create(organization=target.org, external_account_id='read-other')
    target.other_session = Conversation.objects.create(
        organization=target.org, contact=target.contact, channel_account=target.other_account,
    )
    target.other_message = message(target.other_session)
    target.other_contact = ContactIdentity.objects.create(organization=target.org, external_id='read-other-contact')
    target.other_contact_session = Conversation.objects.create(
        organization=target.org, contact=target.other_contact, channel_account=target.account,
    )
    target.other_contact_message = message(target.other_contact_session)
    target.foreign_org = Organization.objects.create(name='Otra clínica', timezone='UTC')
    target.foreign_user = User.objects.create_user(
        username='read-foreign', organization=target.foreign_org, role='ADMIN',
    )
    target.foreign_account = ChannelAccount.objects.create(
        organization=target.foreign_org, external_account_id='read-foreign',
    )
    target.foreign_contact = ContactIdentity.objects.create(
        organization=target.foreign_org, external_id=target.contact.external_id,
    )
    target.foreign_session = Conversation.objects.create(
        organization=target.foreign_org, contact=target.foreign_contact,
        channel_account=target.foreign_account,
    )
    target.foreign_message = message(target.foreign_session)
    target.read_url = reverse('inbox-thread-read', args=[
        str(target.contact.public_id), str(target.account.public_id),
    ])


class InboxReadStateTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        build_fixture(cls)

    def setUp(self):
        self.client.force_authenticate(self.a)

    def count(self, *, account=None, contact=None, archived=False):
        response = self.client.get(reverse('inbox-threads'), {'archived': '1'} if archived else {})
        self.assertEqual(response.status_code, 200)
        return next(row['unread_count'] for row in response.data['results']
                    if row['contact_public_id'] == str((contact or self.contact).public_id)
                    and row['channel_account_public_id'] == str((account or self.account).public_id))

    def read(self, message, **extra):
        response = self.client.post(
            self.read_url, {'last_read_message_id': message.pk, **extra}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        return response.data

    def state(self, user=None):
        return InboxReadState.objects.for_organization(self.org).get(
            user=user or self.a, contact=self.contact, channel_account=self.account,
        )

    def test_baseline_counts_only_visible_inbound_in_current_episode(self):
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.count(account=self.other_account), 1)
        self.assertEqual(self.count(contact=self.other_contact), 1)
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_partial_read_decreases_count_and_persists_audit_actor(self):
        data = self.read(self.incoming[0])
        self.assertEqual(data, {'last_read_message_id': self.incoming[0].pk, 'unread_count': 2, 'unread_total': 4})
        self.assertEqual(self.count(), 2)
        state = self.state()
        self.assertEqual(state.created_by_id, self.a.pk)
        self.assertEqual(state.updated_by_id, self.a.pk)

    def test_two_staff_have_independent_counts_and_view_only_can_read(self):
        self.read(self.incoming[-1])
        self.assertEqual(self.count(), 0)
        self.client.force_authenticate(self.b)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.read(self.incoming[0])['unread_count'], 2)
        self.assertEqual(self.state(self.a).last_read_message_id, self.incoming[-1].pk)
        self.assertEqual(self.state(self.b).last_read_message_id, self.incoming[0].pk)

    def test_repeated_or_older_mark_does_not_regress_or_change_timestamp(self):
        self.read(self.incoming[-1])
        state = self.state()
        for target in (self.incoming[-1], self.incoming[0], self.old_message):
            with self.subTest(message=target.pk):
                self.assertEqual(self.read(target), {
                    'last_read_message_id': self.incoming[-1].pk, 'unread_count': 0, 'unread_total': 2,
                })
                self.assertEqual(self.state().updated_at, state.updated_at)
        self.assertEqual(InboxReadState.objects.for_organization(self.org).count(), 1)

    def test_new_message_after_read_increases_count(self):
        self.read(self.incoming[-1])
        Message.objects.create(
            organization=self.org, contact=self.contact, channel_account=self.account,
            conversation=self.current, direction='in', author_type='client',
            status='pending', body='Llegó después',
        )
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.read(self.incoming[0])['unread_count'], 1)

    def test_old_episode_message_is_allowed_without_reading_current_episode(self):
        self.assertEqual(self.read(self.old_message)['unread_count'], 3)
        self.assertEqual(self.state().last_read_message_id, self.old_message.pk)

    def test_read_is_scoped_to_account_and_contact(self):
        self.read(self.incoming[-1])
        self.assertEqual(self.count(account=self.other_account), 1)
        self.assertEqual(self.count(contact=self.other_contact), 1)

    def test_archived_thread_has_zero_unread_and_can_record_read(self):
        Conversation.objects.filter(pk=self.current.pk).update(state='closed', closed_at=timezone.now())
        self.assertEqual(self.count(archived=True), 0)
        self.assertEqual(self.read(self.incoming[-1])['unread_count'], 0)
        reopened = Conversation.objects.create(
            organization=self.org, contact=self.contact, channel_account=self.account,
        )
        Message.objects.create(
            organization=self.org, contact=self.contact, channel_account=self.account,
            conversation=reopened, direction='in', author_type='client', status='processed', body='Regresó',
        )
        self.assertEqual(self.count(), 1)

    def test_only_current_head_counts_when_several_open_episodes_exist(self):
        newer = Conversation.objects.create(
            organization=self.org, contact=self.contact, channel_account=self.account,
            last_activity_at=timezone.now() + timedelta(minutes=1),
        )
        self.assertEqual(self.count(), 0)
        Message.objects.create(
            organization=self.org, contact=self.contact, channel_account=self.account,
            conversation=newer, direction='in', author_type='client', status='processed', body='Vigente',
        )
        self.assertEqual(self.count(), 1)

    def test_outbound_and_discarded_inbound_are_rejected_without_write(self):
        for target in (self.outgoing, self.hidden):
            with self.subTest(message=target.pk):
                response = self.client.post(self.read_url, {'last_read_message_id': target.pk}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_read_message')
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_foreign_missing_and_other_thread_targets_are_404(self):
        for pk in (self.foreign_message.pk, self.other_message.pk,
                   self.other_contact_message.pk, 9223372036854775807):
            with self.subTest(pk=pk):
                response = self.client.post(self.read_url, {'last_read_message_id': pk}, format='json')
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data['code'], 'not_found')
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_foreign_route_is_404_and_cannot_create_read_state(self):
        self.client.force_authenticate(self.foreign_user)
        response = self.client.post(self.read_url, {'last_read_message_id': self.incoming[0].pk}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(InboxReadState.objects.for_organization(self.foreign_org).exists())

    def test_client_cannot_mark_another_users_state(self):
        self.read(self.incoming[-1], user=self.b.pk, organization=self.foreign_org.pk)
        self.assertEqual(self.state().last_read_message_id, self.incoming[-1].pk)
        self.assertFalse(InboxReadState.objects.for_organization(self.org).filter(user=self.b).exists())

    def test_malformed_body_is_rejected_without_write(self):
        bodies = [{}, {'last_read_message_id': None}, {'last_read_message_id': True}]
        bodies += [{'last_read_message_id': value} for value in (
            0, -1, 'bad', '1.5', 9223372036854775808, [], {}, '9' * 5000,
        )]
        for body in bodies:
            with self.subTest(body=str(body)[:100]):
                response = self.client.post(self.read_url, body, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_read_request')
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_auth_and_permission_are_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.read_url, {'last_read_message_id': self.incoming[0].pk}).status_code, 401)
        agent = User.objects.create_user(username='read-agent', organization=self.org, role='AGENT')
        self.client.force_authenticate(agent)
        self.assertEqual(self.client.post(self.read_url, {'last_read_message_id': self.incoming[0].pk}).status_code, 403)
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_get_requests_do_not_mark_read(self):
        self.count()
        url = reverse('inbox-thread-messages', args=[str(self.contact.public_id), str(self.account.public_id)])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_read_does_not_change_messages_claim_or_episode_authority(self):
        before = list(Message.objects.for_organization(self.org).values())
        conversation_before = Conversation.objects.for_organization(self.org).get(pk=self.current.pk).__dict__.copy()
        self.client.force_authenticate(self.b)
        self.read(self.incoming[-1])
        self.assertEqual(list(Message.objects.for_organization(self.org).values()), before)
        after = Conversation.objects.for_organization(self.org).get(pk=self.current.pk).__dict__
        self.assertEqual({k: v for k, v in after.items() if k != '_state'},
                         {k: v for k, v in conversation_before.items() if k != '_state'})

    def test_null_marker_is_the_same_baseline_as_no_state(self):
        InboxReadState.objects.create(
            organization=self.org, user=self.a, contact=self.contact, channel_account=self.account,
        )
        self.assertEqual(self.count(), 3)

    def test_model_rejects_cross_org_relations_and_wrong_thread_or_direction(self):
        for override in ({'user': self.foreign_user}, {'contact': self.foreign_contact},
                         {'channel_account': self.foreign_account}, {'last_read_message': self.foreign_message},
                         {'last_read_message': self.other_message}, {'last_read_message': self.outgoing}):
            with self.subTest(fields=list(override)):
                state = InboxReadState(organization=self.org, user=self.a, contact=self.contact,
                                       channel_account=self.account, **{})
                for name, value in override.items():
                    setattr(state, name, value)
                with self.assertRaises(ValidationError):
                    state.full_clean()

    def test_database_enforces_one_state_per_user_and_thread(self):
        self.read(self.incoming[0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            InboxReadState.objects.bulk_create([InboxReadState(
                organization=self.org, user=self.a, contact=self.contact, channel_account=self.account,
            )])

    def test_unread_counts_use_id_not_provider_or_local_timestamp(self):
        Message.objects.filter(pk=self.incoming[-1].pk).update(created_at=timezone.now() - timedelta(days=100))
        self.assertEqual(self.read(self.incoming[0])['unread_count'], 2)

    def test_counts_are_batched_without_loading_message_or_read_state_instances(self):
        self.read(self.incoming[0])
        self.client.get(reverse('inbox-threads'))
        from django.db import connection
        with patch.object(Message, 'from_db', wraps=Message.from_db) as messages:
            with patch.object(InboxReadState, 'from_db', wraps=InboxReadState.from_db) as states:
                with CaptureQueriesContext(connection) as captured:
                    self.assertEqual(self.count(), 2)
        self.assertEqual(messages.call_count, 0)
        self.assertEqual(states.call_count, 0)
        # La cabecera ya agrega el número de sesiones; aislar la agregación unread.
        aggregates = [q['sql'] for q in captured
                      if 'COUNT(' in q['sql'] and 'agent_inboxreadstate' in q['sql']]
        self.assertEqual(len(aggregates), 2)
        self.assertEqual(sum('GROUP BY' in query for query in aggregates), 1)


class InboxReadConcurrencyTests(APITransactionTestCase):
    def setUp(self):
        build_fixture(self)

    def race(self, *, first_create):
        start = Barrier(2)
        missing = Barrier(2)
        seen = local()
        original_get = TenantQuerySet.get

        def get(queryset, *args, **kwargs):
            try:
                return original_get(queryset, *args, **kwargs)
            except InboxReadState.DoesNotExist:
                if first_create and queryset.model is InboxReadState and not getattr(seen, 'waited', False):
                    seen.waited = True
                    missing.wait(timeout=20)
                raise

        def worker(pk):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.a.pk, organization=self.org)
                client = APIClient()
                client.force_authenticate(user)
                start.wait(timeout=20)
                response = client.post(self.read_url, {'last_read_message_id': pk}, format='json')
                return response.status_code, response.data
            finally:
                connections.close_all()

        with patch.object(TenantQuerySet, 'get', get), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [self.incoming[0].pk, self.incoming[-1].pk]))
        self.assertEqual([status for status, _ in results], [200, 200])
        states = InboxReadState.objects.for_organization(self.org).filter(
            user=self.a, contact=self.contact, channel_account=self.account,
        )
        self.assertEqual(states.count(), 1)
        self.assertEqual(states.get().last_read_message_id, self.incoming[-1].pk)

    def test_first_create_race_is_one_row_with_highest_marker(self):
        self.race(first_create=True)

    def test_existing_row_race_never_loses_the_highest_marker(self):
        InboxReadState.objects.create(
            organization=self.org, user=self.a, contact=self.contact, channel_account=self.account,
            last_read_message=self.old_message,
        )
        self.race(first_create=False)
