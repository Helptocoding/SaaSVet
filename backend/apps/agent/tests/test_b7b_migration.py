"""Additive receipt/evidence migration preserves legacy as unknown."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class B7BMigrationTests(TransactionTestCase):
    def test_no_synthetic_legacy_consent_or_emission(self):
        old = [('agent', '0025_conversation_operation_b7a'), ('channels', '0014_alter_message_semantic_type')]
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        org = apps.get_model('organizations', 'Organization').objects.create(name='B7B legacy')
        channel = apps.get_model('channels', 'ChannelAccount').objects.create(organization=org,
            external_account_id='b7b-migration')
        legacy = apps.get_model('channels', 'Message').objects.create(organization=org,
            channel_account=channel, direction='out', status='sent', body='Legacy confirmation')
        MigrationExecutor(connection).migrate(latest)
        from apps.agent.models import ConversationOperation
        from apps.channels.models import Message
        self.assertFalse(ConversationOperation.objects.exists())
        legacy = Message.objects.get(pk=legacy.pk)
        self.assertEqual(legacy.raw_metadata, {})
        self.assertIsNone(legacy.provider_accepted_at)
        self.assertIsNone(legacy.send_admitted_at)
