"""SEND-02: HTTP success alone is not evidence of provider acceptance."""
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from apps.channels.providers import MetaWhatsAppProvider


class B4TransportTests(SimpleTestCase):
    def send(self, status=200, payload=None, exception=None):
        channel = Mock(external_account_id='b4', provider_credentials_ref='TOKEN')
        channel.get_access_token.return_value = 'test-token'
        response = Mock(status_code=status)
        if isinstance(payload, Exception):
            response.json.side_effect = payload
        else:
            response.json.return_value = payload
        with patch('apps.channels.providers.requests.post', return_value=response,
                   side_effect=exception) as post:
            result = MetaWhatsAppProvider(channel).send_text('5215512345678', 'test')
        self.assertEqual(post.call_args.kwargs['timeout'], 15)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        return result

    def test_accepted_requires_valid_message_id(self):
        result = self.send(payload={'messages': [{'id': 'wamid.B4'}]})
        self.assertEqual(result.kind, 'accepted')
        self.assertEqual(result.provider_id, 'wamid.B4')

    def test_send_fi_05_2xx_without_wamid_is_uncertain(self):
        for payload in ({}, {'messages': []}, {'messages': [{}]},
                        {'messages': [{'id': ''}]}, {'messages': [{'id': 42}]},
                        {'messages': [{'id': 'not-a-wamid'}]}, [], None,
                        {'messages': 'bad'}, {'messages': [None]},
                        {'messages': [{'id': 'wamid.valid'}], 'messaging_product': 'other'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.send(payload=payload).kind, 'uncertain')

    def test_send_fi_06_invalid_json_is_uncertain(self):
        self.assertEqual(self.send(payload=ValueError()).kind, 'uncertain')

    def test_send_fi_04_timeout_and_network_are_uncertain(self):
        for exception in (requests.Timeout(), requests.ConnectTimeout(),
                          requests.ConnectionError()):
            with self.subTest(exception=exception):
                self.assertEqual(self.send(exception=exception).kind, 'uncertain')

    def test_5xx_even_with_error_body_is_uncertain(self):
        self.assertEqual(self.send(500, {'error': {'code': 131000}}).kind, 'uncertain')

    def test_send_fi_07_explicit_4xx_rejection(self):
        result = self.send(401, {'error': {'code': 190}})
        self.assertEqual(result.kind, 'known_rejected')
        self.assertFalse(result.retryable)

    def test_only_explicit_rate_limit_is_safe_retry(self):
        result = self.send(429, {'error': {'code': 130429}})
        self.assertEqual(result.kind, 'known_rejected')
        self.assertTrue(result.retryable)
        self.assertEqual(self.send(429, {}).kind, 'uncertain')

    def test_unclassified_responses_are_uncertain(self):
        for status in (302, 400, 408, 429, 500):
            with self.subTest(status=status):
                self.assertEqual(self.send(status, {}).kind, 'uncertain')
