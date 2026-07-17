"""
test_webhook.py — É-F0 PR-4: webhook de WhatsApp.

Cubre el contrato de seguridad (firma HMAC fail-closed, handshake) y el de
transporte (routing número→org R1, dedup R5, acuses de entrega). El payload
de fixture replica la forma real de Meta Cloud API.
"""
import hashlib
import hmac
import json

from django.test import TestCase, override_settings

from apps.agent.models import Conversation
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization

SECRET = "test-app-secret"
VERIFY = "test-verify-token"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _meta_payload(phone_number_id, wamid="wamid.001", wa_id="5215511223344",
                  text="hola", profile_name="Ana"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": phone_number_id},
                    "contacts": [{
                        "wa_id": wa_id,
                        "profile": {"name": profile_name},
                    }],
                    "messages": [{
                        "id": wamid,
                        "from": wa_id,
                        "timestamp": "1752600000",
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
            }],
        }],
    }


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY)
class WebhookHandshakeTests(TestCase):
    def test_valid_handshake_echoes_challenge(self):
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY,
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"12345")

    def test_wrong_verify_token_rejected(self):
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": "nope",
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 403)

    @override_settings(WHATSAPP_VERIFY_TOKEN="")
    def test_unconfigured_verify_token_rejects(self):
        """Fail-closed: sin token configurado no hay handshake válido."""
        r = self.client.get("/hooks/whatsapp/", {
            "hub.mode": "subscribe",
            "hub.verify_token": "",
            "hub.challenge": "12345",
        })
        self.assertEqual(r.status_code, 403)


@override_settings(WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY)
class WebhookSignatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="WH Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=cls.org, external_account_id="111222333",
        )

    def _post(self, payload, signature=None):
        body = json.dumps(payload).encode()
        headers = {}
        if signature is not None:
            headers["HTTP_X_HUB_SIGNATURE_256"] = signature
        return self.client.post(
            "/hooks/whatsapp/", body,
            content_type="application/json", **headers,
        )

    def test_missing_signature_rejected_nothing_persisted(self):
        r = self._post(_meta_payload("111222333"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Message.all_objects.count(), 0)

    def test_bad_signature_rejected_nothing_persisted(self):
        r = self._post(_meta_payload("111222333"), signature="sha256=" + "0" * 64)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Message.all_objects.count(), 0)

    @override_settings(WHATSAPP_APP_SECRET="")
    def test_unconfigured_secret_fails_closed(self):
        payload = _meta_payload("111222333")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 403)

    def test_valid_signature_ingests_message(self):
        payload = _meta_payload("111222333", wamid="wamid.SIG1")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)

        message = Message.objects.get(external_message_id="wamid.SIG1")
        self.assertEqual(message.organization, self.org)
        self.assertEqual(message.body, "hola")
        self.assertEqual(message.status, Message.STATUS_PENDING)
        conv = message.conversation
        self.assertEqual(conv.organization, self.org)
        self.assertEqual(conv.contact.display_name, "Ana")
        self.assertEqual(conv.contact.phone_normalized, "5511223344")

    def test_duplicate_delivery_is_deduped(self):
        payload = _meta_payload("111222333", wamid="wamid.DUP")
        body = json.dumps(payload).encode()
        for _ in range(3):
            r = self.client.post(
                "/hooks/whatsapp/", body, content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=_sign(body),
            )
            self.assertEqual(r.status_code, 200)
        self.assertEqual(
            Message.objects.filter(external_message_id="wamid.DUP").count(), 1
        )
        self.assertEqual(Conversation.objects.count(), 1)

    def test_unknown_phone_number_id_acks_without_persisting(self):
        """200 (cortar reintentos de Meta) pero cero escrituras."""
        payload = _meta_payload("999888777")
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Message.all_objects.count(), 0)

    def test_routing_by_receiving_number_is_org_exact(self):
        """R1: el mensaje aterriza en la org del NÚMERO receptor, jamás en
        otra — aunque el remitente sea cliente de ambas clínicas."""
        org_b = Organization.objects.create(name="WH Org B", timezone="UTC")
        ChannelAccount.objects.create(
            organization=org_b, external_account_id="444555666",
        )
        payload = _meta_payload("444555666", wamid="wamid.R1")
        body = json.dumps(payload).encode()
        self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        message = Message.objects.get(external_message_id="wamid.R1")
        self.assertEqual(message.organization, org_b)
        self.assertEqual(
            Message.objects.filter(organization=self.org).count(), 0
        )

    def test_status_update_marks_outbound_delivered(self):
        outbound = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta", status=Message.STATUS_SENT,
            external_message_id="wamid.OUT1",
        )
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "111222333"},
                "statuses": [{"id": "wamid.OUT1", "status": "delivered"}],
            }}]}],
        }
        body = json.dumps(payload).encode()
        r = self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        self.assertEqual(r.status_code, 200)
        outbound.refresh_from_db()
        self.assertEqual(outbound.status, Message.STATUS_DELIVERED)

    def test_late_sent_ack_does_not_degrade_read(self):
        outbound = Message.objects.create(
            organization=self.org, channel_account=self.channel,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            body="respuesta", status=Message.STATUS_READ,
            external_message_id="wamid.OUT2",
        )
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "111222333"},
                "statuses": [{"id": "wamid.OUT2", "status": "sent"}],
            }}]}],
        }
        body = json.dumps(payload).encode()
        self.client.post(
            "/hooks/whatsapp/", body, content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=_sign(body),
        )
        outbound.refresh_from_db()
        self.assertEqual(outbound.status, Message.STATUS_READ)  # forward-only
