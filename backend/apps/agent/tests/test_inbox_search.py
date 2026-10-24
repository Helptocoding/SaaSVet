"""WA-SRCH-01: contact-only search with scoped SQL, filters and cursors."""
import json
import os
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class InboxSearchTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Búsqueda sintética')
        cls.foreign = Organization.objects.create(name='Clínica ajena de búsqueda')
        cls.user = User.objects.create(username='search-staff', role='ASSISTANT', organization=cls.org)
        cls.other = User.objects.create(username='search-other', role='ADMIN', organization=cls.foreign)
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='search-main')
        cls.owner = Owner.objects.create(organization=cls.org, name='Marta Luna', phone='5559001122')
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='wa:525512345678',
            phone_normalized='5512345678', display_name='Ana Ramírez', owner=cls.owner)
        cls.peer = ContactIdentity.objects.create(organization=cls.org, external_id='wa:525598765432',
            phone_normalized='5598765432', display_name='Ana Beltrán')
        cls.archived = ContactIdentity.objects.create(organization=cls.org, external_id='archive-search', display_name='Ana Archivo')
        cls.empty = ContactIdentity.objects.create(organization=cls.org, external_id='opaque-external-id', display_name='Sin mensaje')
        cls.heads = []
        for contact, state, direction in [(cls.contact, 'human_active', 'in'), (cls.peer, 'active', 'out'),
                                          (cls.archived, 'closed', 'in'), (cls.empty, 'active', None)]:
            head = Conversation.objects.create(organization=cls.org, contact=contact, channel_account=cls.account,
                state=state, claimed_by=cls.user if contact == cls.contact else None)
            cls.heads.append(head)
            if direction:
                Message.objects.create(organization=cls.org, contact=contact, channel_account=cls.account,
                    conversation=head, direction=direction, author_type='client' if direction == 'in' else 'agent',
                    status='processed' if direction == 'in' else 'sent', body='SOLO_EN_CUERPO')
        HumanHandoff.objects.create(organization=cls.org, conversation=cls.heads[0], priority='urgent', reason_code='emergency')
        foreign_account = ChannelAccount.objects.create(organization=cls.foreign, external_account_id='foreign-search')
        foreign_owner = Owner.objects.create(organization=cls.foreign, name='Marta Luna', phone='5559001122')
        cls.foreign_contact = ContactIdentity.objects.create(organization=cls.foreign, external_id='wa:525512345678',
            phone_normalized='5512345678', display_name='Ana Ramírez', owner=foreign_owner)
        Conversation.objects.create(organization=cls.foreign, contact=cls.foreign_contact, channel_account=foreign_account)
        cls.url = '/api/inbox/threads/'

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.user)

    def page(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def ids(self, **params):
        return {row['contact_public_id'] for row in self.page(**params)['results']}

    def test_contact_display_name_matches_partial_case_insensitive(self):
        self.assertEqual(self.ids(q='aNA'), {str(self.contact.public_id), str(self.peer.public_id)})
        self.assertEqual(self.ids(q='ramÍREZ'), {str(self.contact.public_id)})

    def test_phone_fragment_and_formatted_digits_match(self):
        for query in ('123456', '+52 (55) 1234-5678', '+5215512345678', '55 1234'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(q=query), {str(self.contact.public_id)})

    def test_external_id_is_searchable_even_without_normalized_phone(self):
        self.assertEqual(self.ids(q='OPAQUE-external'), {str(self.empty.public_id)})
        ContactIdentity.objects.filter(pk=self.contact.pk).update(phone_normalized='')
        self.assertEqual(self.ids(q='+52 (55) 1234-5678'), {str(self.contact.public_id)})

    def test_linked_owner_name_matches_but_owner_phone_is_not_a_lookup(self):
        self.assertEqual(self.ids(q='mARTA lu'), {str(self.contact.public_id)})
        self.assertEqual(self.ids(q='9001122'), set())

    def test_no_results_returns_empty_200_and_global_unread_total(self):
        data = self.page(q='inexistente-sintético')
        self.assertEqual(data['results'], [])
        self.assertFalse(data['has_more'])
        self.assertIsNone(data['next_offset'])
        self.assertEqual(data['unread_total'], self.page()['unread_total'])

    def test_empty_and_short_queries_are_ignored_and_share_cursor_scope(self):
        full = self.page()
        for query in ('', ' ', 'a', ' a '):
            with self.subTest(query=query):
                self.assertEqual(self.ids(q=query), {str(self.contact.public_id), str(self.peer.public_id), str(self.empty.public_id)})
                delta = self.page(q=query, since=full['sync_cursor'])
                self.assertEqual(delta['mode'], 'delta')
                self.assertEqual(delta['upserts'], [])

    def test_text_queries_do_not_add_an_empty_phone_match(self):
        self.assertEqual(self.ids(q='texto-sin-dígitos'), set())
        self.assertEqual(self.ids(q='cliente 5'), set())

    def test_search_is_not_message_content_search(self):
        self.assertEqual(self.ids(q='SOLO_EN_CUERPO'), set())

    def test_search_combines_with_segments_and_archived(self):
        self.assertEqual(self.ids(q='Ana', unanswered=1, urgent=1, claimed='me'), {str(self.contact.public_id)})
        self.assertEqual(self.ids(q='Ana', unanswered=0), {str(self.peer.public_id)})
        self.assertEqual(self.ids(q='Ana', archived=1), {str(contact.public_id) for contact in (self.contact, self.peer, self.archived)})

    def test_same_names_owner_and_phone_in_another_tenant_do_not_leak(self):
        for query in ('Ramírez', 'Marta Luna', '12345678'):
            with self.subTest(query=query):
                self.assertEqual(self.ids(q=query), {str(self.contact.public_id)})
        self.client.force_authenticate(self.other)
        self.assertEqual(self.ids(q='Ramírez'), {str(self.foreign_contact.public_id)})

    def test_sql_and_like_metacharacters_are_literal_values(self):
        for query in ("'; DROP TABLE agent_conversation; --", '_%', '\\%', "' OR TRUE --"):
            with self.subTest(query=query):
                self.assertEqual(self.ids(q=query), set())
        self.assertTrue(Conversation.objects.filter(pk=self.heads[0].pk).exists())
        ContactIdentity.objects.filter(pk=self.empty.pk).update(display_name='Cliente 100%')
        self.assertEqual(self.ids(q='100%'), {str(self.empty.public_id)})

    def test_search_applies_before_offset_and_groups_accounts(self):
        with patch('apps.agent.views.THREADS_PAGE_SIZE', 1):
            first = self.page(q='Ana')
            second = self.page(q='Ana', offset=1)
            self.assertTrue(first['has_more'])
            self.assertEqual(first['next_offset'], 1)
            self.assertFalse(second['has_more'])
            self.assertEqual({r['contact_public_id'] for data in (first, second) for r in data['results']},
                             {str(self.contact.public_id), str(self.peer.public_id)})
        account = ChannelAccount.objects.create(organization=self.org, external_account_id='search-second')
        Conversation.objects.create(organization=self.org, contact=self.contact, channel_account=account)
        self.assertEqual(len(self.page(q='Ramírez')['results']), 2)

    def test_cursor_scope_includes_trimmed_query_and_all_other_filters(self):
        full = self.page(q=' Ana ')
        self.assertEqual(self.page(q='Ana', since=full['sync_cursor'])['mode'], 'delta')
        for params in ({'q': 'Marta'}, {}, {'q': 'Ana', 'urgent': 1}, {'q': 'Ana', 'offset': 100}):
            with self.subTest(params=params):
                response = self.client.get(self.url, dict(params, since=full['sync_cursor']))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_sync_cursor')

    def test_delta_reconciles_contact_rename_out_of_search(self):
        full = self.page(q='Ramírez')
        ContactIdentity.objects.filter(pk=self.contact.pk).update(display_name='Nombre cambiado')
        delta = self.page(q='Ramírez', since=full['sync_cursor'])
        self.assertEqual(delta['removals'], [f'{self.contact.public_id}:{self.account.public_id}'])
        self.assertEqual(delta['upserts'], [])

    def test_search_does_not_bypass_authentication_or_view_permission(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url, {'q': 'Ana'}).status_code, 401)
        agent = User.objects.create(username='search-agent', organization=self.org, role='AGENT', is_service_account=True)
        self.client.force_authenticate(agent)
        self.assertEqual(self.client.get(self.url, {'q': 'Ana'}).status_code, 403)

    def test_query_plan_keeps_search_in_one_bounded_list_select(self):
        # Meaningful clinic volume; bodies/history are not loaded to search.
        contacts = ContactIdentity.objects.bulk_create([ContactIdentity(organization=self.org,
            external_id=f'plan-search-{i}', display_name=f'Contacto sintético {i}') for i in range(1000)])
        Conversation.objects.bulk_create([Conversation(organization=self.org, contact=contact,
            channel_account=self.account) for contact in contacts])
        with CaptureQueriesContext(connection) as captured:
            data = self.page(q='Ramírez')
        self.assertEqual(len(data['results']), 1)
        selects = [entry['sql'] for entry in captured if '_inbox_preview' in entry['sql']]
        self.assertEqual(len(selects), 1)
        sql = selects[0]
        self.assertIn('LIMIT 101', sql)
        self.assertIn('UPPER(', sql)
        self.assertNotIn('SOLO_EN_CUERPO', sql)
        with connection.cursor() as cursor:
            cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql)
            plan = cursor.fetchone()[0][0]
        self.assertEqual(plan['Plan']['Actual Rows'], 1)
        output = os.environ.get('INBOX_SEARCH_PLAN_OUTPUT')
        if output:
            with Path(output).open('x', encoding='utf-8') as artifact:
                json.dump(dict(threads=1004, returned=1, list_selects=len(selects),
                    total_queries=len(captured), plan=plan), artifact, indent=2)
