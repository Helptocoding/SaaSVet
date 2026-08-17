"""
test_inbox_threads.py — La bandeja agrupa por persona (§4 del plan).

La mitad visible de la queja: «mira todas las conversaciones, hay más de 10
conversaciones de un mismo usuario». La conversación sigue siendo el episodio
—de ella cuelgan métricas, claim, hand-off y compromisos— pero recepción ve una
fila por `(contacto, cuenta)`.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.agent.models import ContactIdentity, Conversation, HumanHandoff
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.users.models import User


class ThreadsTestCase(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Inbox Org", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="550100550")
        self.owner = Owner.objects.create(
            organization=self.org, name="Andrés Ruiz", phone="5511224488")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215511224488",
            owner=self.owner, display_name="Andrés",
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            verified_at=timezone.now())
        self.user = User.objects.create_user(
            username="recepcion", password="Recepcion12345",
            organization=self.org, role="ADMIN")
        self.client.force_authenticate(self.user)

    def _session(self, *, state=Conversation.STATE_ACTIVE, closed=None,
                 contact=None, channel=None, activity=None):
        return Conversation.objects.create(
            organization=self.org,
            channel_account=channel or self.channel,
            contact=contact or self.contact,
            state=state,
            closed_at=closed,
            last_activity_at=activity or timezone.now(),
        )

    def _msg(self, conversation, body, *, direction=Message.DIRECTION_IN,
             status=None):
        outbound = direction == Message.DIRECTION_OUT
        return Message.objects.create(
            organization=self.org,
            channel_account=conversation.channel_account,
            conversation=conversation,
            contact=conversation.contact,
            direction=direction,
            author_type=(Message.AUTHOR_AGENT if outbound
                         else Message.AUTHOR_CLIENT),
            body=body,
            status=status or (Message.STATUS_SENT if outbound
                              else Message.STATUS_PROCESSED),
        )

    def _threads(self, **params):
        response = self.client.get(reverse('inbox-threads'), params)
        self.assertEqual(response.status_code, 200)
        return response.data


class GroupingTests(ThreadsTestCase):
    def test_nineteen_sessions_become_one_row(self):
        """El caso literal de producción."""
        for index in range(19):
            self._session(state=Conversation.STATE_CLOSED,
                          closed=timezone.now() - timedelta(days=19 - index))
        current = self._session()
        self._msg(current, "hola de nuevo")

        rows = self._threads()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['session_count'], 20)
        self.assertEqual(rows[0]['conversation_public_id'],
                         str(current.public_id))

    def test_two_contacts_are_two_rows(self):
        other = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500001111")
        self._session()
        self._session(contact=other)
        self.assertEqual(len(self._threads()), 2)

    def test_two_channel_accounts_are_two_rows(self):
        """Dos números de la misma clínica pueden ser dos flujos: agruparlos
        juntaría conversaciones que nadie tuvo juntas."""
        other_channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="550100551")
        self._session()
        self._session(channel=other_channel)
        rows = self._threads()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            len({row['channel_account_public_id'] for row in rows}), 2)

    def test_the_row_carries_the_whole_thread_activity(self):
        old = self._session(state=Conversation.STATE_CLOSED,
                            closed=timezone.now() - timedelta(days=2))
        self._msg(old, "lo de hace dos días")
        current = self._session()
        self._msg(current, "lo más reciente")

        row = self._threads()[0]
        self.assertEqual(row['last_message_preview'], "lo más reciente")
        self.assertTrue(row['has_unanswered'])


class ArchivedThreadTests(ThreadsTestCase):
    def test_an_archived_thread_is_hidden_by_default(self):
        self._session(state=Conversation.STATE_CLOSED, closed=timezone.now())
        self.assertEqual(self._threads(), [])

    def test_it_shows_with_the_explicit_flag_and_offers_no_actions(self):
        """Sin sesión vigente no hay acciones: publicar el `public_id` de una
        cerrada invitaría a la bandeja a ofrecer «responder» sobre algo que
        devuelve 400."""
        self._session(state=Conversation.STATE_CLOSED, closed=timezone.now())
        row = self._threads(archived='1')[0]
        self.assertIsNone(row['conversation_public_id'])
        self.assertIsNone(row['state'])
        self.assertIsNone(row['claimed_by_name'])

    def test_writing_to_a_closed_session_points_at_the_current_one(self):
        closed = self._session(state=Conversation.STATE_CLOSED,
                               closed=timezone.now() - timedelta(hours=2))
        current = self._session()
        response = self.client.post(
            reverse('inbox-send', args=[str(closed.public_id)]),
            {'body': 'hola'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'session_closed')
        self.assertEqual(response.data['current_conversation'],
                         str(current.public_id))


class ThreadDetailTests(ThreadsTestCase):
    def _url(self, name):
        return reverse(name, args=[str(self.contact.public_id),
                                   str(self.channel.public_id)])

    def test_sessions_are_listed_newest_first(self):
        old = self._session(state=Conversation.STATE_CLOSED,
                            closed=timezone.now() - timedelta(days=3),
                            activity=timezone.now() - timedelta(days=3))
        current = self._session()
        response = self.client.get(self._url('inbox-thread-sessions'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row['public_id'] for row in response.data['results']],
            [str(current.public_id), str(old.public_id)])
        self.assertEqual(response.data['count'], 2)

    def test_the_transcript_crosses_sessions(self):
        old = self._session(state=Conversation.STATE_CLOSED,
                            closed=timezone.now() - timedelta(days=1))
        self._msg(old, "esto lo dije la semana pasada")
        current = self._session()
        self._msg(current, "y esto hoy")

        response = self.client.get(self._url('inbox-thread-messages'))
        bodies = [m['body'] for m in response.data['messages']]
        self.assertEqual(bodies, ["esto lo dije la semana pasada", "y esto hoy"])

    def test_a_failed_outbound_is_not_shown(self):
        """Nunca llegó al cliente: mostrarlo haría creer que sí."""
        current = self._session()
        self._msg(current, "esto no salió", direction=Message.DIRECTION_OUT,
                  status=Message.STATUS_FAILED)
        response = self.client.get(self._url('inbox-thread-messages'))
        self.assertEqual(response.data['messages'], [])

    def test_the_cursor_walks_backwards(self):
        from apps.agent import views
        current = self._session()
        for index in range(views.THREAD_MESSAGES_PAGE + 5):
            self._msg(current, f"mensaje {index}")

        first = self.client.get(self._url('inbox-thread-messages')).data
        self.assertEqual(len(first['messages']),
                         views.THREAD_MESSAGES_PAGE)
        self.assertIsNotNone(first['next_before'])

        older = self.client.get(self._url('inbox-thread-messages'),
                                {'before': first['next_before']}).data
        self.assertEqual(len(older['messages']), 5)
        self.assertIsNone(older['next_before'])

    def test_another_org_gets_404(self):
        other_org = Organization.objects.create(name="Ajena", timezone="UTC")
        intruder = User.objects.create_user(
            username="ajeno", password="Ajeno12345678",
            organization=other_org, role="ADMIN")
        self.client.force_authenticate(intruder)
        response = self.client.get(self._url('inbox-thread-messages'))
        self.assertEqual(response.status_code, 404)


class UrgentOrderingTests(ThreadsTestCase):
    def test_an_urgent_handoff_sorts_first(self):
        """Una convulsión no puede quedar debajo de una duda de horarios más
        reciente."""
        quiet_contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500002222")
        urgent_session = self._session(
            activity=timezone.now() - timedelta(hours=3))
        HumanHandoff.objects.create(
            organization=self.org, conversation=urgent_session,
            reason_code=HumanHandoff.REASON_EMERGENCY,
            priority=HumanHandoff.PRIORITY_URGENT)
        self._msg(urgent_session, "mi perro convulsiona")

        recent = self._session(contact=quiet_contact)
        self._msg(recent, "¿a qué hora abren?")

        rows = self._threads()
        self.assertEqual(rows[0]['handoff_priority'],
                         HumanHandoff.PRIORITY_URGENT)


class DeprecatedConversationListTests(ThreadsTestCase):
    """El listado por episodio queda deprecado, no borrado (RFC 8594).

    La bandeja ya no lo llama; el Sunset existe para los clientes que no
    conocemos. El log es el gate para cortarlo a 410 — sin él, «¿lo usa
    alguien?» se contesta con una opinión.
    """

    def test_it_still_works(self):
        session = self._session()
        self._msg(session, "hola")
        response = self.client.get(reverse('inbox-conversations'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_it_announces_its_retirement(self):
        response = self.client.get(reverse('inbox-conversations'))
        self.assertEqual(response['Deprecation'], 'true')
        self.assertIn('2026', response['Sunset'])
        self.assertIn('/api/inbox/threads/', response['Link'])
        self.assertIn('successor-version', response['Link'])

    def test_the_hit_is_logged(self):
        with self.assertLogs('core.deprecation', level='WARNING') as captured:
            self.client.get(reverse('inbox-conversations'))
        self.assertTrue(
            any('DEPRECATED_ENDPOINT_HIT' in line for line in captured.output))

    def test_the_successor_is_not_deprecated(self):
        response = self.client.get(reverse('inbox-threads'))
        self.assertNotIn('Deprecation', response)
