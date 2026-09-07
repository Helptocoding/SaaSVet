"""Forward-only expand/verify repair for the divergent Checkout rollout.

This migration deliberately changes database state only.  Django's state already
describes the target objects because the larger 0026 was recorded as applied on
the affected databases.
"""

from django.db import migrations


ALLOWED_ANCHOR_SOURCES = {
    'service', 'audit_log', 'fallback', 'unresolved', 'legacy',
}


def _columns(cursor, table):
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        """,
        [table],
    )
    return {row[0] for row in cursor.fetchall()}


def repair_and_verify(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        raise RuntimeError('Billing schema reconciliation requires PostgreSQL.')

    with connection.cursor() as cursor:
        concurrently = '' if connection.in_atomic_block else ' CONCURRENTLY'
        tables = set(connection.introspection.table_names(cursor))
        required_tables = {
            'billing_invoice', 'billing_payment',
            'billing_refundpayment', 'billing_refundreversal',
        }
        missing_tables = sorted(required_tables - tables)
        if missing_tables:
            raise RuntimeError(
                'Billing schema preflight failed; missing tables: '
                + ', '.join(missing_tables)
            )

        invoice_columns = _columns(cursor, 'billing_invoice')
        required_invoice_columns = {
            'organization_id', 'status', 'created_at', 'posted_at',
            'posted_at_source',
        }
        missing_columns = sorted(required_invoice_columns - invoice_columns)
        if missing_columns:
            raise RuntimeError(
                'Billing schema preflight failed; billing_invoice is missing: '
                + ', '.join(missing_columns)
            )

        has_confirmed_at = 'confirmed_at' in invoice_columns
        has_confirmed_source = 'confirmed_at_source' in invoice_columns
        if has_confirmed_at != has_confirmed_source:
            raise RuntimeError(
                'Legacy Invoice anchor is partial: confirmed_at and '
                'confirmed_at_source must both exist or both be absent.'
            )

        if has_confirmed_at:
            cursor.execute(
                """
                SELECT DISTINCT confirmed_at_source
                FROM billing_invoice
                WHERE confirmed_at IS NOT NULL
                  AND confirmed_at_source IS NOT NULL
                """
            )
            unknown_sources = {
                row[0] for row in cursor.fetchall()
                if row[0] not in ALLOWED_ANCHOR_SOURCES
            }
            if unknown_sources:
                raise RuntimeError(
                    'Unknown confirmed_at_source values: '
                    + ', '.join(sorted(unknown_sources))
                )

            cursor.execute(
                """
                SELECT applied
                FROM django_migrations
                WHERE app = 'billing'
                  AND name = '0032_reconcile_checkout_schema'
                ORDER BY applied DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            reconcile_applied_at = row[0] if row else None

            # Preserve actual legacy confirmation provenance.  Rows which existed
            # before 0032 and merely received the field default are fallback only
            # when their anchor was derived from created_at.
            cursor.execute(
                """
                UPDATE billing_invoice
                SET posted_at = CASE
                        WHEN confirmed_at IS NOT NULL THEN confirmed_at
                        ELSE COALESCE(posted_at, created_at)
                    END,
                    posted_at_source = CASE
                        WHEN confirmed_at IS NOT NULL
                            THEN confirmed_at_source
                        WHEN %s IS NOT NULL
                             AND created_at <= %s
                             AND (posted_at IS NULL OR posted_at = created_at)
                            THEN 'fallback'
                        ELSE posted_at_source
                    END
                """,
                [reconcile_applied_at, reconcile_applied_at],
            )
        else:
            cursor.execute(
                """
                UPDATE billing_invoice
                SET posted_at = created_at,
                    posted_at_source = 'fallback'
                WHERE posted_at IS NULL
                """
            )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM billing_invoice
            WHERE posted_at IS NULL
               OR posted_at_source IS NULL
               OR posted_at_source NOT IN
                  ('service', 'audit_log', 'fallback', 'unresolved', 'legacy')
            """
        )
        invalid_anchors = cursor.fetchone()[0]
        if invalid_anchors:
            raise RuntimeError(
                f'Billing schema preflight found {invalid_anchors} invalid posted anchors.'
            )

        duplicate_checks = (
            ('billing_payment', 'payment_unique_child_per_command_receipt'),
            ('billing_refundpayment', 'refundpayment_unique_child_per_command_receipt'),
            ('billing_refundreversal', 'refundreversal_unique_child_per_command_receipt'),
        )
        for table, index_name in duplicate_checks:
            columns = _columns(cursor, table)
            needed = {'command_receipt_id', 'command_line_index'}
            if not needed.issubset(columns):
                raise RuntimeError(
                    f'{table} is missing command receipt identity columns.'
                )
            cursor.execute(
                f"""
                SELECT command_receipt_id, command_line_index, COUNT(*)
                FROM {table}
                WHERE command_receipt_id IS NOT NULL
                GROUP BY command_receipt_id, command_line_index
                HAVING COUNT(*) > 1
                LIMIT 1
                """
            )
            if cursor.fetchone():
                raise RuntimeError(
                    f'{table} contains duplicate command receipt child identities; '
                    f'cannot create {index_name}.'
                )

        cursor.execute(
            f"""
            CREATE INDEX{concurrently} IF NOT EXISTS idx_inv_org_status_post
            ON billing_invoice (organization_id, status, posted_at)
            """
        )
        cursor.execute(
            f"""
            CREATE UNIQUE INDEX{concurrently} IF NOT EXISTS payment_unique_child_per_command_receipt
            ON billing_payment (command_receipt_id, command_line_index)
            WHERE command_receipt_id IS NOT NULL
            """
        )
        cursor.execute(
            f"""
            CREATE UNIQUE INDEX{concurrently} IF NOT EXISTS refundpayment_unique_child_per_command_receipt
            ON billing_refundpayment (command_receipt_id, command_line_index)
            WHERE command_receipt_id IS NOT NULL
            """
        )
        cursor.execute(
            f"""
            CREATE UNIQUE INDEX{concurrently} IF NOT EXISTS refundreversal_unique_child_per_command_receipt
            ON billing_refundreversal (command_receipt_id, command_line_index)
            WHERE command_receipt_id IS NOT NULL
            """
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('billing', '0032_reconcile_checkout_schema'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(repair_and_verify, migrations.RunPython.noop),
            ],
            state_operations=[],
        ),
    ]
