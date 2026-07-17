"""
test_models.py — É-F0 PR-3: invariantes de los modelos de transporte.

Los dos constraints load-bearing del subsistema:
  - Dedup de reintentos del webhook (R5): unique parcial por
    (channel_account, wamid) SOLO inbound. Se prueba en ambas capas:
    full_clean (ValidationError) y DB (IntegrityError con validate=False).
  - Enrutamiento número→org (R1): external_account_id unique GLOBAL.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization


def _make_channel(org, phone_number_id):
    return ChannelAccount.objects.create(
        organization=org, external_account_id=phone_number_id,
    )


def _make_inbound(org, channel, wamid, **kwargs):
    defaults = dict(
        organization=org,
        channel_account=channel,
        direction=Message.DIRECTION_IN,
        author_type=Message.AUTHOR_CLIENT,
        body="hola",
        external_message_id=wamid,
    )
    defaults.update(kwargs)
    return Message(**defaults)


class MessageDedupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Chan Org", timezone="UTC")
        cls.channel = _make_channel(cls.org, "111000111")

    def test_duplicate_inbound_wamid_rejected_by_full_clean(self):
        _make_inbound(self.org, self.channel, "wamid.AAA").save()
        with self.assertRaises(ValidationError):
            _make_inbound(self.org, self.channel, "wamid.AAA").save()

    def test_duplicate_inbound_wamid_rejected_by_db_constraint(self):
        """Aunque un caller salte full_clean (save(validate=False)), la DB
        rechaza — el dedup no depende de disciplina del caller (patrón
        Payment.idempotency_key, ADR p27)."""
        _make_inbound(self.org, self.channel, "wamid.BBB").save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            _make_inbound(self.org, self.channel, "wamid.BBB").save(validate=False)

    def test_same_wamid_on_outbound_is_allowed(self):
        """El constraint es SOLO inbound: el wamid que el proveedor asigna a
        un saliente no participa del dedup."""
        _make_inbound(self.org, self.channel, "wamid.CCC").save()
        out = Message(
            organization=self.org,
            channel_account=self.channel,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta",
            external_message_id="wamid.CCC",
        )
        out.save()  # no levanta

    def test_inbound_without_wamid_is_allowed_multiple_times(self):
        """external_message_id NULL no participa del unique parcial."""
        _make_inbound(self.org, self.channel, None).save()
        _make_inbound(self.org, self.channel, None).save()  # no levanta


class ChannelAccountRoutingTests(TestCase):
    def test_external_account_id_is_globally_unique(self):
        """R1: un número pertenece a exactamente UNA organización — el
        constraint es global, no por org."""
        org_a = Organization.objects.create(name="Chan Org A", timezone="UTC")
        org_b = Organization.objects.create(name="Chan Org B", timezone="UTC")
        _make_channel(org_a, "222000222")
        with self.assertRaises(ValidationError):
            _make_channel(org_b, "222000222")
