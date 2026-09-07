from importlib import import_module

from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, TransactionTestCase

from apps.billing.schema_contract import collect_billing_schema_drift


class BillingSchemaContractTests(TestCase):
    def test_clean_migration_schema_matches_runtime_model(self):
        self.assertEqual(collect_billing_schema_drift(), [])
        call_command('audit_billing_schema', verbosity=0)

    def test_replacement_graph_recognizes_the_orphaned_0026_identity(self):
        loader = MigrationLoader(connection)
        replacement = loader.disk_migrations[
            ('billing', '0026_checkout_checkoutestimate_checkoutevent_checkoutitem_and_more')
        ]
        self.assertEqual(replacement.replaces, [
            ('billing', '0026_checkout_checkoutitem_commandreceipt_and_more'),
        ])


class BillingSchemaRepairTests(TransactionTestCase):
    reset_sequences = True

    def test_repair_and_contract_are_idempotent_against_observed_drift(self):
        repair = import_module(
            'apps.billing.migrations.0033_repair_checkout_billing_schema'
        )
        contract = import_module(
            'apps.billing.migrations.0034_contract_legacy_invoice_anchors'
        )
        with connection.cursor() as cursor:
            cursor.execute(
                'ALTER TABLE billing_invoice ADD COLUMN confirmed_at timestamptz NULL'
            )
            cursor.execute(
                'ALTER TABLE billing_invoice '
                'ADD COLUMN confirmed_at_source varchar(24) NOT NULL'
            )
            cursor.execute(
                'CREATE INDEX idx_inv_org_status_conf '
                'ON billing_invoice (organization_id, status, confirmed_at)'
            )
            cursor.execute('DROP INDEX IF EXISTS idx_inv_org_status_post')
            cursor.execute(
                'DROP INDEX IF EXISTS payment_unique_child_per_command_receipt'
            )
            cursor.execute(
                'DROP INDEX IF EXISTS refundpayment_unique_child_per_command_receipt'
            )
            cursor.execute(
                'DROP INDEX IF EXISTS refundreversal_unique_child_per_command_receipt'
            )

        with connection.schema_editor() as schema_editor:
            repair.repair_and_verify(None, schema_editor)
        with connection.schema_editor() as schema_editor:
            contract.contract_legacy_invoice_anchors(None, schema_editor)
        with connection.schema_editor() as schema_editor:
            repair.repair_and_verify(None, schema_editor)
        with connection.schema_editor() as schema_editor:
            contract.contract_legacy_invoice_anchors(None, schema_editor)

        self.assertEqual(collect_billing_schema_drift(), [])
