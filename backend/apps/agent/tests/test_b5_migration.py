"""B5 additive rehearsal: legacy open cases keep unknown operational evidence."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class B5MigrationTests(TransactionTestCase):
    def test_legacy_handoffs_have_no_synthetic_safety_notification_or_ack(self):
        self.assertEqual(connection.vendor, 'postgresql')
        old = ('agent', '0022_conversation_ownership_epoch_turnwork')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        def restore():
            MigrationExecutor(connection).migrate(latest)
        self.addCleanup(restore)
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        org = apps.get_model('organizations', 'Organization').objects.create(name='B5 legacy')
        channel = apps.get_model('channels', 'ChannelAccount').objects.create(
            organization=org, external_account_id='b5-legacy')
        contact = apps.get_model('agent', 'ContactIdentity').objects.create(organization=org, external_id='5215500000000')
        conv = apps.get_model('agent', 'Conversation').objects.create(organization=org,
            channel_account=channel, contact=contact)
        model = apps.get_model('agent', 'HumanHandoff')
        ids = [model.objects.create(organization=org, conversation=conv, reason_code=reason).pk
               for reason in ('emergency', 'explicit_request')]
        restore()
        from apps.agent.models import HumanHandoff
        rows = list(HumanHandoff.objects.filter(pk__in=ids).order_by('pk'))
        self.assertEqual([r.reason_code for r in rows], ['emergency', 'explicit_request'])
        for row in rows:
            self.assertEqual(row.safety_signals, [])
            for field in ('source_turn_id', 'source_message_id', 'event_key', 'guidance_message_id',
                          'guidance_epoch', 'notification_status', 'acknowledged_at', 'acknowledged_by_id'):
                self.assertIsNone(getattr(row, field))
