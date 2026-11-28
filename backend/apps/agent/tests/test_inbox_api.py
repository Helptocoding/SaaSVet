"""
test_inbox_api.py — É-F0 PR-6: API de la bandeja (/api/inbox/).

RBAC por catálogo real (roles sembrados desde PERMISSIONS), aislamiento
tenant, semántica de claim/send/close/release y kill switch.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.agent.models import (
    AgentSettings,
    ContactIdentity,
    Conversation,
    HumanHandoff,
)
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.patients.models import Owner

User = get_user_model()


def _seed_role_from_catalog(org, role_name):
    codes = PERMISSIONS[role_name]
    role, _ = Role.objects.get_or_create(
        name=role_name, organization=org, defaults={"is_system_role": True}
    )
    if "*.*" in codes:
        wildcard, _ = Permission.objects.get_or_create(code="*.*")
        role.permissions.set([wildcard])
    else:
        perms = [Permission.objects.get_or_create(code=c)[0] for c in codes]
        role.permissions.set(perms)
    return role


def _make_user(username, org, role_name):
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role=role_name
    )
    UserRole.objects.get_or_create(user=u, role=_seed_role_from_catalog(org, role_name))
    return u


class InboxApiTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Inbox Org", timezone="UTC")
        cls.admin = _make_user("inbox_admin", cls.org, "ADMIN")
        cls.assistant = _make_user("inbox_asst", cls.org, "ASSISTANT")
        cls.vet = _make_user("inbox_vet", cls.org, "VET")

        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="600100600",
        )
        cls.contact = ContactIdentity.objects.create(
            organization=cls.org, external_id="5215544332211",
            display_name="Ana", phone_normalized="5544332211",
        )
        cls.conversation = Conversation.objects.create(
            organization=cls.org, channel_account=cls.channel,
            contact=cls.contact,
        )
        Message.objects.create(
            organization=cls.org, channel_account=cls.channel,
            conversation=cls.conversation,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            body="hola, quiero una cita",
            status=Message.STATUS_PROCESSED,
        )

        # Fixture trampa cross-tenant (patrón de la suite de la spec §9.2).
        cls.other_org = Organization.objects.create(
            name="Ajena Org", timezone="UTC",
        )
        other_channel = ChannelAccount.objects.create(
            organization=cls.other_org, external_account_id="600200600",
        )
        other_contact = ContactIdentity.objects.create(
            organization=cls.other_org, external_id="5215500001234",
        )
        cls.other_conversation = Conversation.objects.create(
            organization=cls.other_org, channel_account=other_channel,
            contact=other_contact,
        )


class InboxRbacTests(InboxApiTestCase):
    def test_assistant_can_list(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/inbox/conversations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_vet_can_view_but_not_send(self):
        self.client.force_authenticate(self.vet)
        r = self.client.get("/api/inbox/conversations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {"body": "hola"},
            HTTP_X_IDEMPOTENCY_KEY="rbac-does-not-bypass",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_assistant_cannot_touch_settings(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/inbox/settings/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_conversation_is_404(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get(
            f"/api/inbox/conversations/{self.other_conversation.public_id}/messages/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_idempotency_replay_cannot_bypass_cross_tenant_send_404(self):
        Message.objects.create(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conversation,
            contact=self.contact,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_HUMAN,
            human_author=self.assistant,
            body='mensaje local',
            status=Message.STATUS_PENDING,
            idempotency_key='tenant-bound-replay',
        )
        self.client.force_authenticate(self.assistant)

        response = self.client.post(
            f"/api/inbox/conversations/{self.other_conversation.public_id}/send/",
            {'body': 'no debe devolver el local'},
            HTTP_X_IDEMPOTENCY_KEY='tenant-bound-replay',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_excludes_other_orgs(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/inbox/conversations/")
        ids = {c["public_id"] for c in r.json()}
        self.assertIn(str(self.conversation.public_id), ids)
        self.assertNotIn(str(self.other_conversation.public_id), ids)

    def test_serializer_exposes_public_id_only(self):
        """ADR p24: serializer nuevo jamás expone id+public_id."""
        self.client.force_authenticate(self.assistant)
        item = self.client.get("/api/inbox/conversations/").json()[0]
        self.assertIn("public_id", item)
        self.assertNotIn("id", item)


class InboxFlowTests(InboxApiTestCase):
    def _send(self, body, key=None):
        self.client.force_authenticate(self.assistant)
        headers = ({'HTTP_X_IDEMPOTENCY_KEY': key} if key is not None else {})
        return self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {'body': body},
            **headers,
        )

    def test_list_shows_preview_and_unanswered(self):
        self.client.force_authenticate(self.assistant)
        item = self.client.get("/api/inbox/conversations/").json()[0]
        self.assertEqual(item["last_message_preview"], "hola, quiero una cita")
        self.assertTrue(item["has_unanswered"])
        self.assertEqual(item["contact_display_name"], "Ana")

    def test_transcript_returns_messages_in_order(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.get(
            f"/api/inbox/conversations/{self.conversation.public_id}/messages/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["direction"], "in")

    def test_send_creates_outbound_and_takes_over(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {"body": "  ¡Claro! ¿Para qué día?  "},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

        message = Message.objects.get(
            conversation=self.conversation, direction=Message.DIRECTION_OUT,
        )
        self.assertEqual(message.author_type, Message.AUTHOR_HUMAN)
        self.assertEqual(message.human_author, self.assistant)
        self.assertEqual(message.status, Message.STATUS_PENDING)  # outbox

        self.conversation.refresh_from_db()
        self.assertEqual(
            self.conversation.state, Conversation.STATE_HUMAN_ACTIVE,
        )
        self.assertEqual(self.conversation.claimed_by, self.assistant)

    def test_send_same_idempotency_key_replays_same_message_once(self):
        first = self._send('primera entrega', 'same-send-key')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.content)
        self.assertEqual(first.json()['client_message_id'], 'same-send-key')

        # Un replay no vuelve a ejecutar takeover ni actualiza actividad.
        frozen_activity = timezone.now() - timedelta(days=1)
        Conversation.objects.filter(pk=self.conversation.pk).update(
            claimed_by=self.admin,
            last_activity_at=frozen_activity,
        )
        second = self._send('primera entrega', 'same-send-key')

        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.content)
        self.assertEqual(second.json()['id'], first.json()['id'])
        self.assertEqual(second.json()['client_message_id'],
                         first.json()['client_message_id'])
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                idempotency_key='same-send-key',
            ).count(),
            1,
        )
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.claimed_by, self.admin)
        self.assertEqual(self.conversation.last_activity_at, frozen_activity)

    def test_send_replay_survives_conversation_closed_after_first_send(self):
        first = self._send('antes del cierre', 'replay-after-close')
        Conversation.objects.filter(pk=self.conversation.pk).update(
            state=Conversation.STATE_CLOSED,
            closed_at=timezone.now(),
        )

        replay = self._send('body ignorado', 'replay-after-close')

        self.assertEqual(replay.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.json()['id'], first.json()['id'])
        self.assertEqual(replay.json()['body'], 'antes del cierre')
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                idempotency_key='replay-after-close',
            ).count(),
            1,
        )

    def test_send_different_idempotency_keys_create_separate_messages(self):
        first = self._send('uno', 'send-key-one')
        second = self._send('dos', 'send-key-two')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(
            Message.objects.filter(
                organization=self.org, direction=Message.DIRECTION_OUT,
            ).count(),
            2,
        )

    def test_send_without_idempotency_header_keeps_current_behavior(self):
        first = self._send('sin llave')
        second = self._send('sin llave')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(first.json()['client_message_id'])
        self.assertIsNone(second.json()['client_message_id'])
        self.assertNotEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                idempotency_key__isnull=True,
            ).count(),
            2,
        )

    def test_client_message_id_is_output_only(self):
        self.client.force_authenticate(self.assistant)

        response = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {'body': 'sin correlación', 'client_message_id': 'forged-client-id'},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.json()['client_message_id'])
        message = Message.objects.get(pk=response.json()['id'])
        self.assertIsNone(message.idempotency_key)

    def test_send_same_key_with_different_body_returns_original(self):
        first = self._send('texto original', 'same-key-new-body')
        second = self._send('texto que no debe sustituirlo', 'same-key-new-body')

        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.json()['id'], first.json()['id'])
        self.assertEqual(second.json()['body'], 'texto original')
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                idempotency_key='same-key-new-body',
            ).count(),
            1,
        )

    def test_send_idempotency_key_is_trimmed_and_truncated_to_64(self):
        prefix = 'k' * 64
        first = self._send('truncado', f'  {prefix}first  ')
        second = self._send('otro', f'{prefix}second')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.json()['id'], first.json()['id'])
        message = Message.objects.get(pk=first.json()['id'])
        self.assertEqual(message.idempotency_key, prefix)

    def test_send_idempotency_key_is_scoped_by_organization(self):
        other_message = Message.objects.create(
            organization=self.other_org,
            channel_account=self.other_conversation.channel_account,
            conversation=self.other_conversation,
            contact=self.other_conversation.contact,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_HUMAN,
            body='mensaje ajeno',
            status=Message.STATUS_PENDING,
            idempotency_key='shared-between-orgs',
        )

        response = self._send('mensaje propio', 'shared-between-orgs')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.json()['id'], other_message.pk)
        self.assertEqual(response.json()['body'], 'mensaje propio')
        self.assertEqual(
            Message.objects.filter(
                direction=Message.DIRECTION_OUT,
                idempotency_key='shared-between-orgs',
            ).count(),
            2,
        )

    def test_internal_outbound_key_is_never_replayed_to_staff(self):
        key = 'shared-with-internal-outbound'
        internal = [
            Message.objects.create(
                organization=self.org,
                channel_account=self.channel,
                conversation=self.conversation,
                contact=self.contact,
                direction=Message.DIRECTION_OUT,
                author_type=author_type,
                body=f'cuerpo interno {author_type}',
                status=Message.STATUS_SENT,
                idempotency_key=key,
            )
            for author_type in (Message.AUTHOR_AGENT, Message.AUTHOR_SYSTEM)
        ]

        first = self._send('respuesta pública del staff', key)
        replay = self._send('este cuerpo pierde', key)

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json()['body'], 'respuesta pública del staff')
        self.assertEqual(first.json()['author_type'], Message.AUTHOR_HUMAN)
        self.assertEqual(first.json()['client_message_id'], key)
        self.assertNotIn(first.json()['id'], {message.pk for message in internal})
        self.assertEqual(replay.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.json()['id'], first.json()['id'])
        self.assertEqual(replay.json()['body'], 'respuesta pública del staff')
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                author_type=Message.AUTHOR_HUMAN,
                idempotency_key=key,
            ).count(),
            1,
        )

    def test_send_recovers_winner_after_idempotency_integrity_race(self):
        winner = Message.objects.create(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conversation,
            contact=self.contact,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_HUMAN,
            human_author=self.admin,
            body='ganador concurrente',
            status=Message.STATUS_PENDING,
            idempotency_key='race-key',
        )

        with patch(
            'apps.agent.views._replay_outbound_message',
            side_effect=[None, winner],
        ) as replay, patch(
            'apps.agent.views.Message.save',
            side_effect=IntegrityError('duplicate key'),
        ):
            response = self._send('perdedor', 'race-key')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['id'], winner.pk)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(
            Message.objects.filter(
                organization=self.org,
                direction=Message.DIRECTION_OUT,
                idempotency_key='race-key',
            ).count(),
            1,
        )
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.state, Conversation.STATE_ACTIVE)
        self.assertIsNone(self.conversation.claimed_by)

    def test_send_does_not_mask_integrity_error_without_winner(self):
        with patch(
            'apps.agent.views._replay_outbound_message', return_value=None,
        ), patch(
            'apps.agent.views.Message.save',
            side_effect=IntegrityError('unrelated constraint'),
        ):
            response = self._send('mensaje', 'no-winner-key')

        # El exception handler global convierte la excepción relanzada en 500;
        # no se presenta falsamente como replay 201.
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_send_empty_body_rejected(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {"body": "   "},
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_to_closed_conversation_rejected(self):
        self.conversation.state = Conversation.STATE_CLOSED
        self.conversation.save(update_fields=["state"])
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/send/",
            {"body": "hola"},
            HTTP_X_IDEMPOTENCY_KEY="closed-does-not-reopen",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_claim_is_exclusive(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/claim/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.admin)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/claim/"
        )
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(r.json()["code"], "already_claimed")

    def test_close_and_release(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/claim/"
        )
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/release/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.state, Conversation.STATE_ACTIVE)
        self.assertIsNone(self.conversation.claimed_by)

        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/close/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.state, Conversation.STATE_CLOSED)
        self.assertIsNotNone(self.conversation.closed_at)


class InboxSendIdempotencyRaceTests(APITransactionTestCase):
    """La restricción DB decide una carrera real entre dos POST concurrentes."""

    reset_sequences = True

    def setUp(self):
        self.org = Organization.objects.create(
            name='Inbox Race Org', timezone='UTC',
        )
        self.sender_one = _make_user('race_sender_one', self.org, 'ASSISTANT')
        self.sender_two = _make_user('race_sender_two', self.org, 'ASSISTANT')
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id='600300600',
        )
        self.contact = ContactIdentity.objects.create(
            organization=self.org,
            external_id='5215512349999',
            display_name='Carrera',
            phone_normalized='5512349999',
        )
        self.conversation = Conversation.objects.create(
            organization=self.org,
            channel_account=self.channel,
            contact=self.contact,
        )

    def _concurrent_send(self, user, backend_pids):
        # Django mantiene una conexión por thread. Cerrar cualquier conexión
        # heredada obliga a que cada worker abra su propia sesión PostgreSQL.
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                backend_pids.append(cursor.fetchone()[0])

            client = APIClient()
            client.force_authenticate(user)
            response = client.post(
                f'/api/inbox/conversations/{self.conversation.public_id}/send/',
                {'body': f'respuesta de {user.username}'},
                HTTP_X_IDEMPOTENCY_KEY='real-concurrent-send',
            )
            return response.status_code, response.json()
        finally:
            close_old_connections()

    def test_two_real_concurrent_sends_replay_single_winner(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La carrera requiere PostgreSQL y su índice parcial.')

        from apps.agent import views as inbox_views

        real_replay = inbox_views._replay_outbound_message
        precheck_entry_barrier = threading.Barrier(2, timeout=10)
        empty_precheck_barrier = threading.Barrier(2, timeout=10)
        first_call_by_thread = threading.local()
        backend_pids = []

        def synchronized_replay(organization, idempotency_key):
            if not getattr(first_call_by_thread, 'completed', False):
                first_call_by_thread.completed = True
                # Los dos clientes entran juntos al pre-check y, además, ambos
                # deben haber observado «no existe» antes de permitir que
                # cualquiera llegue al INSERT. Las llamadas posteriores son
                # la recuperación normal del perdedor y no esperan aquí.
                precheck_entry_barrier.wait()
                result = real_replay(organization, idempotency_key)
                self.assertIsNone(result)
                empty_precheck_barrier.wait()
                return result
            return real_replay(organization, idempotency_key)

        with patch(
            'apps.agent.views._replay_outbound_message',
            side_effect=synchronized_replay,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self._concurrent_send,
                        sender,
                        backend_pids,
                    )
                    for sender in (self.sender_one, self.sender_two)
                ]
                responses = [future.result(timeout=20) for future in futures]

        self.assertEqual(len(set(backend_pids)), 2)
        self.assertEqual(
            [http_status for http_status, _ in responses],
            [status.HTTP_201_CREATED, status.HTTP_201_CREATED],
        )
        response_ids = {payload['id'] for _, payload in responses}
        self.assertEqual(len(response_ids), 1)

        messages = Message.objects.filter(
            organization=self.org,
            direction=Message.DIRECTION_OUT,
            idempotency_key='real-concurrent-send',
        )
        self.assertEqual(messages.count(), 1)
        winner = messages.select_related('human_author').get()
        self.assertEqual(response_ids, {winner.pk})

        # El takeover pertenece al mismo request que ganó el único INSERT.
        self.conversation.refresh_from_db()
        self.assertEqual(
            self.conversation.state, Conversation.STATE_HUMAN_ACTIVE,
        )
        self.assertEqual(self.conversation.claimed_by, winner.human_author)


class InboxReleaseClosesTheCircleTests(InboxApiTestCase):
    """Fase 1 §1.2 — conv 13 S9: `release` dejaba el `HumanHandoff` sin
    resolver mientras el agente ya volvía a hablar (`resolved_at=None`,
    `state=active`). Cierra ese hueco, y decide qué pasa con un compromiso
    suspendido (§1.1) según si el contacto ya quedó verificado o no."""

    def setUp(self):
        from apps.agent import goals
        commitment = goals.start_identity(
            self.conversation, goals.FAMILY, first_factor='digits')
        goals.park_identity(self.conversation, commitment,
                            going_to_human=True)
        self.conversation.state = Conversation.STATE_HANDOFF_PENDING
        self.conversation.save(update_fields=['state'])
        self.handoff = HumanHandoff.objects.create(
            organization=self.org, conversation=self.conversation,
            reason_code=HumanHandoff.REASON_IDENTITY,
        )

    def _release(self):
        self.client.force_authenticate(self.assistant)
        return self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/release/"
        )

    def test_release_resolves_the_open_handoff(self):
        r = self._release()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.handoff.refresh_from_db()
        self.assertIsNotNone(self.handoff.resolved_at)
        self.assertEqual(
            self.handoff.resolution, HumanHandoff.RESOLUTION_RETURNED_TO_AGENT)
        self.assertEqual(self.handoff.claimed_by, self.assistant)

    def test_release_is_idempotent_on_the_handoff(self):
        self._release()
        r = self._release()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(
            HumanHandoff.objects.filter(
                conversation=self.conversation, resolved_at__isnull=False,
            ).count(),
            1,
        )

    def test_release_leaves_the_parked_challenge_for_lazy_resume(self):
        """Sin verificación, el reto apartado NO se cierra — lo retoma
        `policy.evaluate` con el próximo mensaje del cliente."""
        from apps.agent.tests.harness import identity_commitment
        self._release()
        self.assertIsNotNone(
            identity_commitment(self.conversation, parked=True))

    def test_release_drops_the_parked_challenge_when_already_verified(self):
        """Verificado por otra vía (el propio equipo, p.ej.) mientras el reto
        estaba apartado: re-interrogarlo no tiene sentido."""
        from apps.agent.tests.harness import identity_commitment
        self.contact.verification_level = ContactIdentity.VERIFICATION_STAFF
        self.contact.save(update_fields=['verification_level'])
        self._release()
        self.assertIsNone(
            identity_commitment(self.conversation, parked=True))


class InboxResetIdentityTests(InboxApiTestCase):
    """`reset-identity`: generaliza `unlink-family` a CUALQUIER `linked_via`
    (aquí, `self_register` — el caso que `unlink-family` rechaza a propósito).
    Solo ADMIN (`agentinbox.config`), a diferencia de claim/close/unlink-family
    (`agentinbox.claim`, que ASSISTANT también tiene)."""

    def setUp(self):
        self.owner = Owner.objects.create(
            organization=self.org, name="Felipe Díaz", phone="9371651868",
        )
        self.contact.owner = self.owner
        self.contact.verification_level = ContactIdentity.VERIFICATION_CONFIRMED
        self.contact.linked_via = ContactIdentity.LINKED_SELF_REGISTER
        self.contact.verified_at = self.conversation.created_at
        self.contact.save(update_fields=[
            "owner", "verification_level", "linked_via", "verified_at"])

    def test_admin_resets_self_registered_contact_and_closes_thread(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/reset-identity/"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.contact.refresh_from_db()
        self.assertIsNone(self.contact.owner_id)
        self.assertEqual(
            self.contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN)
        self.assertIsNone(self.contact.verified_at)
        self.assertEqual(self.contact.linked_via, "")
        # No debe volver a vincularse solo por teléfono en el siguiente
        # mensaje del mismo número (ver RematchOwnerTests en test_services.py).
        self.assertTrue(self.contact.auto_rematch_blocked)

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.state, Conversation.STATE_CLOSED)
        self.assertIsNotNone(self.conversation.closed_at)

    def test_unlink_family_refuses_self_registered_contact(self):
        """Confirma el contraste: el endpoint viejo NUNCA toca self_register."""
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/unlink-family/"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.owner.pk)

    def test_assistant_cannot_reset_identity(self):
        self.client.force_authenticate(self.assistant)
        r = self.client.post(
            f"/api/inbox/conversations/{self.conversation.public_id}/reset-identity/"
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.owner_id, self.owner.pk)

    def test_reset_identity_is_tenant_scoped(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            f"/api/inbox/conversations/{self.other_conversation.public_id}/reset-identity/"
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class InboxSettingsTests(InboxApiTestCase):
    def _capture_clinic_phone(self, phone="5512345678"):
        self.org.phone = phone
        self.org.save(update_fields=["phone"])

    def test_admin_toggles_kill_switch(self):
        self._capture_clinic_phone()
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/inbox/settings/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.json()["enabled"])

        r = self.client.patch(
            "/api/inbox/settings/", {"enabled": True}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(
            AgentSettings.objects.get(organization=self.org).enabled
        )

    # ---- Gate: enabled=True exige teléfono de clínica -----------------------
    # No es UX, es seguridad: la plantilla de URGENCIA le dice al cliente que
    # acuda a la clínica; sin teléfono, sin número al que llamar. Ese estado no
    # debe ser alcanzable.

    def test_enable_without_clinic_phone_is_rejected(self):
        self.assertEqual(self.org.phone, "")
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/", {"enabled": True}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertIn("Configuración", r.content.decode())
        self.assertFalse(AgentSettings.objects.get(organization=self.org).enabled)

    def test_enable_with_legacy_invalid_phone_is_rejected(self):
        """Filas guardadas antes de que el serializer validara (p.ej. `"5"`).

        Desde p70 `Organization.save()` ya no admite ese valor y la migración
        0016 los vació; la fila heredada se simula por debajo de `save()`."""
        Organization.objects.filter(pk=self.org.pk).update(phone="5")
        self.org.refresh_from_db()
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/", {"enabled": True}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_disabling_never_requires_a_phone(self):
        """Apagar el agente SIEMPRE debe poder hacerse (es el kill switch).

        Incluso en el estado que INV-L (ADR p70) ya no deja crear: encendido y sin
        teléfono. Se simula una fila previa a la migración 0031, por debajo de
        `save()`."""
        AgentSettings.objects.update_or_create(
            organization=self.org, defaults={"enabled": False},
        )
        AgentSettings.objects.filter(organization=self.org).update(enabled=True)
        self.assertEqual(self.org.phone, "")
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/", {"enabled": False}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertFalse(AgentSettings.objects.get(organization=self.org).enabled)

    def test_other_fields_editable_without_clinic_phone(self):
        """El gate solo bloquea el encendido, no toda la configuración."""
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/",
            {"faq_facts": {"estacionamiento": "Sí"}}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_schedule_is_not_configurable_here(self):
        """El horario vive en Configuración → Horario (`OrganizationSchedule`).

        `business_hours` se eliminó: dos superficies escribiendo el horario
        significaba que el ADMIN podía configurarlo en un lado y el agente
        usar el otro. Un intento de mandarlo aquí se ignora en silencio (campo
        desconocido), nunca crea una segunda fuente.
        """
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/",
            {"business_hours": {"mon": [["09:00", "19:00"]]}},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertNotIn("business_hours", r.json())

    def test_faq_facts_reject_keys_owned_by_clinic_config(self):
        """Lo que ya se edita en Configuración → Clínica no se duplica aquí."""
        self.client.force_authenticate(self.admin)
        for key in ("telefono", "Teléfono", "direccion", "horario", "correo"):
            with self.subTest(key=key):
                r = self.client.patch(
                    "/api/inbox/settings/",
                    {"faq_facts": {key: "algo"}}, format="json",
                )
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_faq_facts_accept_free_keys(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            "/api/inbox/settings/",
            {"faq_facts": {"estacionamiento": "Sí, gratuito"}}, format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)


class HandoffReasonIsVisibleTests(InboxApiTestCase):
    """El equipo tiene que saber POR QUÉ le llegó el caso.

    El dato existía desde siempre en `HumanHandoff` y se quedaba en la base:
    la API publicaba solo `reason_code` (que clasifica) y descartaba
    `reason_detail` (que es el que informa). Recepción veía «Esperando» y
    tenía que leer el transcript entero para deducir qué había pasado.

    El caso real que lo destapó: conversación con `low_confidence` /
    `goal_stalled` — el asistente llevaba tres turnos pidiendo la mascota y
    nadie podía saberlo sin leer 29 mensajes.
    """

    def _stall(self):
        from apps.agent.models import ConversationGoal
        handoff = HumanHandoff.objects.create(
            organization=self.org, conversation=self.conversation,
            reason_code=HumanHandoff.REASON_LOW_CONFIDENCE,
            reason_detail="goal_stalled",
        )
        goal = ConversationGoal.objects.create(
            organization=self.org, conversation=self.conversation,
            name="schedule_appointment",
            status=ConversationGoal.STATUS_HANDOFF,
            slots={"date": {"value": "2026-08-14"}, "time": {"value": "12:00"}},
        )
        return handoff, goal

    def test_list_exposes_the_fine_grained_detail(self):
        self._stall()
        self.client.force_authenticate(self.assistant)
        r = self.client.get("/api/inbox/conversations/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        row = next(c for c in r.json()
                   if c["public_id"] == str(self.conversation.public_id))
        self.assertEqual(row["handoff_reason"], "low_confidence")
        # Lo que de verdad ubica a quien atiende.
        self.assertEqual(row["handoff_detail"], "goal_stalled")

    def test_thread_explains_what_the_client_wanted_and_what_was_missing(self):
        self._stall()
        self.client.force_authenticate(self.assistant)
        r = self.client.get(
            f"/api/inbox/conversations/{self.conversation.public_id}/messages/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        handoff = r.json()["handoff"]
        self.assertEqual(handoff["reason"], "low_confidence")
        self.assertEqual(handoff["detail"], "goal_stalled")

        goal = handoff["goal"]
        self.assertEqual(goal["promise"], "agendarle una cita")
        # Etiquetas de negocio, NUNCA nombres de slot: quien lee esto es una
        # recepcionista, no quien escribió el modelo.
        capturado = {c["label"]: c["value"] for c in goal["captured"]}
        self.assertEqual(capturado["el día de la cita"], "2026-08-14")
        self.assertEqual(capturado["la hora de la cita"], "12:00")
        faltaba = [m["label"] for m in goal["missing"]]
        self.assertIn("la mascota que vamos a atender", faltaba)
        self.assertIn("el motivo de la consulta", faltaba)
        self.assertNotIn("pet_handle", str(goal))

    def test_a_conversation_without_handoff_says_nothing(self):
        """`None`, no un objeto vacío: la bandeja solo pinta lo que existe."""
        self.client.force_authenticate(self.assistant)
        r = self.client.get(
            f"/api/inbox/conversations/{self.conversation.public_id}/messages/")
        self.assertIsNone(r.json()["handoff"])

    def test_a_resolved_handoff_stops_being_shown(self):
        from django.utils import timezone
        handoff, _ = self._stall()
        handoff.resolved_at = timezone.now()
        handoff.save(update_fields=["resolved_at"])
        self.client.force_authenticate(self.assistant)
        r = self.client.get(
            f"/api/inbox/conversations/{self.conversation.public_id}/messages/")
        self.assertIsNone(r.json()["handoff"])
