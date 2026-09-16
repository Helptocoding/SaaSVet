"""Adversarial authenticated HTTP webhook surface; no sender mocks required."""
import json
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.agent.tests.test_b4_sender import SenderFixture
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization
from .test_webhook import SECRET, _sign


@override_settings(WHATSAPP_APP_SECRET=SECRET)
class B4WebhookTests(SenderFixture, TestCase):
    def setUp(self):
        super().setUp()
        Message.objects.filter(pk=self.message.pk).update(status='sent', external_message_id='wamid.B4')

    def post(self, payload, valid=True):
        body = json.dumps(payload).encode()
        return self.client.post('/hooks/whatsapp/', body, content_type='application/json',
            HTTP_X_HUB_SIGNATURE_256=_sign(body) if valid else 'sha256=wrong')

    def payload(self, statuses, phone='b4'):
        return {'entry': [{'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': phone}, 'statuses': statuses}}]}]}

    def test_duplicate_and_reordered_events_keep_read_and_stable_timestamps(self):
        payload = self.payload([{'id': 'wamid.B4', 'status': status}
                               for status in ('read', 'read', 'delivered', 'delivered', 'sent')])
        self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(self.state(), 'read')
        stamps = (self.message.read_at, self.message.delivered_at)
        self.post(payload)
        self.state()
        self.assertEqual((self.message.read_at, self.message.delivered_at), stamps)

    def test_unknown_status_and_wamid_are_ignored(self):
        for status, wamid in [('alien', 'wamid.B4'), ('read', 'wamid.missing')]:
            self.assertEqual(self.post(self.payload([{'id': wamid, 'status': status}])).status_code, 200)
        self.assertEqual(self.state(), 'sent')

    def test_other_account_same_org_cannot_update(self):
        ChannelAccount.objects.create(organization=self.org, external_account_id='other-account')
        self.post(self.payload([{'id': 'wamid.B4', 'status': 'read'}], 'other-account'))
        self.assertEqual(self.state(), 'sent')

    def test_other_org_correct_wamid_cannot_update(self):
        org = Organization.objects.create(name='B4 other', timezone='UTC')
        ChannelAccount.objects.create(organization=org, external_account_id='other-org')
        self.post(self.payload([{'id': 'wamid.B4', 'status': 'read'}], 'other-org'))
        self.assertEqual(self.state(), 'sent')

    def test_unsigned_status_cannot_mutate(self):
        response = self.post(self.payload([{'id': 'wamid.B4', 'status': 'read'}]), valid=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.state(), 'sent')

    def test_malformed_signed_structures_are_acknowledged_without_mutation(self):
        for payload in (None, [], 'x', {'entry': 3}, {'entry': [None]},
                        {'entry': [{'changes': [None, {'value': 'bad'}]}]},
                        self.payload('bad'), self.payload([None, [], {'id': [], 'status': {}}]),
                        self.payload([{'id': 'wamid.B4', 'status': [], 'errors': ['bad']}] )):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(self.state(), 'sent')

    def test_late_webhook_reconciles_uncertain_with_exact_correlation(self):
        stamp = timezone.now()
        Message.objects.filter(pk=self.message.pk).update(status='uncertain', uncertain_at=stamp)
        self.post(self.payload([{'id': 'wamid.B4', 'status': 'delivered'}]))
        self.assertEqual(self.state(), 'delivered')
        self.assertEqual(self.message.uncertain_at, stamp)

    def test_failed_after_read_does_not_degrade_or_copy_provider_pii(self):
        self.post(self.payload([{'id': 'wamid.B4', 'status': 'read'},
            {'id': 'wamid.B4', 'status': 'failed', 'errors': [{'title': 'private details'}]}]))
        self.assertEqual(self.state(), 'read')
        self.assertNotIn('private details', self.message.failure_reason)
