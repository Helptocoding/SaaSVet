"""PERF-03: scope, replay, equal watermarks, projection changes and recovery."""
from datetime import timedelta
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.renderers import JSONRenderer

from apps.agent.inbox_sync import CURSOR_TTL, SALT, _cache_key
from apps.agent.models import ContactIdentity, Conversation, HumanHandoff, InboxReadState
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class InboxSyncTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Sync sintético')
        cls.foreign = Organization.objects.create(name='Foreign sync')
        cls.user = User.objects.create(username='sync-staff', role='ASSISTANT', organization=cls.org)
        cls.peer = User.objects.create(username='sync-vet', role='VET', organization=cls.org)
        cls.other = User.objects.create(username='sync-other', role='ADMIN', organization=cls.foreign)
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='sync-main')
        cls.owner = Owner.objects.create(organization=cls.org, name='Ana', phone='5551234567')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='sync-ana', owner=cls.owner)
        cls.conversation = Conversation.objects.create(organization=cls.org, contact=cls.contact,
            channel_account=cls.account, state='human_active', last_inbound_at=timezone.now())
        cls.message = Message.objects.create(organization=cls.org, contact=cls.contact,
            channel_account=cls.account, conversation=cls.conversation, direction='in',
            author_type='client', status='processed', body='PRIVATE_SYNC_BODY')
        cls.list_url = '/api/inbox/threads/'
        cls.url = f'/api/inbox/threads/{cls.contact.public_id}/{cls.account.public_id}/messages/'

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.user)

    def full(self, url=None, **params):
        response = self.client.get(url or self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def delta(self, previous, url=None, **params):
        return self.full(url, since=previous['sync_cursor'], **params)

    def new_message(self, **values):
        return Message.objects.create(organization=self.org, contact=self.contact,
            channel_account=self.account, conversation=self.conversation, direction='in',
            author_type='client', status='processed', body='Nuevo', **values)

    def test_stable_transcript_transfers_no_bodies_metadata_or_new_cursor(self):
        full = self.full()
        delta = self.delta(full)
        self.assertEqual(delta, dict(mode='delta', sync_cursor=full['sync_cursor'],
            messages=[], removals=[], metadata={}))
        self.assertNotIn('PRIVATE_SYNC_BODY', str(delta))

    def test_new_and_modified_messages_are_merged_with_equal_updated_at(self):
        full = self.full()
        timestamp = self.message.updated_at
        Message.objects.filter(pk=self.message.pk).update(body='Modificado', updated_at=timestamp)
        new = self.new_message()
        Message.objects.filter(pk=new.pk).update(updated_at=timestamp)
        # Same timestamp for both rows is legitimate; IDs must not collide.
        delta = self.delta(full)
        self.assertEqual([row['id'] for row in delta['messages']], [self.message.pk, new.pk])
        self.assertEqual(delta['messages'][0]['body'], 'Modificado')
        recovery = self.full(floor=self.message.pk)
        self.assertEqual(recovery['messages'][0]['body'], 'Modificado')
        self.assertTrue(recovery['reset_range'])

    def test_existing_status_failure_and_body_writes_advance_updated_at(self):
        full = self.full()
        Message.objects.filter(pk=self.message.pk).update(body='Nuevo cuerpo', status='failed')
        delta = self.delta(full)
        self.assertEqual([(row['id'], row['body'], row['status']) for row in delta['messages']],
                         [(self.message.pk, 'Nuevo cuerpo', 'failed')])

    def test_replay_does_not_consume_changes_and_late_commits_with_old_time_are_found(self):
        full = self.full()
        new = self.new_message()
        Message.objects.filter(pk=new.pk).update(updated_at=self.message.updated_at-timedelta(days=1))
        first = self.delta(full)
        second = self.delta(full)
        self.assertEqual([row['id'] for row in first['messages']], [new.pk])
        self.assertEqual(first['messages'], second['messages'])

    def test_removed_first_message_does_not_break_cursor_floor(self):
        full = self.full()
        Message.objects.filter(pk=self.message.pk).update(status='discarded')
        delta = self.delta(full, floor=self.message.pk)
        self.assertEqual(delta['removals'], [self.message.pk])
        self.assertEqual(delta['messages'], [])
        self.assertEqual(self.delta(delta, floor=self.message.pk)['removals'], [])

    def test_burst_larger_than_latest_page_has_no_gap(self):
        full = self.full()
        for _ in range(65):
            self.new_message()
        delta = self.delta(full)
        self.assertEqual(len(delta['messages']), 65)
        self.assertEqual(len({row['id'] for row in delta['messages']}), 65)
        self.assertEqual(self.delta(delta)['messages'], [])

    def test_scroll_back_expands_range_and_preserves_old_message_updates(self):
        for _ in range(55):
            self.new_message()
        full = self.full()
        self.assertNotIn(self.message.pk, [row['id'] for row in full['messages']])
        Message.objects.filter(pk=self.message.pk).update(body='Histórico modificado')
        delta = self.delta(full, floor=self.message.pk)
        self.assertEqual(delta['messages'][0]['body'], 'Histórico modificado')
        self.assertEqual(len(delta['messages']), 6)
        self.assertEqual(self.delta(delta, floor=self.message.pk)['messages'], [])

    def test_claim_close_and_renewal_are_metadata_changes_even_without_messages(self):
        full = self.full()
        Conversation.objects.filter(pk=self.conversation.pk).update(claimed_by=self.peer)
        delta = self.delta(full)
        self.assertEqual(delta['messages'], [])
        self.assertEqual(delta['metadata']['conversation']['claimed_by_name'], self.peer.username)
        Conversation.objects.filter(pk=self.conversation.pk).update(state='closed')
        closed = self.delta(delta)
        self.assertIsNone(closed['metadata']['conversation'])
        Conversation.objects.filter(pk=self.conversation.pk).update(state='active', last_inbound_at=timezone.now())
        opened = self.delta(closed)
        self.assertTrue(opened['metadata']['conversation']['session_window_open'])

    def test_lease_expiry_is_detected_without_a_write(self):
        now = timezone.now()
        Conversation.objects.filter(pk=self.conversation.pk).update(processing_until=now+timedelta(seconds=3))
        with patch('django.utils.timezone.now', return_value=now):
            full = self.full()
        with patch('django.utils.timezone.now', return_value=now+timedelta(seconds=4)):
            delta = self.delta(full)
        self.assertFalse(delta['metadata']['conversation']['agent_processing'])

    def test_read_state_is_per_user_and_metadata_only(self):
        full = self.full()
        self.client.post(self.url.replace('/messages/', '/read/'), {'last_read_message_id': self.message.pk})
        delta = self.delta(full)
        self.assertEqual(delta['metadata']['unread_count'], 0)
        self.assertEqual(delta['messages'], [])
        self.client.force_authenticate(self.peer)
        self.assertEqual(self.full()['unread_count'], 1)

    def test_list_delta_returns_upserts_removals_and_preserves_filter(self):
        full = self.full(self.list_url)
        self.assertEqual(self.delta(full, self.list_url)['upserts'], [])
        Conversation.objects.filter(pk=self.conversation.pk).update(claimed_by=self.peer)
        changed = self.delta(full, self.list_url)
        self.assertEqual(changed['upserts'][0]['claimed_by_name'], self.peer.username)
        Conversation.objects.filter(pk=self.conversation.pk).update(state='closed')
        removed = self.delta(changed, self.list_url)
        self.assertEqual(removed['upserts'], [])
        self.assertEqual(removed['removals'], [f'{self.contact.public_id}:{self.account.public_id}'])
        archived = self.full(self.list_url, archived=1)
        self.assertIsNone(archived['results'][0]['conversation_public_id'])
        Conversation.objects.filter(pk=self.conversation.pk).update(state='active')
        self.assertTrue(self.delta(removed, self.list_url)['upserts'])

    def test_owner_and_handoff_changes_are_detected_without_touching_conversation(self):
        full = self.full(self.list_url)
        Owner.objects.filter(pk=self.owner.pk).update(name='Ana vigente')
        HumanHandoff.objects.create(organization=self.org, conversation=self.conversation, reason_code='explicit_request')
        delta = self.delta(full, self.list_url)
        self.assertEqual(delta['upserts'][0]['owner_name'], 'Ana vigente')
        self.assertEqual(delta['upserts'][0]['handoff_reason'], 'explicit_request')

    def test_invalid_expired_cross_user_org_resource_page_and_filters_are_400(self):
        full = self.full(self.list_url)
        token = full['sync_cursor']
        for params in ({'since': ''}, {'since': 'garbage'}, {'since': token, 'archived': 1},
                       {'since': token, 'offset': 100}):
            self.assertEqual(self.client.get(self.list_url, params).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'since': token}).status_code, 400)
        for user in (self.peer, self.other):
            self.client.force_authenticate(user)
            response = self.client.get(self.list_url, {'since': token})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(str(response.data['code']), 'invalid_sync_cursor')
        self.client.force_authenticate(self.user)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+CURSOR_TTL+1):
            self.assertEqual(self.client.get(self.list_url, {'since': token}).status_code, 400)

    def test_cache_loss_requests_recovery_and_stores_no_pii(self):
        full = self.full()
        state = cache.get(_cache_key(full['sync_cursor']))
        self.assertNotIn('PRIVATE_SYNC_BODY', str(state))
        self.assertNotIn('Ana', str(state))
        self.assertEqual(signing.loads(full['sync_cursor'], salt=SALT)['w'], state['watermarks'])
        cache.clear()
        self.assertEqual(self.client.get(self.url, {'since': full['sync_cursor']}).status_code, 400)
        self.assertEqual(self.full()['mode'], 'full')

    def test_cache_outage_full_response_remains_available(self):
        with patch('apps.agent.inbox_sync.cache.set', return_value=None):
            full = self.full()
        self.assertIsNone(full['sync_cursor'])
        self.assertEqual(len(full['messages']), 1)

    def test_since_cannot_be_combined_with_history_cursors_or_foreign_floor(self):
        full = self.full()
        for params in ({'before': 100}, {'around': self.message.pk}, {'floor': -1}, {'floor': 9999999}):
            self.assertEqual(self.client.get(self.url, dict(since=full['sync_cursor'], **params)).status_code, 400)
        self.assertNotIn('sync_cursor', self.full(before=self.message.pk))
        self.assertNotIn('sync_cursor', self.full(around=self.message.pk))

    def test_delta_is_read_only_and_unauthorized_service_cannot_use_it(self):
        full = self.full()
        before = Conversation.objects.values().get(pk=self.conversation.pk)
        self.delta(full)
        self.assertEqual(before, Conversation.objects.values().get(pk=self.conversation.pk))
        self.assertFalse(InboxReadState.objects.exists())
        agent = User.objects.create(username='sync-agent', organization=self.org, role='AGENT', is_service_account=True)
        self.client.force_authenticate(agent)
        self.assertEqual(self.client.get(self.url, {'since': full['sync_cursor']}).status_code, 403)

    def test_central_tracking_covers_save_atomic_all_objects_and_bulk_update(self):
        models = [self.message, self.conversation, self.contact,
            HumanHandoff.objects.create(organization=self.org, conversation=self.conversation, reason_code='explicit_request'),
            InboxReadState.objects.create(organization=self.org, user=self.user, contact=self.contact, channel_account=self.account)]
        for obj in models:
            old = obj.updated_at
            with patch('apps.core.models.timezone.now', return_value=old+timedelta(seconds=1)):
                obj.save(update_fields=['is_active'])
            obj.refresh_from_db()
            self.assertGreater(obj.updated_at, old)
            with patch('apps.core.models.timezone.now', return_value=old+timedelta(seconds=2)):
                type(obj).all_objects.filter(pk=obj.pk).update(is_active=True)
            obj.refresh_from_db()
            self.assertEqual(obj.updated_at, old+timedelta(seconds=2))
            with patch('apps.core.models.timezone.now', return_value=old+timedelta(seconds=3)):
                type(obj).objects.bulk_update([obj], ['is_active'])
            obj.refresh_from_db()
            self.assertEqual(obj.updated_at, old+timedelta(seconds=3))

    def test_stable_delta_does_not_select_message_bodies(self):
        full = self.full()
        with CaptureQueriesContext(connection) as queries:
            self.delta(full)
        body_selects = [row['sql'] for row in queries if re.search(
            r'(?:SELECT |,\s*)"channels_message"\."body"(?=,| FROM)', row['sql'])]
        self.assertEqual(body_selects, [])

    def test_signed_floor_survives_physical_removal_and_cache_recovery(self):
        full = self.full()
        self.assertTrue(full['sync_floor'])
        Message.all_objects.filter(pk=self.message.pk).delete()
        new = self.new_message()
        delta = self.delta(full, floor=full['sync_floor'])
        self.assertEqual(delta['removals'], [self.message.pk])
        self.assertEqual([row['id'] for row in delta['messages']], [new.pk])
        cache.clear()
        recovered = self.full(floor=full['sync_floor'])
        self.assertTrue(recovered['reset_range'])
        self.assertEqual([row['id'] for row in recovered['messages']], [new.pk])

    def test_history_floor_is_signed_for_the_user_and_thread(self):
        full = self.full()
        floor = full['sync_floor']
        self.client.force_authenticate(self.peer)
        own = self.full()
        response = self.client.get(self.url, {'since': own['sync_cursor'], 'floor': floor})
        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.url, {'since': full['sync_cursor'], 'floor': floor+'x'}).status_code, 400)

    def test_history_extension_reconciles_rows_removed_while_before_was_in_flight(self):
        for _ in range(55):
            self.new_message()
        full = self.full()
        older = self.full(before=full['next_before'])
        Message.objects.filter(pk=self.message.pk).update(status='discarded')
        delta = self.delta(full, floor=older['sync_floor'])
        self.assertNotIn(self.message.pk, delta['range_ids'])
        self.assertEqual(len(delta['messages']), 5)
        self.assertEqual(delta['removals'], [])

    def test_two_status_transitions_on_same_id_and_timestamp_are_not_lost(self):
        full = self.full()
        for status in ('failed', 'processed'):
            Message.objects.filter(pk=self.message.pk).update(status=status, updated_at=self.message.updated_at)
            full = self.delta(full)
            self.assertEqual(full['messages'][0]['status'], status)

    def test_query_plan_and_payload_size_for_large_thread(self):
        # Synthetic homogeneous rows with valid fixture FKs; no business action.
        Message.objects.bulk_create([Message(organization=self.org, contact=self.contact,
            channel_account=self.account, conversation=self.conversation, direction='in',
            author_type='client', status='processed', body='x'*512) for _ in range(6000)])
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE channels_message')
        full = self.full()
        self.assertEqual(len(full['messages']), 50)
        with CaptureQueriesContext(connection) as queries:
            delta = self.delta(full)
        stamp_query = next(row['sql'] for row in queries if ' AS "_inbox_sync_stamp"' in row['sql'])
        with connection.cursor() as cursor:
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+stamp_query)
            plan = cursor.fetchone()[0]
        full_size = len(JSONRenderer().render(full))
        delta_size = len(JSONRenderer().render(delta))
        self.assertLess(delta_size, full_size // 10)
        self.assertEqual(delta['messages'], [])
        result = dict(synthetic=True, total_messages=6001, loaded_messages=50,
            full_payload_bytes=full_size, stable_delta_bytes=delta_size,
            domain_queries=len(queries), explain=plan)
        # Ordinary CI runs must not rewrite a historical evaluation artifact.
        if destination := os.environ.get('INBOX_SYNC_PLAN_OUTPUT'):
            out = Path(destination)
            with out.open('x', encoding='utf-8') as receipt:
                json.dump(result, receipt, indent=2)

    def test_bounded_preview_preserves_text_caption_and_empty_media_labels(self):
        for kind, body in [('text', 'z'*300), ('image', ''), ('image', 'Caption')]:
            Message.objects.filter(pk=self.message.pk).update(payload_type=kind, body=body)
            self.message.refresh_from_db()
            expected = body[:120] if body else f'[{self.message.get_payload_type_display()}]'
            self.assertEqual(self.full()['conversation']['last_message_preview'], expected)

    def test_metadata_preview_never_reads_corrupt_foreign_message(self):
        Message.objects.filter(pk=self.message.pk).update(organization=self.foreign)
        data = self.full()
        self.assertEqual(data['messages'], [])
        self.assertEqual(data['conversation']['last_message_preview'], '')
        self.assertNotIn('PRIVATE_SYNC_BODY', str(data))
