"""Additive B6 migration: no synthetic entity or provenance backfill."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class B6MigrationTests(TransactionTestCase):
    def test_legacy_goals_keep_unknown_binding_and_original_slots(self):
        self.assertEqual(connection.vendor, 'postgresql')
        old = ('agent', '0023_humanhandoff_acknowledged_at_and_more')
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        def restore():
            MigrationExecutor(connection).migrate(latest)
        self.addCleanup(restore)
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        apps = executor.loader.project_state([old]).apps
        org = apps.get_model('organizations', 'Organization').objects.create(name='B6 legacy')
        channel = apps.get_model('channels', 'ChannelAccount').objects.create(
            organization=org, external_account_id='b6-legacy')
        contact = apps.get_model('agent', 'ContactIdentity').objects.create(
            organization=org, external_id='5215500000000')
        conv = apps.get_model('agent', 'Conversation').objects.create(
            organization=org, channel_account=channel, contact=contact)
        slots = {'pet_handle': {'value': 'mascota_1', 'confidence': 1.0}}
        goal = apps.get_model('agent', 'ConversationGoal').objects.create(
            organization=org, conversation=conv, name='schedule_appointment', slots=slots)
        restore()
        from apps.agent.models import ConversationGoal
        from apps.agent import matter_binding
        row = ConversationGoal.objects.get(pk=goal.pk)
        self.assertEqual(row.slots, slots)
        self.assertEqual(row.binding_revision, 0)
        self.assertIsNone(row.bound_owner_id)
        self.assertIsNone(row.bound_pet_id)
        self.assertIsNone(row.bound_appointment_id)
        self.assertEqual(matter_binding.metadata(row), {})
        self.assertEqual(matter_binding.values(row), {})
