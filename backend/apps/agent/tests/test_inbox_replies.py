"""WA-RPL-03: scoped send, bounded quote projection and incremental updates."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from unittest.mock import patch

from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.agent import views
from apps.agent.models import ContactIdentity, Conversation
from apps.agent.serializers import MessageSerializer
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.organizations.models import Organization
from apps.users.models import User


class ReplyApiFixtures:
    @classmethod
    def user(cls, name, codes):
        user = User.objects.create(username=name, organization=cls.org, role='ASSISTANT')
        user.user_roles.all().delete()
        role = Role.objects.create(organization=cls.org, name=name)
        role.permissions.set([Permission.objects.get_or_create(code=code)[0] for code in codes])
        UserRole.objects.create(user=user, role=role)
        return user

    @classmethod
    def build(cls):
        cls.org = Organization.objects.create(name='Citas API sintéticas')
        cls.actor = cls.user('reply-api-actor', ('agentinbox.view', 'agentinbox.send'))
        cls.peer = cls.user('reply-api-peer', ('agentinbox.view', 'agentinbox.send'))
        cls.peer.first_name = 'María'
        cls.peer.last_name = 'Sintética'
        cls.peer.save()
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='reply-api')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='reply-api-person')
        cls.convo = Conversation.objects.create(organization=cls.org, channel_account=cls.account,
            contact=cls.contact, last_inbound_at=timezone.now())
        cls.target = cls.message()
        cls.url = f'/api/inbox/conversations/{cls.convo.public_id}/send/'
        cls.transcript = f'/api/inbox/threads/{cls.contact.public_id}/{cls.account.public_id}/messages/'

    @classmethod
    def message(cls, **overrides):
        fields = dict(organization=cls.org, channel_account=cls.account, contact=cls.contact,
            conversation=cls.convo, direction='in', author_type='client', status='processed',
            body='Destino sintético')
        fields.update(overrides)
        return Message.objects.create(**fields)

    def send(self, target=None, key=None, **overrides):
        data = {'body': 'Respuesta propia sintética', 'reply_to_id': (target or self.target).pk}
        data.update(overrides)
        headers = {'HTTP_X_IDEMPOTENCY_KEY': key} if key else {}
        return self.client.post(self.url, data, format='json', **headers)

    def read(self, **params):
        response = self.client.get(self.transcript, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class InboxReplyApiTests(ReplyApiFixtures, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.actor)

    def test_post_get_roundtrip_and_exact_bounded_projection(self):
        self.target.body = 'é🐾'*50
        self.target.save()
        response = self.send()
        self.assertEqual(response.status_code, 201, response.data)
        quote = {'id': self.target.pk, 'author_type': 'client', 'human_author_name': None,
            'payload_type': 'text', 'excerpt': self.target.body[:80], 'status': 'processed'}
        self.assertEqual(response.data['reply_to'], quote)
        self.assertEqual(len(quote['excerpt']), 80)
        row = next(row for row in self.read()['messages'] if row['id'] == response.data['id'])
        self.assertEqual(row['reply_to'], quote)
        self.assertEqual(Message.objects.get(pk=response.data['id']).reply_to_id, self.target.pk)

    def test_missing_optional_field_keeps_legacy_send_and_null_projection(self):
        response = self.client.post(self.url, {'body': 'Sin cita'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['reply_to'])

    def test_human_author_and_username_fallback_are_projected(self):
        target = self.message(direction='out', author_type='human_staff', human_author=self.peer, status='sent')
        self.assertEqual(self.send(target).data['reply_to']['human_author_name'], 'María Sintética')
        User.objects.filter(pk=self.peer.pk).update(first_name='', last_name='')
        self.assertEqual(self.send(target).data['reply_to']['human_author_name'], self.peer.username)

    def test_empty_media_and_discarded_or_failed_targets_keep_status(self):
        for status in ('discarded', 'failed'):
            with self.subTest(status=status):
                target = self.message(direction='out', author_type='system', status=status, body='', payload_type='image')
                response = self.send(target)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data['reply_to']['excerpt'], '')
                self.assertEqual(response.data['reply_to']['payload_type'], 'image')
                self.assertEqual(response.data['reply_to']['status'], status)

    def test_takeover_response_reads_current_discarded_target_status(self):
        target = self.message(direction='out', author_type='agent', status='pending')
        response = self.send(target)
        self.assertEqual(response.status_code, 201)
        target.refresh_from_db()
        self.assertEqual(target.status, 'discarded')
        self.assertEqual(response.data['reply_to']['status'], 'discarded')

    def test_historical_episode_and_hidden_target_are_valid(self):
        old = Conversation.objects.create(organization=self.org, contact=self.contact,
            channel_account=self.account, state='closed')
        target = self.message(conversation=old, is_active=False)
        response = self.send(target)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['reply_to']['id'], target.pk)

    def test_other_person_account_organization_and_missing_target_are_rejected_without_takeover(self):
        other_contact = ContactIdentity.objects.create(organization=self.org, external_id='another-reply-person')
        other_account = ChannelAccount.objects.create(organization=self.org, external_account_id='another-reply-account')
        foreign_org = Organization.objects.create(name='Foreign reply API')
        foreign_account = ChannelAccount.objects.create(organization=foreign_org, external_account_id='foreign-reply-api')
        foreign_contact = ContactIdentity.objects.create(organization=foreign_org, external_id='foreign-reply-api')
        targets = [self.message(contact=other_contact, conversation=None),
            self.message(channel_account=other_account, conversation=None),
            self.message(organization=foreign_org, channel_account=foreign_account, contact=foreign_contact, conversation=None)]
        pending = self.message(direction='out', author_type='agent', status='pending')
        before = (self.convo.state, self.convo.claimed_by_id, self.convo.ownership_epoch)
        for target_id in [target.pk for target in targets]+[999999999]:
            with self.subTest(target_id=target_id):
                response = self.send(reply_to_id=target_id, key=f'invalid-{target_id}')
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_reply_target')
        self.convo.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((self.convo.state, self.convo.claimed_by_id, self.convo.ownership_epoch), before)
        self.assertEqual(pending.status, 'pending')
        self.assertFalse(Message.objects.filter(author_type='human_staff').exists())

    def test_invalid_input_values_are_400(self):
        for value in (None, 0, -1, 'bad', {}, True, 9223372036854775808):
            with self.subTest(value=value):
                self.assertEqual(self.send(reply_to_id=value).status_code, 400)

    def test_replay_keeps_original_quote_even_with_invalid_changed_request(self):
        first = self.send(key='quoted-idempotency')
        second = self.send(key='quoted-idempotency', reply_to_id=999999999, body='Cambio ignorado')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Message.objects.filter(idempotency_key='quoted-idempotency').count(), 1)

    def test_replay_after_close_preserves_quote(self):
        first = self.send(key='quoted-after-close')
        Conversation.objects.filter(pk=self.convo.pk).update(state='closed', closed_at=timezone.now())
        replay = self.send(key='quoted-after-close', reply_to_id=999999999)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.data['reply_to'], first.data['reply_to'])

    def test_closed_session_rejects_new_quoted_send(self):
        Conversation.objects.filter(pk=self.convo.pk).update(state='closed', closed_at=timezone.now())
        self.assertEqual(self.send().status_code, 400)

    def test_view_only_and_anonymous_cannot_send_but_viewer_can_read_quote(self):
        self.assertEqual(self.send().status_code, 201)
        viewer = self.user('reply-api-viewer', ('agentinbox.view',))
        self.client.force_authenticate(viewer)
        self.assertEqual(self.send().status_code, 403)
        self.assertTrue(any(row['reply_to'] for row in self.read()['messages']))
        self.client.force_authenticate(None)
        self.assertEqual(self.send().status_code, 401)

    def test_foreign_conversation_is_404_before_replay(self):
        self.send(key='quoted-private-key')
        foreign = Organization.objects.create(name='Foreign conversation quote')
        account = ChannelAccount.objects.create(organization=foreign, external_account_id='foreign-quote-convo')
        contact = ContactIdentity.objects.create(organization=foreign, external_id='foreign-quote-convo')
        convo = Conversation.objects.create(organization=foreign, channel_account=account, contact=contact)
        self.url = f'/api/inbox/conversations/{convo.public_id}/send/'
        self.assertEqual(self.send(key='quoted-private-key').status_code, 404)

    def test_projection_is_one_level_even_when_target_is_a_reply(self):
        target = self.message(reply_to=self.target)
        response = self.send(target)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('reply_to', response.data['reply_to'])

    def test_corrupt_legacy_quote_does_not_leak_foreign_or_other_person_content(self):
        other_contact = ContactIdentity.objects.create(organization=self.org, external_id='secret-other-person')
        target = self.message(contact=other_contact, conversation=None, body='PRIVATE_OTHER_PERSON_CONTENT')
        parent = self.message(body='Contenido propio')
        Message.objects.filter(pk=parent.pk).update(reply_to=target)
        packet = self.read()
        row = next(row for row in packet['messages'] if row['id'] == parent.pk)
        self.assertIsNone(row['reply_to'])
        self.assertNotIn('PRIVATE_OTHER_PERSON_CONTENT', json.dumps(packet, default=str))

    def test_foreign_human_author_name_is_not_disclosed_in_quote(self):
        foreign = Organization.objects.create(name='Foreign quoted author')
        user = User.objects.create(username='PRIVATE_FOREIGN_AUTHOR', organization=foreign)
        target = self.message(human_author=user)
        response = self.send(target)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['reply_to']['human_author_name'])

    def test_serializer_has_one_query_for_many_quotes_and_authors(self):
        target = self.message(direction='out', author_type='human_staff', human_author=self.peer, status='sent')
        for _ in range(20):
            self.message(reply_to=target)
        queryset = Message.objects.for_organization(self.org).select_related(
            'human_author', 'conversation', 'reply_to__human_author', 'media')
        with self.assertNumQueries(1):
            rows = MessageSerializer(queryset, many=True).data
        self.assertEqual(sum(row['reply_to'] is not None for row in rows), 20)

    def test_api_query_count_does_not_grow_with_quote_count(self):
        self.send()
        self.read()  # warm actor RBAC
        with CaptureQueriesContext(connection) as small:
            self.read()
        for _ in range(20):
            self.message(reply_to=self.target)
        with CaptureQueriesContext(connection) as large:
            self.read()
        self.assertEqual(len(large), len(small))

    def test_before_around_and_legacy_transcript_include_quote(self):
        old = self.message(reply_to=self.target)
        newest = self.message()
        previous = self.read(before=newest.pk)
        self.assertEqual(next(row for row in previous['messages'] if row['id'] == old.pk)['reply_to']['id'], self.target.pk)
        around = self.read(around=old.pk)
        self.assertEqual(next(row for row in around['messages'] if row['id'] == old.pk)['reply_to']['id'], self.target.pk)
        legacy = self.client.get(f'/api/inbox/conversations/{self.convo.public_id}/messages/')
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(next(row for row in legacy.data['messages'] if row['id'] == old.pk)['reply_to']['id'], self.target.pk)

    def test_stable_delta_with_quotes_is_empty(self):
        self.send()
        full = self.read()
        delta = self.read(since=full['sync_cursor'])
        self.assertEqual(delta['messages'], [])
        self.assertEqual(delta['metadata'], {})

    def test_quote_edit_outside_loaded_page_updates_parent_without_touching_it(self):
        for _ in range(55):
            self.message()
        response = self.send()
        parent = Message.objects.get(pk=response.data['id'])
        full = self.read()
        self.assertNotIn(self.target.pk, [row['id'] for row in full['messages']])
        Message.objects.filter(pk=self.target.pk).update(body='Extracto cambiado')
        delta = self.read(since=full['sync_cursor'])
        row = next(row for row in delta['messages'] if row['id'] == parent.pk)
        self.assertEqual(row['reply_to']['excerpt'], 'Extracto cambiado')
        self.assertNotIn(self.target.pk, [row['id'] for row in delta['messages']])
        original = parent.updated_at
        parent.refresh_from_db()
        self.assertEqual(parent.updated_at, original)

    def test_tail_beyond_excerpt_does_not_change_parent_projection(self):
        self.target.body = 'a'*80+'primera cola'
        self.target.save()
        for _ in range(55):
            self.message()
        self.send()
        full = self.read()
        Message.objects.filter(pk=self.target.pk).update(body='a'*80+'otra cola')
        delta = self.read(since=full['sync_cursor'])
        self.assertEqual(delta['messages'], [])

    def test_quote_status_and_author_rename_are_detected_without_parent_write(self):
        target = self.message(direction='out', author_type='human_staff', human_author=self.peer, status='sent')
        response = self.send(target)
        full = self.read()
        Message.objects.filter(pk=target.pk).update(status='delivered')
        User.objects.filter(pk=self.peer.pk).update(first_name='Nombre actualizado')
        delta = self.read(since=full['sync_cursor'])
        quote = next(row for row in delta['messages'] if row['id'] == response.data['id'])['reply_to']
        self.assertEqual(quote['status'], 'delivered')
        self.assertEqual(quote['human_author_name'], 'Nombre actualizado Sintética')

    def test_retry_preserves_quote_body_author_and_key(self):
        response = self.send(key='quoted-retry')
        message_id = response.data['id']
        Message.objects.filter(pk=message_id).update(status='failed', failure_reason='credentials_missing')
        self.client.force_authenticate(self.peer)
        retry = self.client.post(f'/api/inbox/conversations/{self.convo.public_id}/messages/{message_id}/retry/',
            {'body': 'Ignorado', 'reply_to_id': 999999999}, format='json', HTTP_X_IDEMPOTENCY_KEY='quoted-retry')
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data['reply_to'], response.data['reply_to'])
        self.assertEqual(retry.data['body'], response.data['body'])
        self.assertEqual(retry.data['human_author_public_id'], str(self.actor.public_id))
        self.assertEqual(retry.data['client_message_id'], 'quoted-retry')


class InboxReplyRaceTests(ReplyApiFixtures, APITransactionTestCase):
    def setUp(self):
        cache.clear()
        self.build()

    def test_concurrent_same_key_with_different_quotes_returns_one_original(self):
        other = self.message(body='Segundo destino')
        barrier = threading.Barrier(2, timeout=10)
        real_replay = views._replay_outbound_message
        def precheck(*args, **kwargs):
            result = real_replay(*args, **kwargs)
            if result is None:
                barrier.wait()
            return result
        def request(target_id):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=self.actor.pk))
                response = client.post(self.url, {'body': 'Una intención', 'reply_to_id': target_id},
                    format='json', HTTP_X_IDEMPOTENCY_KEY='quoted-race')
                return response.status_code, response.data
            finally:
                connection.close()
        with patch.object(views, '_replay_outbound_message', side_effect=precheck):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(request, target.pk) for target in (self.target, other)]
                results = [future.result(timeout=20) for future in futures]
        self.assertEqual([row[0] for row in results], [201, 201])
        self.assertEqual(results[0][1], results[1][1])
        message = Message.objects.get(idempotency_key='quoted-race')
        self.assertIn(message.reply_to_id, (self.target.pk, other.pk))
