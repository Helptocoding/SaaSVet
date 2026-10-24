"""M2 additive rehearsal with historical models and legacy writes, disposable DB."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MessageReplyMigrationTests(TransactionTestCase):
    def test_m2_preserves_existing_rows_and_legacy_writers(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        old = ('channels', '0015_b7b_receipt_guard')
        new = ('channels', '0016_message_reply_to')
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate([old])
        old_apps = executor.loader.project_state([old]).apps
        OldMessage = old_apps.get_model('channels', 'Message')
        org = old_apps.get_model('organizations', 'Organization').objects.create(name='M2 sintética', timezone='UTC')
        account = old_apps.get_model('channels', 'ChannelAccount').objects.create(
            organization=org, external_account_id='m2-legacy')
        for index, (direction, status) in enumerate((('in', 'processed'), ('in', 'discarded'),
                ('out', 'pending'), ('out', 'sent'), ('out', 'delivered'), ('out', 'read'), ('out', 'failed'))):
            OldMessage.objects.create(organization=org, channel_account=account, direction=direction,
                author_type='client' if direction == 'in' else 'system', status=status,
                body='Histórico sintético', external_message_id=f'm2-{index}', raw_metadata={'fixture': index})
        old_fields = [field.attname for field in OldMessage._meta.local_fields]
        before = list(OldMessage.objects.filter(organization=org).order_by('id').values(*old_fields))
        MigrationExecutor(connection).migrate([new])
        new_apps = MigrationExecutor(connection).loader.project_state([new]).apps
        NewMessage = new_apps.get_model('channels', 'Message')
        after = list(NewMessage.objects.filter(organization_id=org.pk).order_by('id').values(*old_fields))
        self.assertEqual(after, before)
        self.assertTrue(all(value is None for value in NewMessage.objects.filter(
            organization_id=org.pk).values_list('reply_to_id', flat=True)))
        # The old model doesn't know the new column: inserting without it must
        # still work during a rolling release or a code rollback.
        legacy = OldMessage.objects.create(organization=org, channel_account=account,
            direction='in', author_type='client', status='processed', body='Writer anterior')
        self.assertIsNone(NewMessage.objects.get(pk=legacy.pk).reply_to_id)
        quoted = NewMessage.objects.create(organization_id=org.pk, channel_account_id=account.pk,
            direction='out', author_type='system', status='pending', body='Writer nuevo', reply_to_id=legacy.pk)
        self.assertEqual(quoted.reply_to_id, legacy.pk)
        self.assertEqual(OldMessage.objects.get(pk=quoted.pk).body, 'Writer nuevo')
