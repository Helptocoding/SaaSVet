"""WA-FIL-01: grouped, server-side segments and scoped incremental refresh."""
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.users.models import User


class InboxFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Filtros sintéticos')
        cls.foreign = Organization.objects.create(name='Otra clínica de filtros')
        cls.user = User.objects.create(username='filter-staff', role='ASSISTANT', organization=cls.org)
        cls.peer = User.objects.create(username='filter-peer', role='VET', organization=cls.org)
        cls.other = User.objects.create(username='filter-other', role='ADMIN', organization=cls.foreign)
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='filter-main')
        cls.heads = {}
        for name, direction, claimant, urgent, closed in [
            ('in-mine', 'in', cls.user, True, False),
            ('in-peer', 'in', cls.peer, False, False),
            ('out-mine', 'out', cls.user, True, False),
            ('out-peer', 'out', cls.peer, False, False),
            ('empty', None, None, False, False),
            ('archived', 'in', cls.user, True, True),
        ]:
            contact = ContactIdentity.objects.create(organization=cls.org, external_id=name, display_name=name)
            head = Conversation.objects.create(organization=cls.org, contact=contact,
                channel_account=cls.account, claimed_by=claimant, state='closed' if closed else 'human_active')
            cls.heads[name] = head
            if direction:
                Message.objects.create(organization=cls.org, contact=contact, channel_account=cls.account,
                    conversation=head, direction=direction, author_type='client' if direction == 'in' else 'agent',
                    status='processed' if direction == 'in' else 'sent', body='Mensaje sintético')
            if urgent:
                HumanHandoff.objects.create(organization=cls.org, conversation=head, priority='urgent',
                    reason_code='emergency')
        # Historical urgent/claimed episodes must not qualify the current head.
        HumanHandoff.objects.create(organization=cls.org, conversation=Conversation.objects.create(
            organization=cls.org, contact=cls.heads['out-peer'].contact, channel_account=cls.account,
            state='closed', claimed_by=cls.user), priority='urgent', reason_code='emergency')
        foreign_account = ChannelAccount.objects.create(organization=cls.foreign, external_account_id='foreign-filter')
        foreign_contact = ContactIdentity.objects.create(organization=cls.foreign, external_id='foreign-filter')
        foreign_head = Conversation.objects.create(organization=cls.foreign, contact=foreign_contact,
            channel_account=foreign_account, claimed_by=cls.other)
        Message.objects.create(organization=cls.foreign, contact=foreign_contact, channel_account=foreign_account,
            conversation=foreign_head, direction='in', author_type='client', status='processed', body='Foreign')
        HumanHandoff.objects.create(organization=cls.foreign, conversation=foreign_head, priority='urgent', reason_code='emergency')
        cls.url = '/api/inbox/threads/'

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.user)

    def page(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def names(self, **params):
        return {row['contact_display_name'] for row in self.page(**params)['results']}

    def test_unanswered_only_matches_inbound_and_keeps_global_unread_total(self):
        self.assertEqual(self.names(unanswered=1), {'in-mine', 'in-peer'})
        self.assertEqual(self.page(unanswered=1)['unread_total'], self.page()['unread_total'])

    def test_waiting_client_matches_outbound_and_excludes_empty_threads(self):
        self.assertEqual(self.names(unanswered=0), {'out-mine', 'out-peer'})

    def test_urgent_uses_unresolved_handoff_on_current_head(self):
        self.assertEqual(self.names(urgent=1), {'in-mine', 'out-mine'})

    def test_mine_and_public_user_id_use_current_claim(self):
        self.assertEqual(self.names(claimed='me'), {'in-mine', 'out-mine'})
        self.assertEqual(self.names(claimed=str(self.peer.public_id)), {'in-peer', 'out-peer'})

    def test_segments_combine_with_and(self):
        self.assertEqual(self.names(unanswered=1, urgent=1, claimed='me'), {'in-mine'})
        self.assertEqual(self.names(unanswered=0, urgent=1, claimed='me'), {'out-mine'})
        self.assertEqual(self.names(unanswered=1, claimed=str(self.peer.public_id)), {'in-peer'})

    def test_archived_includes_closed_but_stale_claim_and_handoff_are_not_actionable(self):
        self.assertEqual(self.names(archived=1, unanswered=1), {'in-mine', 'in-peer', 'archived'})
        self.assertEqual(self.names(archived=1, urgent=1, claimed='me'), {'in-mine', 'out-mine'})

    def test_combination_with_no_match_returns_empty_200(self):
        data = self.page(urgent=1, claimed=str(self.peer.public_id))
        self.assertEqual(data['results'], [])
        self.assertFalse(data['has_more'])
        self.assertIsNone(data['next_offset'])

    def test_foreign_user_id_and_foreign_org_are_not_visible(self):
        self.assertEqual(self.names(claimed=str(self.other.public_id)), set())
        self.client.force_authenticate(self.other)
        rows = self.page(unanswered=1, urgent=1, claimed='me')['results']
        self.assertEqual(len(rows), 1)
        self.assertNotIn(rows[0]['contact_public_id'], {str(head.contact.public_id) for head in self.heads.values()})

    def test_invalid_filter_values_return_canonical_400(self):
        for params in ({'unanswered': ''}, {'unanswered': '2'}, {'urgent': 'yes'},
                       {'claimed': '1'}, {'claimed': "' OR 1=1"}, {'claimed': 'z'*1000}):
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_filter')

    def test_effective_equivalent_filters_share_cursor_scope(self):
        data = self.page(unanswered='true', urgent='true', claimed='me')
        delta = self.page(unanswered=1, urgent=1, claimed=str(self.user.public_id), since=data['sync_cursor'])
        self.assertEqual(delta['mode'], 'delta')
        self.assertEqual(delta['upserts'], [])
        self.assertEqual(delta['removals'], [])

    def test_cursor_cannot_be_replayed_in_another_segment(self):
        cursor = self.page(unanswered=1, urgent=1, claimed='me')['sync_cursor']
        for params in ({'unanswered': 0, 'urgent': 1, 'claimed': 'me'},
                       {'unanswered': 1, 'claimed': 'me'}, {'unanswered': 1, 'urgent': 1},
                       {'unanswered': 1, 'urgent': 1, 'claimed': 'me', 'archived': 1},
                       {'unanswered': 1, 'urgent': 1, 'claimed': 'me', 'offset': 100}):
            with self.subTest(params=params):
                response = self.client.get(self.url, dict(params, since=cursor))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['code'], 'invalid_sync_cursor')

    def test_delta_removes_answered_thread_from_unanswered_segment(self):
        full = self.page(unanswered=1)
        head = self.heads['in-mine']
        Message.objects.create(organization=self.org, contact=head.contact, channel_account=self.account,
            conversation=head, direction='out', author_type='agent', status='sent', body='Respuesta')
        delta = self.page(unanswered=1, since=full['sync_cursor'])
        self.assertEqual(delta['removals'], [f'{head.contact.public_id}:{self.account.public_id}'])
        self.assertEqual(self.names(unanswered=1), {'in-peer'})

    def test_filters_apply_before_pagination_without_per_row_queries(self):
        with patch('apps.agent.views.THREADS_PAGE_SIZE', 1):
            with CaptureQueriesContext(connection) as queries:
                first = self.page(unanswered=1)
            second = self.page(unanswered=1, offset=1)
            self.assertTrue(first['has_more'])
            self.assertEqual(first['next_offset'], 1)
            self.assertFalse(second['has_more'])
            self.assertEqual({r['contact_display_name'] for page in (first, second) for r in page['results']},
                             {'in-mine', 'in-peer'})
        with CaptureQueriesContext(connection) as larger_queries:
            self.page(unanswered=1)
        self.assertEqual(len(queries), len(larger_queries))

    def test_filters_do_not_bypass_authentication_or_view_permission(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url, {'urgent': 1}).status_code, 401)
        agent = User.objects.create(username='filter-agent', organization=self.org, role='AGENT', is_service_account=True)
        self.client.force_authenticate(agent)
        self.assertEqual(self.client.get(self.url, {'unanswered': 1, 'claimed': 'me'}).status_code, 403)
