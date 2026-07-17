"""
test_services.py — É-F0 PR-4: normalización, identidad y conversación.
"""
from django.test import TestCase

from apps.agent.models import ContactIdentity, Conversation
from apps.agent.services import (
    get_or_create_open_conversation,
    ingest_inbound_message,
    normalize_wa_id,
    resolve_contact_identity,
)
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from apps.patients.models import Owner


class NormalizeWaIdTests(TestCase):
    """Tabla de la decisión Q5 — la regla completa, incluidos los rechazos."""

    CASES = [
        ("5215512345678", "5512345678"),   # 521 + 10 (móvil MX)
        ("525512345678", "5512345678"),    # 52 + 10
        ("5512345678", "5512345678"),      # 10 pelones
        ("+52 1 55 1234 5678", "5512345678"),  # con ruido de formato
        ("15551234567", ""),               # US: no normalizable
        ("52112345", ""),                  # corto
        ("", ""),
        (None, ""),
    ]

    def test_table(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_wa_id(raw), expected)


class ResolveContactIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Svc Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="900100900",
        )

    def test_no_owner_match_stays_unknown(self):
        contact = resolve_contact_identity(self.channel, "5215500000001", "Ana")
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN
        )
        self.assertIsNone(contact.owner)
        self.assertEqual(contact.phone_normalized, "5500000001")
        self.assertEqual(contact.display_name, "Ana")

    def test_single_owner_match_is_phone_match(self):
        owner = Owner.objects.create(
            organization=self.org, name="Ana Torres", phone="5500000002",
        )
        contact = resolve_contact_identity(self.channel, "5215500000002")
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_PHONE_MATCH
        )
        self.assertEqual(contact.owner, owner)

    def test_multiple_owners_is_ambiguous_never_guesses(self):
        Owner.objects.create(
            organization=self.org, name="Juan Uno", phone="5500000003",
        )
        Owner.objects.create(
            organization=self.org, name="Juan Dos", phone="5500000003",
        )
        contact = resolve_contact_identity(self.channel, "5215500000003")
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN
        )
        self.assertIsNone(contact.owner)   # el sistema jamás elige (E-05)
        self.assertTrue(contact.is_ambiguous)

    def test_generic_owner_never_matches(self):
        # El Owner genérico lo crea el signal initialize_organization (único
        # parcial por org) — se le asigna el teléfono bajo prueba.
        generic = Owner.all_objects.get(organization=self.org, is_generic=True)
        generic.phone = "5500000004"
        generic.save(update_fields=["phone"])
        contact = resolve_contact_identity(self.channel, "5215500000004")
        self.assertIsNone(contact.owner)

    def test_match_is_org_scoped(self):
        """Owner con el mismo teléfono en OTRA org no matchea (R1)."""
        other_org = Organization.objects.create(name="Svc Org B", timezone="UTC")
        Owner.objects.create(
            organization=other_org, name="Ajena", phone="5500000005",
        )
        contact = resolve_contact_identity(self.channel, "5215500000005")
        self.assertIsNone(contact.owner)

    def test_identity_is_reused_and_display_name_refreshed(self):
        first = resolve_contact_identity(self.channel, "5215500000006", "Ana")
        second = resolve_contact_identity(self.channel, "5215500000006", "Ana T.")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.display_name, "Ana T.")


class ConversationLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Conv Svc Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="900200900",
        )
        cls.contact = ContactIdentity.objects.create(
            organization=cls.org, external_id="5215500001111",
        )

    def test_open_conversation_is_reused(self):
        first = get_or_create_open_conversation(self.contact, self.channel)
        second = get_or_create_open_conversation(self.contact, self.channel)
        self.assertEqual(first.pk, second.pk)

    def test_closed_conversation_is_never_reopened(self):
        """Spec §2.8: CLOSED es terminal — mensaje posterior = hilo nuevo."""
        first = get_or_create_open_conversation(self.contact, self.channel)
        first.state = Conversation.STATE_CLOSED
        first.save(update_fields=["state"])

        second = get_or_create_open_conversation(self.contact, self.channel)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.state, Conversation.STATE_ACTIVE)

    def test_ingest_updates_conversation_timestamps(self):
        message = ingest_inbound_message(
            self.channel, wamid="wamid.T1", wa_id="5215500001111", body="hola",
        )
        conv = message.conversation
        self.assertIsNotNone(conv.last_inbound_at)
        self.assertEqual(conv.last_activity_at, conv.last_inbound_at)
        self.assertEqual(message.status, Message.STATUS_PENDING)
        self.assertIsNotNone(message.available_at)  # drain-on-pickup

    def test_ingest_dedup_returns_none(self):
        ingest_inbound_message(
            self.channel, wamid="wamid.T2", wa_id="5215500001111", body="hola",
        )
        again = ingest_inbound_message(
            self.channel, wamid="wamid.T2", wa_id="5215500001111", body="hola",
        )
        self.assertIsNone(again)
        self.assertEqual(
            Message.objects.filter(external_message_id="wamid.T2").count(), 1
        )

    def test_blocked_contact_message_is_discarded_but_audited(self):
        """GB-10: se persiste (auditable) pero el worker no lo procesará."""
        blocked = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500002222", is_blocked=True,
        )
        message = ingest_inbound_message(
            self.channel, wamid="wamid.T3", wa_id="5215500002222", body="spam",
        )
        self.assertEqual(message.status, Message.STATUS_DISCARDED)
        self.assertEqual(message.conversation.contact, blocked)
