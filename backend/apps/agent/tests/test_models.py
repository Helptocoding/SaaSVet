"""
test_models.py — É-F0 PR-3: invariantes del núcleo conversacional.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.agent.models import AgentSettings, ContactIdentity, Conversation
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization


class ContactIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name="CI Org A", timezone="UTC")
        cls.org_b = Organization.objects.create(name="CI Org B", timezone="UTC")

    def test_unique_per_org_and_channel(self):
        ContactIdentity.objects.create(
            organization=self.org_a, external_id="5215511112222",
        )
        with self.assertRaises(ValidationError):
            ContactIdentity.objects.create(
                organization=self.org_a, external_id="5215511112222",
            )

    def test_same_external_id_in_another_org_is_allowed(self):
        """El mismo cliente puede escribirle a DOS clínicas distintas — la
        identidad de contacto es por organización, no global."""
        ContactIdentity.objects.create(
            organization=self.org_a, external_id="5215533334444",
        )
        ContactIdentity.objects.create(
            organization=self.org_b, external_id="5215533334444",
        )  # no levanta

    def test_defaults(self):
        ci = ContactIdentity.objects.create(
            organization=self.org_a, external_id="5215599990000",
        )
        self.assertEqual(ci.verification_level, ContactIdentity.VERIFICATION_UNKNOWN)
        self.assertFalse(ci.is_blocked)
        self.assertFalse(ci.is_ambiguous)
        self.assertIsNone(ci.owner)
        self.assertIsNone(ci.privacy_notice_sent_at)


class ConversationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Conv Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="333000333",
        )
        cls.contact = ContactIdentity.objects.create(
            organization=cls.org, external_id="5215512340000",
        )

    def test_defaults_and_public_id(self):
        conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact,
        )
        self.assertEqual(conv.state, Conversation.STATE_ACTIVE)
        self.assertEqual(conv.flow, {})
        self.assertIsNotNone(conv.public_id)  # la bandeja navega por UUID
        self.assertIsNone(conv.claimed_by)

    def test_invalid_state_rejected(self):
        conv = Conversation(
            organization=self.org, channel_account=self.channel,
            contact=self.contact, state="BLOCKED",  # estado eliminado en v1.1
        )
        with self.assertRaises(ValidationError):
            conv.save()


class AgentSettingsTests(TestCase):
    def test_kill_switch_starts_off(self):
        org = Organization.objects.create(name="AS Org", timezone="UTC")
        settings_obj = AgentSettings.objects.create(organization=org)
        self.assertFalse(settings_obj.enabled)
        self.assertEqual(settings_obj.faq_facts, {})


class RetiredFieldsTests(TestCase):
    """F5 · lo que se retiró no vuelve por descuido.

    `Conversation.summary` vivió desde É-F1 sin que nadie lo escribiera ni lo
    leyera. La continuidad se resolvió por otro camino —el transcript se lee por
    contacto (F2), los hechos duraderos salen de tools (F4)— y un resumen
    generado por el LLM habría sido una segunda fuente de verdad (ADR p50).

    Este test existe porque un campo muerto no es una decisión aplazada: es una
    invitación a llenarlo sin pensarlo. Si alguien lo reintroduce, que sea
    discutiéndolo, no de paso.
    """

    def test_conversation_has_no_summary_field(self):
        field_names = {f.name for f in Conversation._meta.get_fields()}
        self.assertNotIn('summary', field_names)
