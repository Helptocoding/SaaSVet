"""Executable PostgreSQL contract for the post-Checkout Billing schema."""

from django.db import connection


CRITICAL_CHILD_IDENTITIES = {
    'billing_payment': (
        'payment_unique_child_per_command_receipt',
        ['command_receipt_id', 'command_line_index'],
    ),
    'billing_refundpayment': (
        'refundpayment_unique_child_per_command_receipt',
        ['command_receipt_id', 'command_line_index'],
    ),
    'billing_refundreversal': (
        'refundreversal_unique_child_per_command_receipt',
        ['command_receipt_id', 'command_line_index'],
    ),
}

UNIT_SNAPSHOT_CONTRACTS = {
    'billing_checkoutitem': (
        'conversion_factor_snapshot', True,
        'billing_checkout_item_factor_snapshot_valid',
    ),
    'billing_invoiceitem': (
        'conversion_factor_snapshot', True,
        'billing_invoice_item_factor_snapshot_valid',
    ),
    'inventory_medicalrecordproduct': (
        'conversion_factor_snapshot', False,
        'medicalrecordproduct_factor_snapshot_valid',
    ),
}

MULTILOT_UNIQUES = {
    'billing_stockdispositionevent': (
        'billing_stock_disposition_credit_allocation_unique',
        ['credit_note_item_id', 'allocation_id'],
        'billing_stock_disposition_per_credit_line',
    ),
    'billing_prescriptionfulfillmentevent': (
        'billing_rx_return_credit_allocation_unique',
        ['credit_note_item_id', 'allocation_id'],
        'billing_rx_return_once_per_credit_line',
    ),
}


def collect_billing_schema_drift():
    """Return every material model/state/physical-schema mismatch."""
    from .models import Invoice

    errors = []
    if connection.vendor != 'postgresql':
        return ['El contrato de Billing solo admite PostgreSQL.']

    expected_columns = {
        field.column: field.null for field in Invoice._meta.concrete_fields
    }
    expected_checks = {
        constraint.name for constraint in Invoice._meta.constraints
    }
    expected_indexes = {
        index.name: [
            Invoice._meta.get_field(field.lstrip('-')).column
            for field in index.fields
        ]
        for index in Invoice._meta.indexes
    }

    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
        required_tables = {
            'billing_invoice',
            *CRITICAL_CHILD_IDENTITIES,
            *UNIT_SNAPSHOT_CONTRACTS,
            *MULTILOT_UNIQUES,
        }
        for table in sorted(required_tables - tables):
            errors.append(f'Falta la tabla física {table}.')
        if 'billing_invoice' not in tables:
            return errors

        description = connection.introspection.get_table_description(
            cursor, 'billing_invoice',
        )
        physical_columns = {field.name: field.null_ok for field in description}
        for column in sorted(set(expected_columns) - set(physical_columns)):
            errors.append(f'billing_invoice no contiene la columna {column}.')
        for column in sorted(set(physical_columns) - set(expected_columns)):
            errors.append(f'billing_invoice conserva la columna no modelada {column}.')
        for column in sorted(set(expected_columns) & set(physical_columns)):
            if bool(physical_columns[column]) != bool(expected_columns[column]):
                errors.append(
                    f'billing_invoice.{column} nullability física='
                    f'{physical_columns[column]} modelo={expected_columns[column]}.'
                )

        constraints = connection.introspection.get_constraints(
            cursor, 'billing_invoice',
        )
        physical_checks = {
            name for name, metadata in constraints.items() if metadata.get('check')
        }
        for name in sorted(expected_checks - physical_checks):
            errors.append(f'Falta el CHECK de Invoice {name}.')
        for name in sorted(physical_checks - expected_checks):
            errors.append(f'Invoice conserva el CHECK no modelado {name}.')
        for name, columns in expected_indexes.items():
            metadata = constraints.get(name)
            if not metadata or not metadata.get('index'):
                errors.append(f'Falta el índice de Invoice {name}.')
            elif metadata.get('columns') != columns:
                errors.append(
                    f'Índice {name} columnas={metadata.get("columns")} '
                    f'esperadas={columns}.'
                )
        if 'idx_inv_org_status_conf' in constraints:
            errors.append('Invoice conserva el índice legacy idx_inv_org_status_conf.')

        for table, (name, columns) in CRITICAL_CHILD_IDENTITIES.items():
            if table not in tables:
                continue
            table_constraints = connection.introspection.get_constraints(cursor, table)
            metadata = table_constraints.get(name)
            if not metadata or not metadata.get('unique'):
                errors.append(f'Falta el UNIQUE parcial {name}.')
            elif metadata.get('columns') != columns:
                errors.append(
                    f'UNIQUE {name} columnas={metadata.get("columns")} '
                    f'esperadas={columns}.'
                )

        for table, (column, nullable, check_name) in UNIT_SNAPSHOT_CONTRACTS.items():
            if table not in tables:
                continue
            table_description = connection.introspection.get_table_description(
                cursor, table,
            )
            physical = {field.name: field.null_ok for field in table_description}
            if column not in physical:
                errors.append(f'{table} no contiene la columna {column}.')
            elif bool(physical[column]) != nullable:
                errors.append(
                    f'{table}.{column} nullability física={physical[column]} '
                    f'esperada={nullable}.'
                )
            table_constraints = connection.introspection.get_constraints(cursor, table)
            if not table_constraints.get(check_name, {}).get('check'):
                errors.append(f'Falta el CHECK {check_name}.')

        for table, (name, columns, legacy_name) in MULTILOT_UNIQUES.items():
            if table not in tables:
                continue
            table_constraints = connection.introspection.get_constraints(cursor, table)
            metadata = table_constraints.get(name)
            if not metadata or not metadata.get('unique'):
                errors.append(f'Falta el UNIQUE multi-lote {name}.')
            elif metadata.get('columns') != columns:
                errors.append(
                    f'UNIQUE {name} columnas={metadata.get("columns")} '
                    f'esperadas={columns}.'
                )
            if legacy_name in table_constraints:
                errors.append(f'{table} conserva el UNIQUE legacy {legacy_name}.')

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM django_migrations
                WHERE app = 'billing'
                  AND name = '0034_contract_legacy_invoice_anchors'
            )
            """
        )
        if not cursor.fetchone()[0]:
            errors.append('La migration contractual billing.0034 no está registrada.')

        cursor.execute(
            """
            SELECT app, name
            FROM django_migrations
            WHERE (app = 'billing' AND name = '0035_unit_snapshots_and_multilot_returns')
               OR (app = 'inventory' AND name = '0026_medical_record_product_factor_snapshot')
            """
        )
        applied_unit_migrations = set(cursor.fetchall())
        expected_unit_migrations = {
            ('billing', '0035_unit_snapshots_and_multilot_returns'),
            ('inventory', '0026_medical_record_product_factor_snapshot'),
        }
        for app, name in sorted(expected_unit_migrations - applied_unit_migrations):
            errors.append(f'La migration contractual {app}.{name} no está registrada.')

    return errors
