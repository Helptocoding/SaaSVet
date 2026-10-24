"""WA-HIST-03: bounded historical windows, operational visibility and scope."""
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.agent.models import ContactIdentity, Conversation
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.users.models import User

from .test_inbox_threads import ThreadsTestCase


class ThreadAroundTests(ThreadsTestCase):
    def setUp(self):
        super().setUp()
        self.old = self._session(
            state=Conversation.STATE_CLOSED, closed=timezone.now() - timedelta(days=60),
        )
        self.current = self._session()
        self.messages = Message.objects.bulk_create([
            Message(
                organization=self.org, contact=self.contact,
                channel_account=self.channel,
                conversation=self.old if index < 100 else self.current,
                direction=Message.DIRECTION_IN, author_type=Message.AUTHOR_CLIENT,
                status=Message.STATUS_PROCESSED, body=f'Histórico {index}',
            ) for index in range(200)
        ])
        self.start = timezone.now() - timedelta(days=90)
        for index, message in enumerate(self.messages):
            message.created_at = self.start + timedelta(minutes=index)
        Message.objects.bulk_update(self.messages, ['created_at'])
        self.url = reverse('inbox-thread-messages', args=[
            str(self.contact.public_id), str(self.channel.public_id),
        ])

    def _around(self, index=100):
        response = self.client.get(self.url, {'around': self.messages[index].pk})
        self.assertEqual(response.status_code, 200)
        return response.data

    def _assert_window(self, index, start, stop, has_older, has_newer):
        data = self._around(index)
        expected = [message.pk for message in self.messages[start:stop]]
        self.assertEqual([row['id'] for row in data['messages']], expected)
        self.assertEqual(len(set(expected)), len(data['messages']))
        self.assertIs(data['has_older'], has_older)
        self.assertIs(data['has_newer'], has_newer)
        self.assertEqual(data['next_before'], expected[0] if has_older else None)
        self.assertTrue(all(row['is_hidden'] is False for row in data['messages']))
        # A historical destination must never restore the closed episode as current.
        self.assertEqual(data['conversation']['public_id'], str(self.current.public_id))

    def test_first_message(self):
        self._assert_window(0, 0, 25, False, True)

    def test_near_start_in_closed_history(self):
        self._assert_window(10, 0, 35, False, True)

    def test_middle_crosses_sessions(self):
        self._assert_window(100, 75, 125, True, True)

    def test_near_end(self):
        self._assert_window(190, 165, 200, True, False)

    def test_last_message(self):
        self._assert_window(199, 174, 200, True, False)

    def test_exact_window_boundaries_have_no_false_continuation(self):
        self._assert_window(25, 0, 50, False, True)
        self._assert_window(175, 150, 200, True, False)

    def test_timestamp_ties_use_id_as_tiebreaker(self):
        Message.objects.filter(contact=self.contact).update(created_at=self.start)
        self._assert_window(100, 75, 125, True, True)

    def test_timestamp_order_takes_precedence_over_id(self):
        for index, message in enumerate(self.messages):
            message.created_at = self.start - timedelta(minutes=index)
        Message.objects.bulk_update(self.messages, ['created_at'])
        data = self._around(100)
        self.assertEqual(
            [row['id'] for row in data['messages']],
            [message.pk for message in self.messages[76:126][::-1]],
        )
        self.assertIs(data['has_older'], True)
        self.assertIs(data['has_newer'], True)

    def test_hidden_target_is_marked_without_exposing_hidden_neighbors(self):
        discarded = [self.messages[index].pk for index in (99, 100, 101)]
        Message.objects.filter(pk__in=discarded).update(status=Message.STATUS_DISCARDED)
        data = self._around(100)
        self.assertEqual(
            [row['id'] for row in data['messages']],
            [message.pk for message in self.messages[74:99]]
            + [self.messages[100].pk]
            + [message.pk for message in self.messages[102:126]],
        )
        hidden = [row for row in data['messages'] if row['is_hidden']]
        self.assertEqual(len(hidden), 1)
        self.assertEqual(hidden[0]['id'], self.messages[100].pk)
        self.assertEqual(hidden[0]['status'], Message.STATUS_DISCARDED)
        self.assertEqual(hidden[0]['body'], 'Histórico 100')
        regular = self.client.get(self.url, {'before': self.messages[125].pk}).data
        self.assertTrue(set(discarded).isdisjoint(row['id'] for row in regular['messages']))

    def test_outbound_evidence_preserves_status_identity_and_acceptance(self):
        target = self.messages[100]
        for status in (Message.STATUS_DISCARDED, Message.STATUS_FAILED,
                       Message.STATUS_PENDING, Message.STATUS_UNCERTAIN):
            with self.subTest(status=status):
                Message.objects.filter(pk=target.pk).update(
                    direction=Message.DIRECTION_OUT, author_type=Message.AUTHOR_HUMAN,
                    human_author=self.user, status=status,
                    idempotency_key='hist03-client-key',
                    uncertain_at=timezone.now() if status == Message.STATUS_UNCERTAIN else None,
                )
                row = next(row for row in self._around()['messages'] if row['id'] == target.pk)
                self.assertEqual(row['status'], status)
                self.assertIs(row['is_hidden'], False)
                self.assertIs(row['acceptance_known'], False)
                self.assertEqual(row['human_author_public_id'], str(self.user.public_id))
                self.assertEqual(row['client_message_id'], 'hist03-client-key')
                self.assertNotIn('send_token', row)

    def test_regular_payload_and_current_metadata_remain_compatible(self):
        recent = self.client.get(self.url).data
        centered = self._around(10)
        for key in recent.keys() - {'messages', 'next_before', 'first_unread_message_id', 'latest_visible_inbound_id',
                                    'mode', 'sync_cursor', 'sync_floor'}:
            self.assertEqual(centered[key], recent[key], key)
        self.assertEqual(set(centered), (set(recent) - {'mode', 'sync_cursor'}) | {'has_older', 'has_newer'})
        self.assertEqual(recent['mode'], 'full')
        self.assertTrue(recent['sync_cursor'])
        self.assertTrue(centered['sync_floor'])
        self.assertNotIn('is_hidden', recent['messages'][0])
        self.assertEqual(len(recent['messages']), 50)
        self.assertEqual(recent['next_before'], self.messages[150].pk)

    def test_archived_thread_has_no_current_conversation(self):
        Conversation.objects.filter(pk=self.current.pk).update(
            state=Conversation.STATE_CLOSED, closed_at=timezone.now(),
        )
        data = self._around(10)
        self.assertIsNone(data['conversation'])
        self.assertIsNone(data['identity_case'])
        self.assertIsNone(data['handoff'])
        self.assertIn(self.messages[10].pk, [row['id'] for row in data['messages']])

    def test_only_message_in_thread_has_no_continuation(self):
        solo_contact = ContactIdentity.objects.create(
            organization=self.org, external_id='single-message-thread',
        )
        target = self._msg(self._session(contact=solo_contact), 'Único mensaje')
        url = reverse('inbox-thread-messages', args=[
            str(solo_contact.public_id), str(self.channel.public_id),
        ])
        response = self.client.get(url, {'around': target.pk})
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual([row['id'] for row in data['messages']], [target.pk])
        self.assertIs(data['has_older'], False)
        self.assertIs(data['has_newer'], False)
        self.assertIsNone(data['next_before'])

    def test_before_and_around_are_exclusive_even_with_empty_values(self):
        for params in ({'around': self.messages[100].pk, 'before': self.messages[50].pk},
                       {'around': '', 'before': ''},
                       {'around': self.messages[100].pk, 'before': ''}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_cursor')

    def test_malformed_around_is_400(self):
        for value in ('', 'abc', '1.5', '0', '-1', '9223372036854775808', '9' * 5000):
            with self.subTest(value=value[:30]):
                response = self.client.get(self.url, {'around': value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_cursor')

    def test_missing_target_is_404(self):
        response = self.client.get(self.url, {'around': 9223372036854775807})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {'code': 'not_found'})

    def test_other_contact_or_account_is_404(self):
        other_contact = ContactIdentity.objects.create(
            organization=self.org, external_id='other-contact',
        )
        other_account = ChannelAccount.objects.create(
            organization=self.org, external_account_id='other-account',
        )
        for session in (self._session(contact=other_contact),
                        self._session(channel=other_account)):
            with self.subTest(session=session.pk):
                target = self._msg(session, 'No divulgar este mensaje')
                response = self.client.get(self.url, {'around': target.pk})
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data, {'code': 'not_found'})

    def test_other_organization_target_is_404_even_for_hidden_target(self):
        foreign_org = Organization.objects.create(name='Otra clínica', timezone='UTC')
        foreign_contact = ContactIdentity.objects.create(
            organization=foreign_org, external_id=self.contact.external_id,
        )
        foreign_account = ChannelAccount.objects.create(
            organization=foreign_org, external_account_id='foreign-account',
        )
        target = Message.objects.create(
            organization=foreign_org, contact=foreign_contact,
            channel_account=foreign_account, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, status=Message.STATUS_DISCARDED,
            body='PII de otra clínica',
        )
        response = self.client.get(self.url, {'around': target.pk})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {'code': 'not_found'})
        intruder = User.objects.create_user(
            username='intruder', organization=foreign_org, role='ADMIN',
        )
        self.client.force_authenticate(intruder)
        response = self.client.get(self.url, {'around': self.messages[100].pk})
        self.assertEqual(response.status_code, 404)

    def test_authentication_is_required(self):
        self.client.force_authenticate(None)
        response = self.client.get(self.url, {'around': self.messages[100].pk})
        self.assertIn(response.status_code, (401, 403))

    def test_view_permission_without_send_is_enough(self):
        viewer = User.objects.create_user(
            username='clinical-viewer', organization=self.org, role='VET',
        )
        self.client.force_authenticate(viewer)
        self._assert_window(100, 75, 125, True, True)

    def test_user_without_inbox_permission_is_denied(self):
        agent = User.objects.create_user(
            username='service-agent', organization=self.org, role='AGENT',
        )
        self.client.force_authenticate(agent)
        response = self.client.get(self.url, {'around': self.messages[100].pk})
        self.assertEqual(response.status_code, 403)

    def test_window_queries_and_materialization_are_bounded(self):
        with patch.object(Message, 'from_db', wraps=Message.from_db) as loaded:
            with CaptureQueriesContext(connection) as captured:
                data = self._around()
        self.assertEqual(len(data['messages']), 50)
        loaded_ids = [call.args[2][call.args[1].index('id')]
                      for call in loaded.call_args_list]
        self.assertCountEqual(loaded_ids, [message.pk for message in self.messages[74:126]])
        self.assertEqual(len(loaded_ids), 52)
        self.assertEqual(data['conversation']['last_message_preview'], self.messages[-1].body[:120])
        self.assertIs(data['conversation']['has_unanswered'], True)
        sql = [query['sql'] for query in captured if 'FROM "channels_message"' in query['sql']]
        self.assertTrue(any(query.endswith('LIMIT 26') for query in sql))
        self.assertTrue(any(query.endswith('LIMIT 25') for query in sql))
        # UNR-02 añade un único conteo de lectura; las ventanas siguen acotadas.
        self.assertEqual(sum('COUNT(' in query for query in sql), 1)
