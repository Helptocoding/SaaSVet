"""Additive B7A migration does not synthesize historical operations/evidence."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class B7AMigrationTests(TransactionTestCase):
    def test_no_backfill_of_legacy_proposals(self):
        self.assertEqual(connection.vendor, 'postgresql')
        old = ('agent', '0024_matter_binding_b6')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        def restore():
            MigrationExecutor(connection).migrate(latest)
        self.addCleanup(restore)
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        org = apps.get_model('organizations', 'Organization').objects.create(name='B7A legacy')
        channel = apps.get_model('channels', 'ChannelAccount').objects.create(organization=org, external_account_id='b7a-old')
        contact = apps.get_model('agent', 'ContactIdentity').objects.create(organization=org, external_id='5215500000001')
        flow = {'pending_action': {'tool': 'cancel_appointment', 'args': {'id': 1}}}
        conv = apps.get_model('agent', 'Conversation').objects.create(
            organization=org, channel_account=channel, contact=contact, flow=flow)
        restore()
        from apps.agent.models import ConversationOperation, ContactIdentity, Conversation
        self.assertFalse(ConversationOperation.objects.exists())
        self.assertEqual(ContactIdentity.objects.get(pk=contact.pk).authorization_revision, 0)
        self.assertEqual(Conversation.objects.get(pk=conv.pk).flow, flow)
