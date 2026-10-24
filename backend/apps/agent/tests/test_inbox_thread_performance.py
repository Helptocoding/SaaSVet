"""WA-PERF-01: frozen payload parity and bounded reads for grouped threads."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User

NOW = datetime(2026, 10, 21, 12, tzinfo=dt_timezone.utc)
FIXTURE = Path(__file__).with_name('fixtures') / 'inbox_threads_perf01.json'
MEASUREMENTS = []


class ThreadPerformanceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Inbox performance', timezone='UTC')
        cls.user = User.objects.create_user(username='recepcion_perf', organization=cls.org, role='ADMIN')
        cls.channel = ChannelAccount.objects.create(organization=cls.org,
            external_account_id='perf-main', public_id=UUID(int=101))
        cls.other_channel = ChannelAccount.objects.create(organization=cls.org,
            external_account_id='perf-other', public_id=UUID(int=102))
        cls.owner = Owner.objects.create(organization=cls.org, name='Cliente sintético', phone='5512345678')
        cls.contacts = []
        for index in range(7):
            cls.contacts.append(ContactIdentity.objects.create(organization=cls.org,
                public_id=UUID(int=201 + index), external_id=f'perf-{index}',
                display_name=f'Contacto {index}', phone_normalized=f'550000000{index}',
                owner=cls.owner if index == 0 else None,
                verification_level='staff_verified' if index == 0 else 'unknown'))

        # Closed episode newer than the active one: head and bucket order differ.
        cls.active = cls.session(0, 301, activity=1, claimed_by=cls.user,
                                 processing_until=NOW + timedelta(minutes=5))
        closed = cls.session(0, 302, activity=9, state='closed')
        cls.session(0, 303, activity=-2, state='closed')
        cls.message(closed, 'Último mensaje entre episodios', minute=30)
        cls.message(cls.active, 'Anterior', minute=10)
        # Discarded inbound must not hide the last operational message.
        cls.message(cls.active, 'Entrante descartado', minute=50, status='discarded')

        archived = cls.session(1, 304, activity=8, state='closed')
        cls.session(1, 305, activity=0, state='closed')
        cls.message(archived, 'á🙂' * 80, minute=25, direction='out', status='uncertain')
        HumanHandoff.objects.create(organization=cls.org, conversation=archived,
            priority='normal', reason_code='explicit_request', reason_detail='Histórico abierto')

        empty = cls.session(2, 306, activity=7, state='handoff_pending')
        for priority, reason, detail, resolved in [
            ('urgent', 'emergency', 'Anterior', None),
            ('normal', 'explicit_request', 'Más reciente normal', None),
            ('urgent', 'safety_urgent', 'Urgente elegido', None),
            ('urgent', 'tool_failure', 'Resuelto excluido', NOW),
        ]:
            HumanHandoff.objects.create(organization=cls.org, conversation=empty,
                priority=priority, reason_code=reason, reason_detail=detail, resolved_at=resolved)

        second_account = cls.session(0, 307, activity=6, channel=cls.other_channel)
        cls.message(second_account, '', minute=20, direction='out', status='failed')
        # Equal latest message times retain ordering by bucket activity.
        for index, activity in [(3, 5), (4, 4)]:
            session = cls.session(index, 308 + index, activity=activity)
            cls.message(session, f'Empate {index}', minute=20)
        # Same timestamp within one thread: higher message ID wins.
        tied = cls.session(5, 313, activity=3)
        cls.message(tied, 'Primero con misma hora', minute=15)
        cls.message(tied, 'Segundo con misma hora', minute=15, direction='out', status='pending')
        cls.session(6, 314, activity=2)  # no messages, no handoff

        foreign = Organization.objects.create(name='Otra clínica', timezone='UTC')
        other_contact = ContactIdentity.objects.create(organization=foreign, external_id='perf-0')
        other_account = ChannelAccount.objects.create(organization=foreign, external_account_id='foreign')
        Conversation.objects.create(organization=foreign, contact=other_contact, channel_account=other_account)

    @classmethod
    def session(cls, contact_index, public_int, *, activity=0, channel=None, state='active', **kwargs):
        return Conversation.objects.create(organization=cls.org,
            contact=cls.contacts[contact_index], channel_account=channel or cls.channel,
            public_id=UUID(int=public_int), state=state,
            closed_at=NOW if state == 'closed' else None,
            last_activity_at=NOW + timedelta(minutes=activity), **kwargs)

    @classmethod
    def message(cls, session, body, *, minute, direction='in', status='processed'):
        message = Message.objects.create(organization=cls.org, conversation=session,
            contact=session.contact, channel_account=session.channel_account,
            direction=direction, author_type=Message.AUTHOR_CLIENT if direction == 'in' else Message.AUTHOR_AGENT,
            status=status, body=body, uncertain_at=NOW if status == 'uncertain' else None)
        Message.objects.filter(pk=message.pk).update(created_at=NOW + timedelta(minutes=minute))

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.clock = patch('apps.agent.serializers.timezone.now', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def payloads(self):
        result = {}
        for name, params in [('active', {}), ('archived', {'archived': '1'})]:
            response = self.client.get(reverse('inbox-threads'), params)
            self.assertEqual(response.status_code, 200)
            result[name] = json.loads(response.content)['results']
        return result

    def query_sample(self):
        self.client.get(reverse('inbox-threads'))  # permission/cache warmup
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse('inbox-threads'))
        self.assertEqual(response.status_code, 200)
        return {'rows': len(response.data['results']), 'queries': len(captured)}

    def add_thirty_threads(self):
        for index in range(30):
            contact = ContactIdentity.objects.create(organization=self.org, external_id=f'bulk-{index}')
            for state in ('closed', 'active'):
                session = Conversation.objects.create(organization=self.org, contact=contact,
                    channel_account=self.channel, state=state, last_activity_at=NOW)
            self.message(session, f'Mensaje de carga {index}', minute=index)
            HumanHandoff.objects.create(organization=self.org, conversation=session,
                reason_code='explicit_request')

    def test_characterization_payload_matches_frozen_baseline(self):
        payloads = self.payloads()
        # Additive DTO fields are verified here; frozen pre-media evidence stays intact.
        for rows in payloads.values():
            for row in rows:
                self.assertIsInstance(row.pop('unread_count'), int)
                kind = row.pop('last_message_type')
                self.assertIn(kind, (None, 'text', 'image', 'audio', 'video', 'document', 'sticker', 'location', 'other'))
                self.assertIsNone(row.pop('last_message_filename'))
        self.assertEqual(payloads, json.loads(FIXTURE.read_text(encoding='utf-8')))

    def test_first_page_is_applied_after_urgent_ordering(self):
        contacts = ContactIdentity.objects.bulk_create([
            ContactIdentity(organization=self.org, external_id=f'cap-{i}') for i in range(110)
        ])
        sessions = Conversation.objects.bulk_create([
            Conversation(organization=self.org, contact=contact, channel_account=self.channel,
                         last_activity_at=NOW - timedelta(days=1)) for contact in contacts
        ])
        urgent = sessions[-1]
        HumanHandoff.objects.create(organization=self.org, conversation=urgent,
            priority='urgent', reason_code='emergency')
        response = self.client.get(reverse('inbox-threads'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 100)
        self.assertIn(str(urgent.public_id), [row['conversation_public_id'] for row in response.data['results'][:2]])

    def test_query_count_is_constant_with_thirty_more_threads(self):
        small = self.query_sample()
        self.add_thirty_threads()
        large = self.query_sample()
        MEASUREMENTS.append({'small': small, 'large': large})
        self.assertEqual(large['rows'], small['rows'] + 30)
        self.assertEqual(large['queries'], small['queries'])
        self.assertLessEqual(large['queries'], 4)

    def test_closed_history_is_counted_without_materializing_each_episode(self):
        Conversation.objects.bulk_create([
            Conversation(organization=self.org, contact=self.contacts[0],
                channel_account=self.channel, state='closed', last_activity_at=NOW - timedelta(days=1))
            for _ in range(100)
        ])
        with patch.object(Conversation, 'from_db', wraps=Conversation.from_db) as loader:
            response = self.client.get(reverse('inbox-threads'), {'archived': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(loader.call_count, len(response.data['results']))
        target = next(row for row in response.data['results'] if row['conversation_public_id'] == str(self.active.public_id))
        self.assertEqual(target['session_count'], 103)
