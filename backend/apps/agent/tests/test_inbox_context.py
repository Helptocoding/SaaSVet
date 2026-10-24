"""WA-CTX-01: minimal projection, linked identity, tenant scope and bounded queries."""
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, InboxReadState
from apps.appointments.models import Appointment
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.users.models import User


class InboxContextTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Contexto sintético', timezone='America/Tijuana')
        cls.viewer = User.objects.create(username='context-vet', organization=cls.org, role='VET')
        cls.staff = User.objects.create(username='context-staff', organization=cls.org, role='ASSISTANT')
        cls.account = ChannelAccount.objects.create(organization=cls.org, external_account_id='context-main')
        cls.owner = Owner.objects.create(organization=cls.org, name='Ana Contexto', phone='5551234567',
            legacy_id='private-owner-reference', extra_data=[{'label': 'private', 'value': 'PRIVATE_OWNER_DATA'}])
        cls.other_owner = Owner.objects.create(organization=cls.org, name='Otro Cliente', phone='5557654321')
        cls.pet = Pet.objects.create(organization=cls.org, owner=cls.owner, name='Luna', species='felino',
            breed='PRIVATE_BREED', extra_data=[{'label': 'private', 'value': 'PRIVATE_PET_DATA'}])
        cls.contact = ContactIdentity.objects.create(organization=cls.org, external_id='5215551234567',
            phone_normalized='5551234567', owner=cls.owner)
        cls.conv = Conversation.objects.create(organization=cls.org, channel_account=cls.account, contact=cls.contact)
        cls.message = Message.objects.create(organization=cls.org, conversation=cls.conv, contact=cls.contact,
            channel_account=cls.account, direction='in', author_type='client', status='processed', body='PRIVATE_MESSAGE')
        cls.foreign_org = Organization.objects.create(name='Otra clínica', timezone='UTC')
        cls.foreign_owner = Owner.objects.create(organization=cls.foreign_org, name='PRIVATE_FOREIGN_OWNER', phone='5551234567')
        cls.foreign_account = ChannelAccount.objects.create(organization=cls.foreign_org, external_account_id='context-foreign')
        cls.url = reverse('inbox-thread-context', args=[cls.contact.public_id, cls.account.public_id])

    def setUp(self):
        self.client.force_authenticate(self.viewer)
        self.now = datetime(2026, 10, 21, 0, 30, tzinfo=dt_timezone.utc)  # Oct 20, 17:30 in clinic.

    def appointment(self, *, pet=None, hour=9, day=20, status='done', legacy=False, organization=None):
        start = datetime(2026, 10, day, hour, tzinfo=dt_timezone.utc) + timedelta(hours=7)
        return Appointment.objects.create(organization=organization or self.org, pet=pet or self.pet,
            date=start.astimezone(ZoneInfo('America/Tijuana')).date(),
            start_time=time(hour), end_time=time(hour, 30),
            start_datetime=None if legacy else start, end_datetime=None if legacy else start+timedelta(minutes=30),
            timezone_at_creation='America/Tijuana', status=status, reason='PRIVATE_REASON',
            notes='PRIVATE_NOTES', cancellation_reason='PRIVATE_CANCELLATION')

    def fetch(self, url=None):
        with patch('apps.agent.inbox_context.timezone.now', return_value=self.now):
            return self.client.get(url or self.url)

    def test_linked_owner_pets_and_last_appointment_have_only_public_minimum(self):
        Pet.objects.create(organization=self.org, owner=self.owner, name='Bruno', species='canino')
        self.appointment()
        response = self.fetch()
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(set(data), {'owner', 'pets', 'last_appointment'})
        self.assertEqual(data['owner'], {'public_id': str(self.owner.public_id), 'name': 'Ana Contexto', 'phone': '5551234567'})
        self.assertEqual([pet['name'] for pet in data['pets']], ['Bruno', 'Luna'])
        self.assertTrue(all(set(pet) == {'public_id', 'name', 'species'} for pet in data['pets']))
        self.assertEqual(data['last_appointment'], {'date': '2026-10-20', 'status': 'done'})
        self.assertNotIn('PRIVATE', str(data))
        self.assertNotIn('legacy_id', str(data))

    def test_same_phone_without_link_never_rematches_owner(self):
        ContactIdentity.objects.filter(pk=self.contact.pk).update(owner=None)
        response = self.fetch()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'owner': None, 'pets': [], 'last_appointment': None})
        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)

    def test_owner_without_pets_or_appointments_returns_empty_collections(self):
        ContactIdentity.objects.filter(pk=self.contact.pk).update(owner=self.other_owner)
        data = self.fetch().data
        self.assertEqual(data['owner']['public_id'], str(self.other_owner.public_id))
        self.assertEqual(data['pets'], [])
        self.assertIsNone(data['last_appointment'])

    def test_other_owners_pets_and_appointments_are_excluded(self):
        other = Pet.objects.create(organization=self.org, owner=self.other_owner, name='PRIVATE_OTHER_PET', species='canino')
        self.appointment(pet=other, hour=16)
        self.appointment(hour=8)
        data = self.fetch().data
        self.assertEqual([pet['public_id'] for pet in data['pets']], [str(self.pet.public_id)])
        self.assertEqual(data['last_appointment']['status'], 'done')
        self.assertNotIn('PRIVATE_OTHER_PET', str(data))

    def test_latest_past_appointment_is_selected_by_date_time_with_status_intact(self):
        self.appointment(hour=8, status='done')
        self.appointment(hour=16, status='canceled')
        self.appointment(hour=18, status='scheduled')  # today, but still in the future.
        self.appointment(day=22, status='confirmed')
        self.assertEqual(self.fetch().data['last_appointment'], {'date': '2026-10-20', 'status': 'canceled'})

    def test_future_only_is_not_presented_as_last_appointment(self):
        self.appointment(hour=18)
        self.appointment(day=22)
        self.assertIsNone(self.fetch().data['last_appointment'])

    def test_legacy_without_utc_uses_clinic_date_and_local_time(self):
        self.appointment(day=20, hour=16, legacy=True, status='no_show')
        self.appointment(day=20, hour=18, legacy=True)
        self.appointment(day=21, hour=8, legacy=True)
        self.assertEqual(self.fetch().data['last_appointment'], {'date': '2026-10-20', 'status': 'no_show'})

    def test_archive_keeps_linked_context_available_without_reopening(self):
        Conversation.objects.filter(pk=self.conv.pk).update(state='closed', closed_at=self.now)
        self.assertEqual(self.fetch().status_code, 200)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.state, 'closed')

    def test_linked_foreign_owner_is_404_without_disclosure(self):
        ContactIdentity.objects.filter(pk=self.contact.pk).update(owner=self.foreign_owner)
        response = self.fetch()
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('PRIVATE_FOREIGN', str(response.data))

    def test_foreign_route_and_valid_ids_without_thread_are_404(self):
        foreign = reverse('inbox-thread-context', args=[self.contact.public_id, self.foreign_account.public_id])
        other = ChannelAccount.objects.create(organization=self.org, external_account_id='context-unused')
        missing = reverse('inbox-thread-context', args=[self.contact.public_id, other.public_id])
        random = reverse('inbox-thread-context', args=[uuid4(), self.account.public_id])
        for url in (foreign, missing, random):
            self.assertEqual(self.fetch(url).status_code, 404)

    def test_foreign_user_cannot_read_local_context(self):
        foreign = User.objects.create(username='context-intruder', organization=self.foreign_org, role='ADMIN')
        self.client.force_authenticate(foreign)
        self.assertEqual(self.fetch().status_code, 404)

    def test_corrupt_foreign_pet_and_appointment_cannot_escape_scope(self):
        foreign_pet = Pet.objects.create(organization=self.foreign_org, owner=self.foreign_owner, name='PRIVATE_FOREIGN_PET')
        Pet.objects.filter(pk=foreign_pet.pk).update(owner=self.owner)
        local_appt = self.appointment(hour=16, status='no_show')
        Appointment.objects.filter(pk=local_appt.pk).update(organization=self.foreign_org)
        data = self.fetch().data
        self.assertEqual([pet['public_id'] for pet in data['pets']], [str(self.pet.public_id)])
        self.assertIsNone(data['last_appointment'])
        self.assertNotIn('PRIVATE_FOREIGN', str(data))

    def test_inactive_owner_is_not_disclosed(self):
        Owner.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.fetch().status_code, 404)

    def test_inactive_pets_are_excluded_with_their_appointments(self):
        self.appointment()
        Pet.objects.filter(pk=self.pet.pk).update(is_active=False)
        data = self.fetch().data
        self.assertEqual(data['pets'], [])
        self.assertIsNone(data['last_appointment'])

    def test_vet_and_reception_can_view_service_account_and_anonymous_cannot(self):
        self.assertEqual(self.fetch().status_code, 200)
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.fetch().status_code, 200)
        agent = User.objects.create(username='context-agent', organization=self.org, role='AGENT', is_service_account=True)
        self.client.force_authenticate(agent)
        self.assertEqual(self.fetch().status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.fetch().status_code, (401, 403))

    def test_get_has_no_business_or_read_state_writes_and_rejects_post(self):
        conversation = Conversation.objects.values().get(pk=self.conv.pk)
        contact = ContactIdentity.objects.values().get(pk=self.contact.pk)
        message = Message.objects.values().get(pk=self.message.pk)
        self.assertEqual(self.fetch().status_code, 200)
        self.assertEqual(conversation, Conversation.objects.values().get(pk=self.conv.pk))
        self.assertEqual(contact, ContactIdentity.objects.values().get(pk=self.contact.pk))
        self.assertEqual(message, Message.objects.values().get(pk=self.message.pk))
        self.assertFalse(InboxReadState.objects.exists())
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    def test_queries_do_not_grow_with_number_of_pets(self):
        with CaptureQueriesContext(connection) as first:
            self.assertEqual(self.fetch().status_code, 200)
        for index in range(35):
            Pet.objects.create(organization=self.org, owner=self.owner, name=f'Mascota {index}')
        with CaptureQueriesContext(connection) as second:
            response = self.fetch()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['pets']), 36)
        relevant = lambda queries: [query['sql'] for query in queries if any(
            table in query['sql'] for table in ('"patients_', '"agent_contactidentity"', '"agent_conversation"',
                                               '"channels_channelaccount"', '"appointments_appointment"'))]
        self.assertEqual(len(relevant(first)), 6)
        self.assertEqual(len(relevant(second)), 6)
