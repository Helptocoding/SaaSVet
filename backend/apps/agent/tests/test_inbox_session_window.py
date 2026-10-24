"""WA-WIN-01: current-episode projection and real inbound renewal, without writes on GET."""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation
from apps.agent.serializers import ConversationListSerializer
from apps.agent.services import ingest_inbound_message
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.users.models import User


class InboxSessionWindowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Ventana sintética', timezone='America/Tijuana')
        cls.viewer = User.objects.create(username='window-viewer', organization=cls.org, role='VET')
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='window-main')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='5215551234567',
                                                    phone_normalized='5551234567')
        cls.conv = Conversation.objects.create(organization=cls.org, channel_account=cls.account,
            contact=cls.contact, last_inbound_at=timezone.now())
        cls.message = Message.objects.create(organization=cls.org, channel_account=cls.account,
            contact=cls.contact, conversation=cls.conv, direction='in', author_type='client',
            status='processed', body='Consulta sintética')
        cls.url = reverse('inbox-thread-messages', args=[cls.contact.public_id, cls.account.public_id])

    def setUp(self):
        self.client.force_authenticate(self.viewer)
        self.now = timezone.now()

    def fetch(self, **params):
        with patch('apps.agent.serializers.timezone.now', return_value=self.now):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def window(self, age):
        stamp = None if age is None else self.now - age
        Conversation.objects.filter(pk=self.conv.pk).update(last_inbound_at=stamp)
        return self.fetch()['conversation']

    def test_open_recent_and_expiring_expose_readonly_boolean_and_utc_expiry(self):
        for age in (timedelta(hours=1), timedelta(hours=16, minutes=48)):
            with self.subTest(age=age):
                data = self.window(age)
                self.assertIs(data['session_window_open'], True)
                self.assertEqual(parse_datetime(data['session_window_expires_at']),
                                 self.now - age + timedelta(hours=24))
        fields = ConversationListSerializer().fields
        self.assertTrue(fields['session_window_open'].read_only)
        self.assertTrue(fields['session_window_expires_at'].read_only)

    def test_closed_and_missing_last_inbound_cannot_claim_an_open_window(self):
        data = self.window(timedelta(hours=25))
        self.assertIs(data['session_window_open'], False)
        self.assertEqual(parse_datetime(data['session_window_expires_at']), self.now-timedelta(hours=1))
        data = self.window(None)
        self.assertIs(data['session_window_open'], False)
        self.assertIsNone(data['session_window_expires_at'])

    def test_exact_24h_matches_b4_then_closes_immediately_after(self):
        self.assertIs(self.window(timedelta(hours=24))['session_window_open'], True)
        self.assertIs(self.window(timedelta(hours=24, microseconds=1))['session_window_open'], False)

    def test_window_is_elapsed_24h_across_org_dst_fallback(self):
        # Tijuana falls back on 2026-11-01: elapsed UTC must stay exactly 24 h.
        self.now = datetime(2026, 11, 1, 17, tzinfo=dt_timezone.utc)
        stamp = datetime(2026, 10, 31, 18, tzinfo=dt_timezone.utc)
        Conversation.objects.filter(pk=self.conv.pk).update(last_inbound_at=stamp)
        data = self.fetch()['conversation']
        self.assertTrue(data['session_window_open'])
        self.assertEqual(parse_datetime(data['session_window_expires_at']),
                         datetime(2026, 11, 1, 18, tzinfo=dt_timezone.utc))

    def test_archived_thread_has_no_current_window_and_legacy_session_is_closed(self):
        Conversation.objects.filter(pk=self.conv.pk).update(state='closed', closed_at=self.now)
        self.assertIsNone(self.fetch()['conversation'])
        legacy = self.client.get(reverse('inbox-messages', args=[self.conv.public_id]))
        self.assertEqual(legacy.status_code, 200)
        self.assertIs(legacy.data['conversation']['session_window_open'], False)
        self.assertIsNone(legacy.data['conversation']['session_window_expires_at'])

    def test_historical_page_uses_current_episode_window(self):
        old = Conversation.objects.create(organization=self.org, contact=self.contact,
            channel_account=self.account, state='closed', closed_at=self.now-timedelta(days=3),
            last_inbound_at=self.now-timedelta(days=4), last_activity_at=self.now-timedelta(days=3))
        target = Message.objects.create(organization=self.org, conversation=old, contact=self.contact,
            channel_account=self.account, direction='in', author_type='client', status='processed')
        data = self.fetch(around=target.pk)
        self.assertEqual(data['conversation']['public_id'], str(self.conv.public_id))
        self.assertTrue(data['conversation']['session_window_open'])

    def test_real_new_inbound_renews_expired_window_without_rewriting_history(self):
        self.window(timedelta(hours=25))
        original = Message.objects.values().get(pk=self.message.pk)
        received = ingest_inbound_message(self.account, wamid='wamid.WINDOW01',
            wa_id=self.contact.external_id, body='Nuevo mensaje sintético')
        self.assertIsNotNone(received)
        self.assertEqual(received.conversation_id, self.conv.pk)
        self.conv.refresh_from_db()
        data = self.fetch()['conversation']
        self.assertTrue(data['session_window_open'])
        self.assertEqual(parse_datetime(data['session_window_expires_at']),
                         self.conv.last_inbound_at + timedelta(hours=24))
        self.assertEqual(Message.objects.values().get(pk=self.message.pk), original)

    def test_real_inbound_after_archive_creates_current_episode_with_new_window(self):
        Conversation.objects.filter(pk=self.conv.pk).update(state='closed', closed_at=self.now)
        received = ingest_inbound_message(self.account, wamid='wamid.WINDOW02',
            wa_id=self.contact.external_id, body='Nueva consulta sintética')
        self.assertIsNotNone(received)
        self.assertNotEqual(received.conversation_id, self.conv.pk)
        data = self.fetch()['conversation']
        self.assertEqual(data['public_id'], str(received.conversation.public_id))
        self.assertTrue(data['session_window_open'])

    def test_get_does_not_modify_episode_message_or_read_state_and_foreign_org_is_404(self):
        from apps.agent.models import InboxReadState
        before = Conversation.objects.values().get(pk=self.conv.pk)
        self.fetch()
        self.assertEqual(before, Conversation.objects.values().get(pk=self.conv.pk))
        self.assertFalse(InboxReadState.objects.exists())
        foreign = Organization.objects.create(name='Otra clínica', timezone='UTC')
        intruder = User.objects.create(username='window-foreign', organization=foreign, role='ADMIN')
        self.client.force_authenticate(intruder)
        self.assertEqual(self.client.get(self.url).status_code, 404)
