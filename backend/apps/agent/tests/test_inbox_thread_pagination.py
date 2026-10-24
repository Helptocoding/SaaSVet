"""WA-PERF-02: complete, tenant-scoped traversal with deterministic ties."""
from datetime import datetime, timezone
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.users.models import User


class ThreadPaginationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Paginación sintética', timezone='UTC')
        cls.user = User.objects.create_user(username='pagination', organization=cls.org, role='ADMIN')
        cls.channel = ChannelAccount.objects.create(organization=cls.org, external_account_id='pagination')
        cls.contacts = ContactIdentity.objects.bulk_create([
            ContactIdentity(organization=cls.org, external_id=f'page-{i}', display_name=f'Cliente {i}')
            for i in range(250)
        ])
        now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        cls.sessions = Conversation.objects.bulk_create([
            Conversation(organization=cls.org, contact=contact, channel_account=cls.channel,
                         last_activity_at=now) for contact in cls.contacts
        ])
        Message.objects.bulk_create([
            Message(organization=cls.org, contact=session.contact, channel_account=cls.channel,
                    conversation=session, direction='in', author_type='client', status='processed',
                    body='Mensaje de prueba') for session in cls.sessions
        ])
        Message.objects.filter(organization=cls.org).update(created_at=now)
        HumanHandoff.objects.bulk_create([
            HumanHandoff(organization=cls.org, conversation=session, priority='urgent', reason_code='emergency')
            for session in cls.sessions[-5:]
        ])
        cls.expected = [str(c.public_id) for c in cls.contacts[-5:] + cls.contacts[:-5]]
        cls.foreign = Organization.objects.create(name='Otra clínica de prueba', timezone='UTC')
        foreign_account = ChannelAccount.objects.create(organization=cls.foreign, external_account_id='foreign-page')
        foreign_contact = ContactIdentity.objects.create(organization=cls.foreign, external_id='foreign-page')
        Conversation.objects.create(organization=cls.foreign, contact=foreign_contact, channel_account=foreign_account)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def page(self, **params):
        response = self.client.get(reverse('inbox-threads'), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'results', 'has_more', 'next_offset', 'unread_total', 'mode', 'sync_cursor'})
        self.assertEqual(response.data['mode'], 'full')
        self.assertIsInstance(response.data['sync_cursor'], str)
        return response.data

    def test_250_threads_are_reachable_in_stable_urgent_first_pages(self):
        pages = [self.page(), self.page(offset=100), self.page(offset=200)]
        self.assertEqual([len(p['results']) for p in pages], [100, 100, 50])
        self.assertEqual([p['has_more'] for p in pages], [True, True, False])
        self.assertEqual([p['next_offset'] for p in pages], [100, 200, None])
        ids = [r['contact_public_id'] for p in pages for r in p['results']]
        self.assertEqual(ids, self.expected)
        self.assertEqual(len(set(ids)), 250)
        repeated = self.page(offset=100)
        self.assertEqual({key: value for key, value in repeated.items() if key != 'sync_cursor'},
                         {key: value for key, value in pages[1].items() if key != 'sync_cursor'})
        self.assertTrue(all(r['handoff_priority'] == 'urgent' for r in pages[0]['results'][:5]))

    def test_archived_flag_is_kept_on_later_pages(self):
        contact = ContactIdentity.objects.create(organization=self.org, external_id='archived-page')
        Conversation.objects.create(organization=self.org, contact=contact, channel_account=self.channel,
                                    state='closed')
        self.assertEqual(len(self.page(offset=200)['results']), 50)
        last = self.page(archived='1', offset=200)
        self.assertEqual(len(last['results']), 51)
        archived = next(r for r in last['results'] if r['contact_public_id'] == str(contact.public_id))
        self.assertIsNone(archived['conversation_public_id'])
        self.assertIsNone(archived['state'])
        self.assertFalse(last['has_more'])

    def test_offset_past_the_end_returns_an_empty_final_page(self):
        empty = self.page(offset=250)
        self.assertEqual({key: value for key, value in empty.items() if key not in ('mode', 'sync_cursor')},
                         {'results': [], 'has_more': False, 'next_offset': None, 'unread_total': 250})
        self.assertEqual(self.page(offset=2147483647)['results'], [])

    def test_invalid_offsets_return_400(self):
        for offset in ('-1', 'abc', '1.5', '', '2147483648', '9' * 5000):
            with self.subTest(offset=offset[:30]):
                response = self.client.get(reverse('inbox-threads'), {'offset': offset})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_offset')

    def test_exact_page_boundary_has_no_phantom_next_page(self):
        # 250 is exactly two pages at this size; sentinel logic must report exhaustion.
        with patch('apps.agent.views.THREADS_PAGE_SIZE', 125):
            self.assertEqual(self.page()['next_offset'], 125)
            final = self.page(offset=125)
        self.assertEqual(len(final['results']), 125)
        self.assertFalse(final['has_more'])
        self.assertIsNone(final['next_offset'])

    def test_same_contact_on_another_account_is_a_distinct_thread(self):
        channel = ChannelAccount.objects.create(organization=self.org, external_account_id='second-page')
        Conversation.objects.create(organization=self.org, contact=self.contacts[0], channel_account=channel)
        pages = [self.page(offset=offset) for offset in (0, 100, 200)]
        rows = [r for page in pages for r in page['results']]
        self.assertEqual(len(rows), 251)
        self.assertEqual(len({(r['contact_public_id'], r['channel_account_public_id']) for r in rows}), 251)

    def test_offset_does_not_bypass_authentication_or_tenant_scope(self):
        other = User.objects.create_user(username='other-pagination', organization=self.foreign, role='ADMIN')
        self.client.force_authenticate(other)
        self.assertEqual(len(self.page()['results']), 1)
        self.assertEqual(self.page(offset=100)['results'], [])
        self.client.force_authenticate(None)
        response = self.client.get(reverse('inbox-threads'), {'offset': 100, 'archived': '1'})
        self.assertEqual(response.status_code, 401)
