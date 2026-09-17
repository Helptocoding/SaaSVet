"""Additive migration rehearsal using historical models, isolated test DB only."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class B4MigrationTests(TransactionTestCase):
    def test_legacy_rows_keep_states_ids_and_null_evidence(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        old = ('channels', '0012_b3_scope_and_membership')
        new = ('channels', '0013_b4_durable_sender')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        def restore():
            MigrationExecutor(connection).migrate(latest)
        self.addCleanup(restore)
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        org = apps.get_model('organizations', 'Organization').objects.create(name='B4 legacy', timezone='UTC')
        channel = apps.get_model('channels', 'ChannelAccount').objects.create(
            organization=org, external_account_id='b4-migration')
        OldMessage = apps.get_model('channels', 'Message')
        cases = [('pending', None), ('sent', 'wamid.legacy'), ('sent', None),
                 ('delivered', 'wamid.delivered'), ('read', 'wamid.read')]
        ids = [OldMessage.objects.create(organization=org, channel_account=channel,
            direction='out', author_type='system', body='historical', status=status,
            external_message_id=provider_id).pk for status, provider_id in cases]
        restore()
        from apps.channels.models import Message
        rows = list(Message.objects.filter(pk__in=ids).order_by('pk'))
        self.assertEqual([(row.status, row.external_message_id) for row in rows], cases)
        for row in rows:
            for field in ('send_token', 'send_started_at', 'send_lease_until', 'send_admitted_at',
                          'provider_accepted_at', 'delivered_at', 'read_at', 'uncertain_at',
                          'supersedes_message_id', 'origin_epoch'):
                self.assertIsNone(getattr(row, field), field)
