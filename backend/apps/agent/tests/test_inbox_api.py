"""
test_inbox_api.py — É-F0 PR-6: API de la bandeja (/api/inbox/).

RBAC por catálogo real (roles sembrados desde PERMISSIONS), aislamiento
tenant, semántica de claim/send/close/release y kill switch.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.channels.models import ChannelAccount, Message
from apps.core.models import Permission, Role, UserRole
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization

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


class InboxSettingsTests(InboxApiTestCase):
    def test_admin_toggles_kill_switch(self):
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
