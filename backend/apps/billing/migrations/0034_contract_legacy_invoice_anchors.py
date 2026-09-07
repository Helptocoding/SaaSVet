"""Contract the pre-Checkout Invoice lifecycle after 0033 verified provenance."""

from django.db import migrations


def contract_legacy_invoice_anchors(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        raise RuntimeError('Billing schema reconciliation requires PostgreSQL.')

    with connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS idx_inv_org_status_conf')
        cursor.execute(
            'ALTER TABLE billing_invoice DROP COLUMN IF EXISTS confirmed_at_source'
        )
        cursor.execute(
            'ALTER TABLE billing_invoice DROP COLUMN IF EXISTS confirmed_at'
        )


def irreversible_reverse(apps, schema_editor):
    raise RuntimeError(
        '0034 is forward-only: removed legacy anchor values cannot be reconstructed. '
        'Restore a verified database backup and roll forward instead.'
    )


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0033_repair_checkout_billing_schema'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    contract_legacy_invoice_anchors,
                    irreversible_reverse,
                ),
            ],
            state_operations=[],
        ),
    ]
