"""
test_providers.py — É-F0 PR-5: adaptador Meta Cloud API (HTTP mockeado).
"""
from unittest import mock

import requests
from django.test import TestCase, override_settings

from apps.channels.models import ChannelAccount
from apps.channels.providers import MetaWhatsAppProvider
from apps.organizations.models import Organization


def _response(status_code, payload=None):
    response = mock.Mock()
    response.status_code = status_code
    if payload is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = payload
    return response


@override_settings(WHATSAPP_API_BASE_URL="https://graph.test/v20.0")
class MetaProviderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        org = Organization.objects.create(name="Prov Org", timezone="UTC")
        cls.channel = ChannelAccount.objects.create(
            organization=org, external_account_id="123123123",
            provider_credentials_ref="WHATSAPP_ACCESS_TOKEN",
        )

    def _send(self, post_result=None, post_error=None):
        provider = MetaWhatsAppProvider(self.channel)
        with mock.patch.dict(
            "os.environ", {"WHATSAPP_ACCESS_TOKEN": "tok-123"},
        ), mock.patch("apps.channels.providers.requests.post") as post:
            if post_error is not None:
                post.side_effect = post_error
            else:
                post.return_value = post_result
            result = provider.send_text("5215511112222", "hola")
            return result, post

    def test_success_returns_wamid_and_builds_request(self):
        wamid, post = self._send(
            _response(200, {"messages": [{"id": "wamid.NEW"}]}),
        )
        self.assertEqual(wamid.kind, 'accepted')
        self.assertEqual(wamid.provider_id, "wamid.NEW")
        url = post.call_args.args[0]
        self.assertEqual(url, "https://graph.test/v20.0/123123123/messages")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok-123")
        self.assertEqual(kwargs["json"]["to"], "5215511112222")
        self.assertEqual(kwargs["json"]["text"]["body"], "hola")

    def test_5xx_is_uncertain(self):
        result, _ = self._send(_response(503))
        self.assertEqual(result.kind, 'uncertain')

    def test_429_is_retryable(self):
        result, _ = self._send(_response(429, {'error': {'code': 130429}}))
        self.assertEqual(result.kind, 'known_rejected')
        self.assertTrue(result.retryable)

    def test_4xx_is_not_retryable(self):
        result, _ = self._send(_response(400, {'error': {'code': 100}}))
        self.assertEqual(result.kind, 'known_rejected')
        self.assertFalse(result.retryable)

    def test_network_error_is_uncertain(self):
        result, _ = self._send(post_error=requests.ConnectTimeout("timeout"))
        self.assertEqual(result.kind, 'uncertain')

    def test_missing_token_is_not_retryable(self):
        provider = MetaWhatsAppProvider(self.channel)
        with mock.patch.dict("os.environ", {}, clear=False):
            # Garantizar ausencia del token en env y settings.
            with mock.patch(
                "apps.channels.providers.os.environ.get", return_value="",
            ), override_settings(WHATSAPP_ACCESS_TOKEN=""):
                result = provider.send_text("5215511112222", "hola")
        self.assertEqual(result.kind, 'known_rejected')
        self.assertFalse(result.retryable)

    def test_2xx_without_wamid_is_uncertain_no_retry(self):
        """No acceptance evidence; a later webhook might remain uncorrelatable."""
        wamid, _ = self._send(_response(200, {"unexpected": True}))
        self.assertEqual(wamid.kind, 'uncertain')
