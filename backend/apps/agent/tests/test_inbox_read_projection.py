"""UNR-02 requires an all-page total and a boundary from the visible current episode."""
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.agent.models import InboxReadState
from .test_inbox_read_state import build_fixture


class InboxReadProjectionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        build_fixture(cls)

    def setUp(self):
        self.client.force_authenticate(self.a)

    def read(self, message):
        response = self.client.post(self.read_url, {'last_read_message_id': message.pk}, format='json')
        self.assertEqual(response.status_code, 200)
        return response.data

    def transcript(self, **params):
        return self.client.get(reverse('inbox-thread-messages', args=[
            str(self.contact.public_id), str(self.account.public_id),
        ]), params).data

    def test_opening_projection_excludes_closed_history_discarded_and_outbound(self):
        data = self.transcript()
        self.assertIsNone(data['last_read_message_id'])
        self.assertEqual(data['unread_count'], 3)
        self.assertEqual(data['first_unread_message_id'], self.incoming[0].pk)
        self.assertEqual(data['latest_visible_inbound_id'], self.incoming[-1].pk)
        self.assertNotEqual(data['first_unread_message_id'], self.old_message.pk)

    def test_projection_is_personal_and_removes_boundary_after_read(self):
        self.read(self.incoming[-1])
        data = self.transcript()
        self.assertEqual(data['last_read_message_id'], self.incoming[-1].pk)
        self.assertIsNone(data['first_unread_message_id'])
        self.assertEqual(data['unread_count'], 0)
        self.client.force_authenticate(self.b)
        self.assertIsNone(self.transcript()['last_read_message_id'])
        self.assertEqual(self.transcript()['unread_count'], 3)

    def test_historical_page_has_no_visible_current_inbound_to_mark(self):
        data = self.transcript(before=self.incoming[0].pk)
        self.assertEqual(data['unread_count'], 3)
        self.assertIsNone(data['first_unread_message_id'])
        self.assertIsNone(data['latest_visible_inbound_id'])
        self.assertFalse(InboxReadState.objects.for_organization(self.org).exists())

    def test_total_is_all_threads_even_with_one_row_page_or_empty_offset(self):
        from unittest.mock import patch
        with patch('apps.agent.views.THREADS_PAGE_SIZE', 1):
            first = self.client.get(reverse('inbox-threads')).data
            past_end = self.client.get(reverse('inbox-threads'), {'offset': 1000}).data
        self.assertEqual(len(first['results']), 1)
        self.assertEqual(first['unread_total'], 5)
        self.assertEqual(past_end['unread_total'], 5)
        self.read(self.incoming[-1])
        self.assertEqual(self.client.get(reverse('inbox-threads')).data['unread_total'], 2)
